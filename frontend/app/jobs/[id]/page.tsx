'use client';

import { useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import {
  getJob, jobRuns, jobItems, runJob, getToken, exportUrl,
  Job, JobRun, ScrapedItem, ApiError,
} from '@/lib/api';

export default function JobDetail() {
  const router = useRouter();
  const params = useParams();
  const id = Number(params.id);

  const [job, setJob] = useState<Job | null>(null);
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [items, setItems] = useState<ScrapedItem[]>([]);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);
  const pollRef = useRef<any>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push('/login');
      return;
    }
    load();
    return () => clearInterval(pollRef.current);
  }, [id]);

  async function load() {
    try {
      const [j, r, it] = await Promise.all([getJob(id), jobRuns(id), jobItems(id)]);
      setJob(j);
      setRuns(r);
      setItems(it);
      const active = r.some((run) => ['pending', 'running'].includes(run.status));
      if (active) startPolling();
      else stopPolling();
    } catch (err) {
      const e = err as ApiError;
      if (e.status === 401) router.push('/login');
      else setError(e.message);
    }
  }

  function startPolling() {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const r = await jobRuns(id);
      setRuns(r);
      if (!r.some((run) => ['pending', 'running'].includes(run.status))) {
        stopPolling();
        setItems(await jobItems(id));
        setRunning(false);
      }
    }, 2500);
  }
  function stopPolling() {
    clearInterval(pollRef.current);
    pollRef.current = null;
  }

  async function trigger() {
    setError('');
    setRunning(true);
    try {
      await runJob(id);
      startPolling();
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
      setRunning(false);
    }
  }

  async function doExport(fmt: 'csv' | 'xlsx' | 'json') {
    const res = await fetch(exportUrl(id), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ format: fmt }),
    });
    if (!res.ok) {
      setError('Export failed');
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${job?.name || 'export'}.${fmt}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const columns = deriveColumns(items);

  return (
    <>
      <TopBar />
      <div className="container">
        <a href="#" onClick={(e) => { e.preventDefault(); router.push('/'); }}>← All jobs</a>
        <h1 style={{ marginTop: 12 }}>{job?.name || 'Job'}</h1>

        <div className="card">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div className="row">
              <span className="badge">{job?.mode}</span>
              <span className="muted">{job?.total_items_scraped ?? 0} items total</span>
            </div>
            <div className="row">
              <button onClick={trigger} disabled={running}>{running ? 'Running…' : 'Run now'}</button>
              <button className="secondary" onClick={() => doExport('csv')}>CSV</button>
              <button className="secondary" onClick={() => doExport('xlsx')}>Excel</button>
              <button className="secondary" onClick={() => doExport('json')}>JSON</button>
            </div>
          </div>
          {error && <div className="error">{error}</div>}
        </div>

        <div className="card">
          <h2>Runs</h2>
          {runs.length === 0 ? (
            <p className="muted">No runs yet.</p>
          ) : (
            <table>
              <thead>
                <tr><th>#</th><th>Status</th><th>Items</th><th>Pages</th><th>Duration</th><th>When</th></tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td><span className={`badge ${r.status}`}>{r.status}</span></td>
                    <td>{r.items_scraped}</td>
                    <td>{r.pages_visited}</td>
                    <td>{r.duration_seconds ? `${r.duration_seconds.toFixed(1)}s` : '—'}</td>
                    <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h2>Results ({items.length})</h2>
          {items.length === 0 ? (
            <p className="muted">No items scraped yet. Hit “Run now”.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.id}>
                      {columns.map((c) => (
                        <td key={c}>{formatCell(it.data?.[c])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function deriveColumns(items: ScrapedItem[]): string[] {
  const set = new Set<string>();
  items.slice(0, 100).forEach((it) => {
    if (it.data && typeof it.data === 'object') Object.keys(it.data).forEach((k) => set.add(k));
  });
  return Array.from(set);
}

function formatCell(v: any): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
