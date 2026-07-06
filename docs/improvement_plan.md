# Code review — findings & improvement plan

Source: full-codebase review (2026-07-06) on branch `feature/retention-improvements`.
Overall verdict: architecture is sound (agent vs CSS path split, schema caching,
cost controls, defensive error handling). The items below are the bugs and gaps found,
ordered into shippable phases.

Verification for every phase: `docker compose exec -T backend python manage.py test`
(or an `APIClient` shell check), and remember the Docker-on-Windows gotcha —
`docker compose restart backend` after editing backend modules.

---

## Phase 1 — Secrets leak (finish the in-flight serializer change) ~30 min

- [x] `backend/apps/scraper/serializers.py` (`DataDestinationSerializer.to_representation`,
  ~line 272): the ad-hoc mask set `{'api_key', 'password', 'token', 'secret', 'webhook_url'}`
  misses the real secret keys. Postgres stores `dsn` (embeds the DB password), Sheets stores
  `credentials` / `credentials_json`, and the webhook stores its URL under `url` (the
  substring check `'webhook_url' in 'url'` is False) — all returned **decrypted** today.
  Fix: mask using `apps.core.crypto.SECRET_KEYS` so the two lists can never drift.
  Keep the existing `'********'` restore logic in `validate()` (round-trip already works).
- [x] Test: create postgres + webhook destinations, assert API response masks `dsn`/`url`,
  PATCH back with masked values, assert stored secrets survive.

## Phase 2 — Correctness bugs ~half a day

- [x] `tasks.py` ~321: failure path increments `job.total_runs`/`failed_runs` *then*
  retries — a run that fails twice and succeeds counts as 3 runs. Only update counters in
  terminal states; switch counters to `F()` expressions; use `update_fields` on the
  post-run `job.save()` (~line 277) so it can't clobber `configuration`.
- [x] `views.py` ~265 (`_export_csv`): fieldnames sampled from first 100 items; a later
  item with a new key makes `DictWriter.writerow` raise `ValueError` → 500. Compute
  fieldnames over all items or pass `extrasaction='ignore'`. Also run
  `sanitize_filename(job.name)` on all three export filenames.
- [x] `tasks.py` ~447 (`generate_ai_schema_task`): each `asyncio.run()` is a fresh event
  loop, so a Playwright browser started for URL 1 breaks on URL 2 / on close; and if the
  engine constructor raises, `finally` hits `NameError: engine`. Rewrite as one async
  function under a single `asyncio.run()`.
- [x] `tasks.py` ~174: `.exists()` → `.create()` dedupe isn't atomic; overlapping runs of
  the same job can raise `IntegrityError` on `unique_together(job, unique_hash)` and kill
  the run mid-save. Catch `IntegrityError` per item (count as duplicate), or
  `bulk_create(..., ignore_conflicts=True)` (also removes the N+1 exists query).
- [x] `scraping_engine.py` ~292 (`_fetch_with_browser`): still `wait_until='networkidle'`;
  the crawl4ai engine deliberately uses `domcontentloaded` because networkidle hangs on
  heavy/slow sites (myneta etc.). Align the visual path.

## Phase 3 — API payload / perf ~2 hours

- [x] `serializers.py` ~31: `JobRunSerializer.items_preview` serializes **all** items of a
  run, and `JobRunViewSet` uses it for list too → `GET /api/scraper/runs/` returns every
  item of every run. Cap via `SerializerMethodField` (first ~20) and use
  `JobRunListSerializer` for the list action.
- [x] `serializers.py` ~75: `ScrapeJobSerializer.recent_runs` serializes all runs forever;
  slice to the last ~10.
- [x] `views.py` ~393 (`statistics`): Python `sum()` over all job rows → one `.aggregate()`.

## Phase 4 — NL-agent (prompt-mode) improvements ~1 day

- [x] `agent/graph.py`: the agent never paginates — harvest follows detail links but never
  calls `discover_next_url`, so a prompt job with `max_pages=5` on a paginated list reads
  page 1 only on its first (agent) run. After harvesting a content page, discover the next
  URL from its HTML and enqueue it while under the page budget.
- [x] `agent/graph.py` 85 vs 157: first page is fetched twice (plan, then harvest). Stash
  the planner's `FetchResult` in state and reuse it. Saves up to ~1 min/run on slow sites.
- [x] `agent/graph.py` (`plan_node`): a failed first fetch still sends an empty page sample
  to the planner (hallucinated columns, wasted call). Bail out early when the fetch fails.
- [x] Temperature: `AI_TEMPERATURE` defaults to 0.7 (`settings.py` ~222, applied in
  `agent/llm.py` ~20). Use 0 for planner/extractor — determinism + stabler CSS-schema
  verification.
- [x] Scheduling: `check_scheduled_jobs` logs `jobs.count()` after mutating `next_run_at`
  (usually logs 0) — capture the count first. Make dispatch the single owner of
  `next_run_at` (remove the recompute at run completion in `execute_scrape_job` ~275) so
  hourly jobs don't drift by run duration and manual runs don't reshuffle the schedule.

## Phase 5 — Hardening backlog (opportunistic)

- [ ] SSRF: scrape URLs, webhook destinations, and notification targets are user-supplied
  URLs fetched/POSTed from the backend with no restrictions (internal network, metadata
  IPs). Add a shared private-IP/scheme guard if this ever goes multi-tenant.
- [x] `destinations/postgres.py`: table schema frozen at first delivery; new columns later
  make every INSERT fail. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` before insert.
- [x] `monitoring.py`: `diff_indexes` ignores the `truncated` flag — >5k-row jobs report
  phantom added/removed rows. Surface truncation instead of exact counts.
- [ ] `WebsiteDomain` model is unused — wire it into robots.txt caching / per-domain rate
  limits, or drop it.
- [x] CSV-injection escaping on export (cells starting with `=` `+` `-` `@`).
- [ ] Blocking calls (`requests.get`, `time.sleep`, `RateLimiter`) inside async methods in
  `scraping_engine.py` — swap to `httpx.AsyncClient` / `asyncio.sleep` if concurrency is
  ever wanted.
- [x] `discover_next_url` aria check (`'next' in aria`) can false-match labels like
  "next to…" — use word-boundary matching.
- [ ] Frontend stores JWTs in localStorage — accepted XSS tradeoff for self-hosted; note
  only.

---

Suggested order: Phase 1 + 2 immediately (small, fix real breakage; Phase 1 completes
work already uncommitted in the tree), Phase 4 next (the NL path is the headline
feature), Phases 3 and 5 as time allows.
