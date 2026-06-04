# CLAUDE.md — orientation for AI agents working in this repo

Self-hosted "scrape anything from any website" platform (browse.ai-style). Two scrape
modes — **natural-language** (LLM agent) and **visual click-to-select** — plus on-site
**discovery**, **change monitoring with alerts**, and an **output preview** before runs.

## Stack
- **Backend:** Django 5.1 + DRF + SimpleJWT + Celery + Redis + Postgres. Runs via
  `docker compose` (services: backend `:8000`, frontend `:3000`, db `:5432`, redis,
  celery_worker, celery_beat, flower `:5555`).
- **Frontend:** Next.js (App Router, TypeScript) in `frontend/`. The original empty
  Flutter scaffold was replaced — ignore any Flutter references in `README.md`.
- **LLM:** Google **Gemini** (cost minimization is a hard requirement). Extraction uses
  `gemini-2.5-flash-lite` (high volume), planning uses `gemini-2.5-flash` (one call).
  Factory: `backend/apps/scraper/agent/llm.py` (`get_llm(role='planner'|'extractor')`).
  `gemini-2.0-flash` is retired — do not use.

## How the scrape pipeline fits together
- **LangGraph agent** `backend/apps/scraper/agent/graph.py` — `planner → harvest` loop;
  dynamic per-column Pydantic models; follows detail links. Prompt-mode jobs use this.
- **Engines** `backend/apps/scraper/engines/` — `Crawl4AIEngine` (Playwright, primary),
  `FirecrawlEngine` (managed fallback), `fetch_with_fallback`. `scan_full_page` is a
  threaded param: **True for real runs** (loads infinite-scroll content), **False for
  preview** (speed).
- **CSS path** `scraping_engine.py` (`ScrapingEngine`) — deterministic extraction for
  visual/cached-selector jobs; follows "next" pagination via `discover_next_url`.
- **CSS-schema caching** — after a single-page agent run, a verified CSS schema is cached
  on the job so future runs skip the LLM (`tasks._maybe_cache_css_schema`); self-heals on 0 rows.
- **Discovery** `discovery.py` — `discover_sections` (nav→sections) + `discover_items`
  (repeating links→entries). Pure BeautifulSoup, no LLM. Scopes to the main content
  landmark; `_best_label` recovers titles from generic "View"/"Download" links.
- **Monitoring** `monitoring.py` — fingerprints each *successful* run and diffs vs the
  previous (added/removed/unchanged). `notifications.py` sends change alerts
  (Slack/Discord/webhook/email).
- **Output preview** `tasks.preview_scrape_task` — bounded one-page dry run (≤8 rows),
  persists nothing.
- **Destinations** `destinations/` — Postgres / Google Sheets / Webhook delivery after
  each run. Secrets encrypted at rest via `apps/core/crypto.py` (Fernet; `enc:` prefix).

## Key models (`backend/apps/scraper/models.py`)
`ScrapeJob` (mode prompt|visual, configuration JSON, schedule, `notify_on_change` /
`notify_config`), `JobRun` (status, stats incl. `stats['change']`, `content_index`),
`ScrapedItem` (deduped per job via `unique_together(job, unique_hash)` — that's why
change detection stores its own `content_index`), `DataDestination`, `ScrapeRecipe`.
Migrations: `0001`–`0006`.

## API (`/api/scraper/`)
`jobs/` (+`run`, `schedule`, `runs`, `items`, `export`, `test_alert`), `runs/`, `items/`,
`destinations/` (+`test`), `recipes/` (+`create_job`), `snapshot/`, `infer-selectors/`,
`discover-sections/`, `discover-items/`, `preview/`, `task-status/<id>/`.

## Frontend pages (`frontend/app/`)
`/` dashboard + create (+ Discover/Monitor/Recipes/Visual buttons), `/discover` wizard,
`/monitor` (create+schedule+alerts in one), `/recipes`, `/visual`, `/jobs/[id]`, `/login`.
API client: `frontend/lib/api.ts`.

## Conventions & gotchas (read before editing)
- **Commits/PRs: NEVER add AI/Claude attribution** (no `Co-Authored-By`, no "Generated
  with Claude" footer). Plain human-sounding messages.
- **Dual `.env`:** root `.env` (compose interpolation) AND `backend/.env` (Django
  `load_dotenv`, `override=False` so compose-set vars win). Models are hardcoded in
  `docker-compose.yml`; API keys intentionally not set there. `backend/.env` is gitignored
  — `SCRAPER_TIMEOUT=90` lives there; the committed `settings.py` default is also 90.
- **Docker-on-Windows file-watcher gap:** newly added frontend route/component files (and
  often edited backend modules / `urls.py`) do **not** hot-reload — the long-running
  server keeps stale code. After such changes run `docker compose restart frontend`
  (and/or `backend`). Symptom: new routes 404, or old behavior persists despite edits.
- **Slow sites are real:** some servers take 40–65s (e.g. myneta.info). Timeout is 90s;
  fetch waits for `domcontentloaded` (not `networkidle`, which can hang).
- **Verifying without the UI:** `docker compose exec -T backend python manage.py …`; for
  DRF endpoints use `APIClient` after `settings.ALLOWED_HOSTS += ['testserver']`.
- **Editing the project guide docx** (`docs/Super_Scraper_Project_Guide.docx`): append a
  new section to the *existing* file (unpack → edit XML → repack); never create a new docx.
  Check for a `~$…docx` Word lock file first.

## Outstanding follow-ups (backlog)
- **`README.md` is intentionally not maintained** — it still describes the old Flutter/GPT
  stack. Do **not** update it; keep `docs/` and this file current instead.
- **Secrets masking:** destination secrets are encrypted at rest but the serializer still
  returns them decrypted to the owner (so the edit UI works). Make `config` write-only /
  masked in responses as a hardening step.
- **Visual mode** lacks detail-link following (the NL agent has it); pagination works.
- **Google Sheets** delivery is built but not live-tested (needs a service-account JSON).
- **Future scope** (project guide Section 16): conversational refinement (multi-turn,
  needs a LangGraph checkpointer) and a web-search "universal" scraper (budget caps +
  source-consent UI).

## Where things are documented
- `docs/PROGRESS.md` — phase-by-phase log with per-file change tables (authoritative).
- `docs/Super_Scraper_Project_Guide.docx` — full project guide (Sections 1–19).
