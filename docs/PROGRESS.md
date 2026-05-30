# Super Scraper — Progress Tracker

> Last updated: 2026-05-30 · Branch: `initial-run-testing`

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

## Commit history (this effort)

```
8bd6ecb feat(frontend): scheduling and destinations management UI
48e0f99 feat(backend): cache derived CSS schema after agent runs to skip the LLM
eb33248 feat(frontend): visual click-to-select UI
3eff975 chore(compose): frontend service, Gemini env, and per-service healthchecks
ef808e1 feat(frontend): Next.js thin-slice UI (auth, jobs, run, results, export)
6871ba3 feat(backend): agentic Gemini scraper, visual selector, and data destinations
```

---

## Known limitations / not yet done

- **Google Sheets** delivery is implemented but not live-tested (needs a service-account JSON with edit access).
- **Scheduling** beat loop (`check_scheduled_jobs`, every 5 min) is wired and the UI works, but a full scheduled re-run wasn't observed over real time.
- The planner occasionally emits CSS `:contains(...)` → soupsieve deprecation warning (`:-soup-contains`). Harmless today; hardening pending.
- **Visual mode** has no pagination/detail-link following (the NL agent does); the existing CSS pagination config (`pagination`) is supported by `ScrapingEngine` but not surfaced in the visual UI yet.
- **Secrets** (destination DSNs, Sheets creds) are stored in plaintext JSON on `DataDestination.config` — encrypt at rest before production.
- Docker-on-Windows: **newly added** frontend route/component files need a `docker compose restart frontend` (file-watcher gap); edits to existing files hot-reload.
- Nothing pushed to a remote yet; no PR.

## Suggested next steps

1. Push `initial-run-testing` and open a PR.
2. Live-test Google Sheets with a real service account.
3. Harden selectors (`:contains` → `:-soup-contains`).
4. Visual-mode pagination + multi-page; destination secret encryption.
5. Observability: surface LangSmith traces (already supported via env).
