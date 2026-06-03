# Super Scraper — Progress Tracker

> Last updated: 2026-06-03 · Branch: `initial-run-testing`

A self-hosted "scrape anything from any website" platform (a browse.ai-style product) with
two modes — **natural-language** (AI agent) and **visual click-to-select** — that outputs to
CSV/Excel/JSON, an external Postgres, Google Sheets, or webhooks, and can run on a schedule.

---

## Status at a glance

| Area | Status | Notes |
|------|--------|-------|
| Backend stabilization | ✅ Done & verified | admin, healthchecks, run lifecycle |
| NL agent (LangGraph + Gemini + Crawl4AI) | ✅ Done & verified live | quotes.toscrape.com, myneta.info |
| Visual selector (backend + UI) | ✅ Done & verified | snapshot + infer + click-to-select page |
| Data destinations (Postgres/Sheets/Webhook) | ✅ Built; PG+Webhook verified | Sheets needs service-account creds to live-test |
| CSS-schema caching (cost optimization) | ✅ Done & verified | run 2 skips the LLM |
| Frontend (Next.js) | ✅ Thin slice + visual + schedule/destinations | auth, jobs, run, results, export |
| Scheduling | ✅ UI + API verified | beat loop runs every 5 min (not long-run tested) |
| **On-site Discovery** | ✅ Done & verified | sections + entries + preview; recipe save |
| **Monitoring (change detection + alerts)** | ✅ Done & verified | diff, webhook alert, run history UI |
| **Output preview (dry run)** | ✅ Done & verified | pre-run sample, state persists across navigation |
| Deployment / PR | ⏳ Not pushed | local commits only |

---

## Phase log

### Phase 0 — Stabilize the backend ✅
- Fixed `/admin/` 500 (`admin.site.admin_view` → `admin.site.urls`).
- Fixed false-`unhealthy` Celery worker (image healthcheck probed :8000; override with `celery inspect ping`); later applied to beat (disabled) and flower (probe :5555).
- Removed **double `JobRun`** creation (view + task each made one) — task now reuses the view's run via `run_id`.
- Consolidated the per-URL `asyncio.run` loop into one event loop per run.
- Default AI model moved off the retired `gpt-4-turbo-preview`.
- **Verified:** `/admin/` 302, `/api/health/` 200, worker healthy.

### Phase 1 — Agentic NL engine ✅
- `engines/`: `Crawl4AIEngine` (fetch/render + CSS extraction, one browser per run), `FirecrawlEngine` fallback, `fetch_with_fallback`.
- `agent/`: LangGraph `StateGraph` (`planner → harvest` loop with detail-link following), dynamic per-column Pydantic models, Gemini via `langchain-google-genai`.
- **Cost split:** extraction `gemini-2.5-flash-lite`, planning `gemini-2.5-flash`.
- Wired into `execute_scrape_job`: prompt mode → agent; visual/cached → CSS.
- **Verified live:** quotes.toscrape.com (10 rows), myneta.info/WestBengal2021 (92 constituencies).

### Phase 2 — Visual selector backend ✅
- `POST /api/scraper/snapshot/` — Playwright DOM map (stable CSS selector + bbox + text per element) + full-page screenshot.
- `POST /api/scraper/infer-selectors/` — infers the repeating container, rewrites field selectors relative to it, returns sample rows.
- **Verified:** live snapshot (133 elements + screenshot), inference → 10 sample rows from real selectors.

### Phase 3 — Data destinations ✅
- `DataDestination` model + migration; `destinations/` package (Postgres, Google Sheets, Webhook); CRUD API + `test` action; delivery invoked after each run; shared `export_utils.flatten_items`.
- **Verified:** Postgres round-trip against real DB; webhook delivered to httpbin (200); invalid config rejected (400). Sheets built but not live-tested (needs creds).

### Phase 4 — Next.js frontend ✅
- Replaced the empty Flutter scaffold. App Router + TypeScript + JWT client (`lib/api.ts`).
- Login/register, dashboard (create NL job + list), job detail (run, poll, results table, CSV/Excel/JSON export), **visual selector page**, **schedule + destinations panels**.
- **Verified end-to-end:** register → login → create → run → 10 items; visual flow; schedule + destination tests.

### Phase 5 — End-to-end verification ✅
- Full-stack NL flow through the API (Celery + agent + Gemini) returning items.
- Visual path through HTTP (snapshot → infer → create visual job → run).

### Extra — CSS-schema caching ✅
- After a single-page agent run, derive + **verify** a CSS schema (≥60% of agent rows) and cache it on the job; future runs use the deterministic CSS path (no LLM). Self-heals (clears cache) when a cached run returns 0 rows.
- **Verified:** run 1 caches; run 2 extracts the same 10 rows with no agent invocation.

---

### Phase 6 — On-site Discovery (map_site + list_items) ✅

#### What it does
A new mode in which the user gives a URL, sees what sections the site has, picks one, then
multi-selects individual entries — before any scraping happens. The flow: URL → sections → entries
(pick-list) → describe what to extract → Create job / Save as recipe.

#### New files
| File | Purpose |
|------|---------|
| `backend/apps/scraper/discovery.py` | `discover_sections` (nav→section list) + `discover_items` (repeating-link pick-list). Pure BeautifulSoup, no LLM, no cost. Scopes to main content landmark (`<main>`/`article`/`#content`) rather than filtering chrome broadly. `_best_label` recovers proper titles from generic "View"/"Download" links by borrowing the row heading text. |
| `frontend/app/discover/page.tsx` | Discovery wizard UI: URL → section buttons → scrollable multi-select (nothing pre-checked) → 👁 Preview screenshot per entry → Create job / Save as recipe. |
| `frontend/components/PreviewOutput.tsx` | Reusable dry-run preview component (see Phase 8). |
| `backend/apps/scraper/migrations/0004_scraperecipe.py` | Migration for `ScrapeRecipe`. |

#### Changed files
| File | Change |
|------|--------|
| `backend/apps/scraper/models.py` | Added `ScrapeRecipe` model: `name`, `source_url`, `section_label`, `prompt`, `items` (JSON list of `{title, url}`), `selectors`, `use_js_rendering`, `respect_robots_txt`. `item_urls` property returns the selected entry URLs. |
| `backend/apps/scraper/serializers.py` | `DiscoverRequestSerializer`, `ScrapeRecipeSerializer` (with `item_urls` read-only). |
| `backend/apps/scraper/views.py` | `DiscoverSectionsView` (`POST /discover-sections/`), `DiscoverItemsView` (`POST /discover-items/`), `ScrapeRecipeViewSet` with `create_job` action that materialises a recipe into a prompt-mode `ScrapeJob`. |
| `backend/apps/scraper/urls.py` | Routes for `discover-sections/`, `discover-items/`, `recipes/` (router). |
| `backend/apps/scraper/admin.py` | `ScrapeRecipeAdmin` registered. |
| `frontend/lib/api.ts` | `discoverSections`, `discoverItems`, `listRecipes`, `createRecipe`, `deleteRecipe`, `createJobFromRecipe` + associated types. |
| `frontend/app/page.tsx` | 🧭 Discover button added next to Visual Selector. |

#### Discovery algorithm details
`discover_sections`: reads anchors from nav/header selectors; skips utility labels (login,
subscribe, social…) and off-site links; dedupes on label+URL.

`discover_items`: scopes to the page's main content landmark (`_content_root`); groups links by
ancestor shape (`_shape_key` — 3-level tag+class chain); selects the largest group as the dominant
listing. `_best_label` prefers `title`/`aria-label` attribute over truncated visible text (e.g.
books.toscrape book titles), and falls back to the surrounding row heading when the anchor text is
generic ("View", "Download", "PDF").

#### Save-as-recipe
After picking entries and entering a prompt, the user can save the selection as a `ScrapeRecipe`
without running a job. A recipe can later be re-run via `POST /api/scraper/recipes/{id}/create_job/`
which creates a fresh `ScrapeJob` with the recipe's URLs and prompt pre-populated.

#### Entry web preview (👁 Preview)
Each entry in the pick-list has a Preview button that renders a live screenshot via the existing
`/snapshot/` endpoint (with `wait_until='domcontentloaded'` and 60s timeout) and displays it inline
below the list. Snapshot timeout raised to 60s and switched from `networkidle` to `domcontentloaded`
to prevent hangs on heavy pages.

**Verified:** `discover_sections` on books.toscrape.com → 40 sections; `discover_items` → 20 book
titles (full, not truncated); adrindia.org reference page → 8 properly-titled PDF entries; all HTTP
endpoints 200/401/201/204; recipe create → `create_job` → delete round-trip verified.

---

### Phase 7 — Monitoring: change detection + alerts + run history diff ✅

#### What it does
Every successful run's content is fingerprinted and diffed against the previous run. When content
changes and the job opts in, a change alert fires to Slack, Discord, a webhook, or email. The job
detail page shows a **Changes** column in the Runs table (expandable diff with added/removed
samples) and an **Alerts** configuration panel.

#### New files
| File | Purpose |
|------|---------|
| `backend/apps/scraper/monitoring.py` | `build_content_index` — hashes each row (up to 5 000; previews for 500) after dedupe. `diff_indexes` — computes added/removed/unchanged counts and 25-row samples. `previous_indexed_run` — walks back up to 25 runs to find the last indexed baseline. |
| `backend/apps/scraper/notifications.py` | `send_change_alert` — delivers to each configured channel. Slack/Discord: HTTP POST `{"text": "…"}` or `{"content": "…"}`. Webhook: structured JSON payload with job, run, change, message. Email: Django mail backend. Per-channel failures are recorded, never fatal. |
| `backend/apps/scraper/migrations/0005_change_detection_and_alerts.py` | Adds `JobRun.content_index` (JSONField), `ScrapeJob.notify_on_change` (bool), `ScrapeJob.notify_config` (JSONField). |
| `frontend/components/Alerts.tsx` | Alert configuration panel: toggle on/off, add/remove channels (type + target), Save, Send test. Mirrors Destinations panel design. |

#### Changed files
| File | Change |
|------|--------|
| `backend/apps/scraper/models.py` | `JobRun.content_index` — server-side hash store (not serialized); `change_summary` property returns `stats['change']`. `ScrapeJob.notify_on_change`, `ScrapeJob.notify_config` — channel list lives here. |
| `backend/apps/scraper/tasks.py` | After finalization, calls `monitoring.build_content_index` + `diff_indexes`; stores result in `stats['change']`; if `notify_on_change` and `change.changed`, calls `send_change_alert`. Diffing never fails a run (try/except around it). |
| `backend/apps/scraper/serializers.py` | `change_summary` added to `JobRunSerializer` + `JobRunListSerializer`. `notify_on_change`, `notify_config` exposed on `ScrapeJobSerializer` + `CreateScrapeJobSerializer`. |
| `backend/apps/scraper/views.py` | `test_alert` action on `ScrapeJobViewSet` — sends a sample change payload to all configured channels; 400 if no channels configured. |
| `frontend/lib/api.ts` | `NotifyChannel`, `ChangeSummary` types; `notify_on_change`/`notify_config` on `Job`; `change_summary` on `JobRun`; `testAlert()` function. |
| `frontend/app/jobs/[id]/page.tsx` | Changes column in Runs table (`+N −N` button, expandable `ChangeDetail` component showing added/removed row samples). `Alerts` panel added below Schedule + Destinations. |

#### Change detection design
Only **successful** runs are indexed so a transient empty/failed run never becomes a baseline that
makes the next run look like a wholesale change. `content_index` is stored on `JobRun` but is not
serialized to the API (server-side only). The diff computes set differences on row hashes (not
content similarity), which is exact and cheap.

`notify_config` shape:
```json
{
  "channels": [
    {"type": "slack",   "target": "https://hooks.slack.com/…"},
    {"type": "discord", "target": "https://discord.com/api/webhooks/…"},
    {"type": "webhook", "target": "https://example.com/hook"},
    {"type": "email",   "target": "alerts@example.com"}
  ]
}
```

**Verified:** two-run live test (mystery books → travel books): RUN1 baseline (20 rows),
RUN2 → `changed=True`, `added=11`, `removed=20`, correct added_sample titles; webhook alert
delivered to httpbin (success); `test_alert` 200 with channel, 400 without; all routes compile.

---

### Phase 8 — Output preview (dry run before full run) ✅

#### What it does
A "🔎 Preview output" button on the dashboard create form and every job detail page dispatches a
bounded Celery task that fetches and LLM-extracts up to 8 rows from the first page only — without
persisting anything. The user sees sample columns and values before committing to a full run.
Preview state persists across navigation via `localStorage`, and resumes polling if the user
navigates away while the preview is in flight.

#### New files
| File | Purpose |
|------|---------|
| `frontend/components/PreviewOutput.tsx` | Reusable component. Reads/writes `localStorage` under `ss_preview_{storageKey}`. On mount: restores a finished result, or resumes polling a still-running task (Celery task ID persisted). Clear button drops stored state. |

#### Changed files
| File | Change |
|------|--------|
| `backend/apps/scraper/tasks.py` | `_preview_extract` async helper (one fetch + plan + extract, `scan_full_page=False` for speed). `preview_scrape_task` Celery task: dispatches CSS test or `_preview_extract` based on whether selectors exist; cleans and returns `{success, url, columns, rows, count, error}`. |
| `backend/apps/scraper/views.py` | `PreviewScrapeView` (`POST /api/scraper/preview/`) — validates URL(s) and dispatches `preview_scrape_task`; returns `{task_id}` immediately. |
| `backend/apps/scraper/urls.py` | `preview/` route. |
| `frontend/lib/api.ts` | `PreviewResult` type; `previewScrape()` (POST to `/preview/`); `taskStatus()` (polls `/task-status/{id}/`); `runPreview()` convenience poller (removed — polling now lives in the component). |
| `frontend/app/page.tsx` | `<PreviewOutput storageKey="dashboard" …>` wired into the create form with live URL/prompt/js values. |
| `frontend/app/jobs/[id]/page.tsx` | `<PreviewOutput storageKey={`job-{id}`} …>` wired with the job's config. |

**Verified:** preview on books.toscrape.com → 8 rows, correct columns, book detail links resolved
to absolute URLs; preview task dispatches as 202; `task-status` poll cycle confirmed.

---

### Phase 9 — Engine reliability fixes ✅

Three generic fixes applied across the fetch/extract pipeline. None are site-specific.

#### 1. Fetch timeout raised to 90s
`backend/.env`: `SCRAPER_TIMEOUT=30` → `90`.
`backend/config/settings.py`: default raised from 30 to 60 (env overrides).

Root cause: the headless browser's `page.goto()` had a 30s ceiling; slow server-rendered sites
(e.g. myneta.info PHP tables) take 38–64s to respond. The `goto` would throw → the engine returned
"fetch failed" → agent got zero content → 0 rows, but the run was marked **success**. Raising to
90s gives all slow sites headroom without changing behaviour for fast ones.

#### 2. scroll_full_page — on for real runs, off for preview
`backend/apps/scraper/engines/crawl4ai_engine.py`, `base.py`, `registry.py`, `firecrawl_engine.py`:
`scan_full_page` is now a threaded parameter (default **True**). Only `_preview_extract` in
`tasks.py` passes `scan_full_page=False` for speed (it samples page one only).

Real runs keep `scan_full_page=True` so infinite-scroll and lazy-loaded content loads automatically
with no user action. Verified: myneta with scroll on → 52.5s, full content, within 90s budget.

#### 3. Fetch errors now surface as run failures
`backend/apps/scraper/tasks.py`: added an `elif` after the robots/empty check — when
`items_created == 0` and `agent_errors` is non-empty, the run status is set to **failed** with a
human-readable message rather than a misleading empty success.

#### 4. URL post-processing — resolve relative links and strip markdown wrapping
`backend/apps/scraper/agent/graph.py`: `clean_url_value` + `absolutize_row_urls`.

Root cause: the LLM lifts hrefs from page markdown, where links are **relative** and/or wrapped in
markdown angle brackets (`<path>`). Two forms handled:
- `https://site/</rel/path?id=1>` → strips angle-bracket, resolves to absolute.
- `/rel/path?id=1` → resolves against the page URL.
- Non-URL strings (e.g. "Rs 4 Crore+", "Graduate") pass through unchanged.

Applied in `harvest_node` (every agent content extraction) and `_preview_extract` (preview task).

#### 5. `domcontentloaded` instead of `networkidle`
`backend/apps/scraper/visual.py` (snapshot), `engines/crawl4ai_engine.py` (run config): both now
wait for `domcontentloaded` rather than `networkidle`. Heavy pages whose background requests never
settle no longer hang the timeout. A short settle wait (800–1200ms) is kept for late content.

**Verified:** myneta winners page — with 90s timeout + scroll on → 52.5s, full markdown (95 659
chars). Preview (scroll off) → 14s on books.toscrape.com. Snapshot of a myneta candidate page →
23s, screenshot URL returned.

---

### Phase 10 — Hardening & UX polish ✅

- **Selector hardening:** `normalize_css_selector` rewrites jQuery-style `:contains(...)` to
  soupsieve's `:-soup-contains(...)` before `select()`, applied to container + field selectors.
- **Destination secret encryption at rest:** `apps/core/crypto.py` (Fernet, keyed off
  `SECRET_KEY`/`FIELD_ENCRYPTION_KEY`). Secret config keys are stored with an `enc:` prefix
  (idempotent, backward-compatible with plaintext rows; no-op if `cryptography` missing).
  `DataDestination.save()` encrypts; `decrypted_config` feeds handlers; serializer decrypts on
  read; migration 0006 encrypts existing rows. **Verified:** DB stores `enc:` ciphertext,
  `decrypted_config` returns plaintext.
- **Discover wizard state** persists to localStorage (sections/entries/selection survive
  navigation); Start-over button clears it.
- **Recipes page** (`/recipes`): list, run-as-job, delete saved recipes.
- **Monitor flow** (`/monitor`): create + schedule + enable change-alerts in one step.
  **Verified:** create 201 → schedule 200 → alerts 200.
- **Visual-mode pagination** hint surfaced (pagination already followed "next" via the CSS path).
- Default fetch timeout default raised to 90s in committed settings.

---

## Commit history (this effort)

```
1197c5c feat(frontend): recipes page, monitor flow, persisted discover wizard, visual paging hint
b00b0c7 feat(backend): encrypt destination secrets at rest; harden :contains selectors
d8a9cf8 docs: document discovery, monitoring, preview, and reliability work
0bd4ada feat(frontend): discovery wizard, alerts panel, run-diff view, persisted output preview
e73359e feat(scraper): on-site discovery, change monitoring, output preview, fetch reliability
8bd6ecb feat(frontend): scheduling and destinations management UI
48e0f99 feat(backend): cache derived CSS schema after agent runs to skip the LLM
eb33248 feat(frontend): visual click-to-select UI
3eff975 chore(compose): frontend service, Gemini env, and per-service healthchecks
ef808e1 feat(frontend): Next.js thin-slice UI (auth, jobs, run, results, export)
6871ba3 feat(backend): agentic Gemini scraper, visual selector, and data destinations
```

> Phases 6–9 are in the working tree (uncommitted) on `initial-run-testing`.

---

## Known limitations / not yet done

- **Google Sheets** delivery is implemented but not live-tested (needs a service-account JSON with edit access).
- **Scheduling** beat loop (`check_scheduled_jobs`, every 5 min) is wired and the UI works, but a full scheduled re-run wasn't observed over real time.
- **Visual mode** has no detail-link following (the NL agent does); pagination across pages works.
- **Secrets API exposure:** secrets are now encrypted at rest, but the destination serializer still returns decrypted values to the owner (so the edit UI works). Masking in API responses is a further hardening step.
- Docker-on-Windows: newly added frontend route/component files need a `docker compose restart frontend` (file-watcher gap); edits to existing files hot-reload.
- Nothing committed beyond `8bd6ecb` is on a PR yet (commits pushed to `initial-run-testing`).

## Suggested next steps

1. Open a PR for `initial-run-testing`.
2. Live-test Google Sheets with a real service account.
3. Visual-mode detail-link following (parity with the NL agent).
4. Mask secrets in destination API responses (write-only config).
5. Observability: surface LangSmith traces (already supported via env).
6. Future scope (Section 16 of the project guide): conversational refinement, web-search universal scraper.
