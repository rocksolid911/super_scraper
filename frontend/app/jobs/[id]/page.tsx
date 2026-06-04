'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import Schedule from '@/components/Schedule';
import Destinations from '@/components/Destinations';
import Alerts from '@/components/Alerts';
import PreviewOutput from '@/components/PreviewOutput';
import {
  getJob, jobRuns, jobItems, runJob, updateJob, getToken, exportUrl, parsePages, formatPages,
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
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const pollRef = useRef<any>(null);

  function toggleExpanded(runId: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  }

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

  async function toggleRobots(value: boolean) {
    setError('');
    try {
      const updated = await updateJob(id, { respect_robots_txt: value });
      setJob(updated);
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
    }
  }

  async function savePages(input: string) {
    setError('');
    try {
      const updated = await updateJob(id, { max_pages: parsePages(input) });
      setJob(updated);
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
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
          <label className="row" style={{ marginTop: 12, width: 'auto' }}>
            <input
              type="checkbox"
              checked={job?.respect_robots_txt ?? true}
              onChange={(e) => toggleRobots(e.target.checked)}
              style={{ width: 'auto' }}
            />
            <span>Respect robots.txt (uncheck only if you have permission to scrape the site)</span>
          </label>
          <div className="row" style={{ marginTop: 8, width: 'auto', gap: 8 }}>
            <span>Pages to scrape:</span>
            <input
              defaultValue={formatPages(job?.max_pages)}
              key={job?.max_pages}
              onBlur={(e) => savePages(e.target.value)}
              placeholder='1 or "all"'
              style={{ maxWidth: 100 }}
            />
            <span className="muted" style={{ fontSize: 12 }}>number, or “all”</span>
          </div>
          {job && (
            <PreviewOutput
              storageKey={`job-${id}`}
              urls={(job.configuration?.urls as string[]) || []}
              prompt={job.configuration?.prompt || job.configuration?.scrape_prompt}
              useJs={job.use_js_rendering}
              selectors={job.configuration?.selectors}
            />
          )}
          {error && <div className="error">{error}</div>}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>
          {job && <Schedule job={job} onUpdated={load} />}
          <Destinations jobId={id} />
        </div>

        {job && <Alerts job={job} onUpdated={load} />}

        <div className="card">
          <h2>Runs</h2>
          {runs.length === 0 ? (
            <p className="muted">No runs yet.</p>
          ) : (
            <table>
              <thead>
                <tr><th>#</th><th>Status</th><th>Items</th><th>Changes</th><th>Pages</th><th>Duration</th><th>When</th></tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const cs = r.change_summary;
                  const hasDiff = !!cs && !cs.first_run && cs.changed;
                  const isOpen = expanded.has(r.id);
                  return (
                    <Fragment key={r.id}>
                      <tr>
                        <td>{r.id}</td>
                        <td><span className={`badge ${r.status}`}>{r.status}</span></td>
                        <td>{r.items_scraped}</td>
                        <td>{renderChange(cs, hasDiff, isOpen, () => toggleExpanded(r.id))}</td>
                        <td>{r.pages_visited}</td>
                        <td>{r.duration_seconds ? `${r.duration_seconds.toFixed(1)}s` : '—'}</td>
                        <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
                      </tr>
                      {hasDiff && isOpen && (
                        <tr>
                          <td colSpan={7} style={{ background: 'var(--bg-alt, #f7f7f8)' }}>
                            <ChangeDetail cs={cs!} />
                          </td>
                        </tr>
                      )}
                      {r.error_message && (
                        <tr>
                          <td colSpan={7} className="error" style={{ fontSize: 13 }}>⚠ {r.error_message}</td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
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

function renderChange(
  cs: JobRun['change_summary'],
  hasDiff: boolean,
  isOpen: boolean,
  onToggle: () => void,
) {
  if (!cs || Object.keys(cs).length === 0) return <span className="muted">—</span>;
  if (cs.first_run) return <span className="badge">baseline</span>;
  if (!cs.changed) return <span className="muted">no change</span>;
  return (
    <button
      className="secondary"
      onClick={onToggle}
      style={{ padding: '2px 8px', fontSize: 12 }}
      title="Show what changed"
    >
      <span style={{ color: '#1a7f37' }}>+{cs.added ?? 0}</span>{' '}
      <span style={{ color: '#cf222e' }}>−{cs.removed ?? 0}</span>{' '}
      {isOpen ? '▲' : '▼'}
    </button>
  );
}

function ChangeDetail({ cs }: { cs: NonNullable<JobRun['change_summary']> }) {
  const added = cs.added_sample || [];
  const removed = cs.removed_sample || [];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, padding: 8, fontSize: 13 }}>
      <div>
        <strong style={{ color: '#1a7f37' }}>Added ({cs.added ?? 0})</strong>
        {added.length === 0 ? (
          <p className="muted" style={{ margin: '4px 0' }}>—</p>
        ) : (
          <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
            {added.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        )}
      </div>
      <div>
        <strong style={{ color: '#cf222e' }}>Removed ({cs.removed ?? 0})</strong>
        {removed.length === 0 ? (
          <p className="muted" style={{ margin: '4px 0' }}>—</p>
        ) : (
          <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
            {removed.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        )}
      </div>
    </div>
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
