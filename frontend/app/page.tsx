'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import PreviewOutput from '@/components/PreviewOutput';
import { listJobs, createJob, getToken, parsePages, Job, ApiError } from '@/lib/api';

export default function Dashboard() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // create form
  const [name, setName] = useState('');
  const [urls, setUrls] = useState('');
  const [prompt, setPrompt] = useState('');
  const [js, setJs] = useState(false);
  const [respectRobots, setRespectRobots] = useState(true);
  const [pages, setPages] = useState('1');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.push('/login');
      return;
    }
    refresh();
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      setJobs(await listJobs());
    } catch (err) {
      const e = err as ApiError;
      if (e.status === 401) router.push('/login');
      else setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setCreating(true);
    try {
      const urlList = urls.split(/[\n,]+/).map((u) => u.trim()).filter(Boolean);
      const configuration: Record<string, any> = { urls: urlList, prompt };
      const job = await createJob({
        name,
        mode: 'prompt',
        configuration,
        use_js_rendering: js,
        respect_robots_txt: respectRobots,
        max_pages: parsePages(pages),
      });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <TopBar />
      <div className="container">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h1 style={{ margin: 0 }}>New scrape job</h1>
          <div className="row" style={{ gap: 8 }}>
            <button className="secondary" onClick={() => router.push('/discover')}>
              🧭 Discover
            </button>
            <button className="secondary" onClick={() => router.push('/visual')}>
              🖱 Visual selector
            </button>
          </div>
        </div>
        <p className="notice" style={{ margin: '6px 0 16px' }}>
          Describe what you want in natural language below, or use the visual selector to click fields on a live page.
        </p>
        <div className="card">
          <form onSubmit={submit}>
            <label>Job name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="WB 2021 candidates" />

            <label>URL(s) — one per line</label>
            <textarea value={urls} onChange={(e) => setUrls(e.target.value)} required placeholder="https://myneta.info/WestBengal2021/" />

            <label>What do you want to extract?</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              required
              placeholder="Get every constituency with its name and election date."
            />

            <label className="row" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={js} onChange={(e) => setJs(e.target.checked)} style={{ width: 'auto' }} />
              <span>Render JavaScript (slower, needed for SPA sites)</span>
            </label>

            <label className="row" style={{ marginTop: 8 }}>
              <input type="checkbox" checked={respectRobots} onChange={(e) => setRespectRobots(e.target.checked)} style={{ width: 'auto' }} />
              <span>Respect robots.txt (uncheck only if you have permission to scrape the site)</span>
            </label>

            <label style={{ marginTop: 12 }}>Pages to scrape</label>
            <input
              value={pages}
              onChange={(e) => setPages(e.target.value)}
              placeholder='1, 2, 3… or "all"'
              style={{ maxWidth: 220 }}
            />
            <span className="muted" style={{ fontSize: 12 }}>
              Number of pages to follow (auto-detects “next”). Use “all” to follow every page.
            </span>

            <PreviewOutput
              storageKey="dashboard"
              urls={urls.split(/[\n,]+/).map((u) => u.trim()).filter(Boolean)}
              prompt={prompt}
              useJs={js}
            />

            {error && <div className="error">{error}</div>}
            <div style={{ marginTop: 16 }}>
              <button type="submit" disabled={creating}>{creating ? 'Creating…' : 'Create job'}</button>
            </div>
          </form>
        </div>

        <h1 style={{ marginTop: 28 }}>Your jobs</h1>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : jobs.length === 0 ? (
          <p className="muted">No jobs yet. Create one above.</p>
        ) : (
          <div className="grid">
            {jobs.map((j) => (
              <div className="card" key={j.id} style={{ cursor: 'pointer' }} onClick={() => router.push(`/jobs/${j.id}`)}>
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <strong>{j.name}</strong>
                  <span className="badge">{j.mode}</span>
                </div>
                <p className="muted" style={{ margin: '8px 0 0' }}>
                  {j.total_items_scraped} items · {j.total_runs} runs · {j.status}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
