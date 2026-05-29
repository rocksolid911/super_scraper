'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import { listJobs, createJob, getToken, Job, ApiError } from '@/lib/api';

export default function Dashboard() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // create form
  const [name, setName] = useState('');
  const [mode, setMode] = useState<'prompt' | 'visual'>('prompt');
  const [urls, setUrls] = useState('');
  const [prompt, setPrompt] = useState('');
  const [js, setJs] = useState(false);
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
      const configuration: Record<string, any> = { urls: urlList };
      if (mode === 'prompt') configuration.prompt = prompt;
      const job = await createJob({
        name,
        mode,
        configuration,
        use_js_rendering: js,
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
        <h1>New scrape job</h1>
        <div className="card">
          <form onSubmit={submit}>
            <label>Job name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="WB 2021 candidates" />

            <label>Mode</label>
            <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
              <option value="prompt">Natural language (AI agent)</option>
              <option value="visual">Visual selector</option>
            </select>

            <label>URL(s) — one per line</label>
            <textarea value={urls} onChange={(e) => setUrls(e.target.value)} required placeholder="https://myneta.info/WestBengal2021/" />

            {mode === 'prompt' ? (
              <>
                <label>What do you want to extract?</label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  required
                  placeholder="Get every constituency with its name and election date."
                />
              </>
            ) : (
              <p className="notice">
                Visual selector picking UI is coming next. For now, create the job and configure
                selectors via the API (<code>/snapshot/</code> + <code>/infer-selectors/</code>).
              </p>
            )}

            <label className="row" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={js} onChange={(e) => setJs(e.target.checked)} style={{ width: 'auto' }} />
              <span>Render JavaScript (slower, needed for SPA sites)</span>
            </label>

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
