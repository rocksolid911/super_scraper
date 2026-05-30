# Super Scraper — Web Frontend (Next.js)

React/Next.js (App Router, TypeScript) UI for the super_scraper backend.

## Run

Via Docker Compose from the repo root (recommended):

```bash
docker compose up -d frontend
# http://localhost:3000
```

Or locally:

```bash
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_BASE` if the backend isn't at `http://localhost:8000/api`.

## What's here (thin vertical slice)

- **Login / register** against the DRF JWT endpoints (`lib/api.ts`).
- **Dashboard** (`app/page.tsx`) — list jobs and create a job (natural-language mode wired;
  visual mode UI is the next iteration).
- **Job detail** (`app/jobs/[id]/page.tsx`) — run a job, poll run status, view the results
  table, and export CSV / Excel / JSON.

Planned next: the visual click-to-select UI (using the backend `/snapshot/` and
`/infer-selectors/` endpoints), destination management, and scheduling.
