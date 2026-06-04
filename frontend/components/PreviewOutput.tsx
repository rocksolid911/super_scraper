'use client';

import { useEffect, useRef, useState } from 'react';
import { previewScrape, taskStatus, PreviewResult, ApiError } from '@/lib/api';

/**
 * "Preview output" — runs a bounded dry run (one page, up to 8 rows) and shows the
 * extracted sample so the user can sanity-check before committing to a full run.
 *
 * State is persisted to localStorage (keyed by `storageKey`) so navigating away and
 * back keeps the result — and resumes polling if the preview was still running, since
 * the Celery task continues server-side and is retrievable by its task id.
 */
const lsKey = (k: string) => `ss_preview_${k}`;

export default function PreviewOutput({
  storageKey,
  urls,
  prompt,
  useJs,
  selectors,
}: {
  storageKey: string;
  urls: string[];
  prompt?: string;
  useJs?: boolean;
  selectors?: Record<string, any>;
}) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [error, setError] = useState('');
  const unmounted = useRef(false);

  const canPreview = urls.length > 0 && (!!prompt?.trim() || !!selectors?.fields);

  function persist(obj: { result?: PreviewResult; taskId?: string } | null) {
    try {
      if (obj) localStorage.setItem(lsKey(storageKey), JSON.stringify(obj));
      else localStorage.removeItem(lsKey(storageKey));
    } catch {
      /* ignore quota/availability errors */
    }
  }

  // Restore a saved result, or resume polling a still-running preview, on mount.
  useEffect(() => {
    unmounted.current = false;
    try {
      const raw = localStorage.getItem(lsKey(storageKey));
      if (raw) {
        const saved = JSON.parse(raw);
        if (saved.result) {
          setResult(saved.result);
        } else if (saved.taskId) {
          setLoading(true);
          poll(saved.taskId);
        }
      }
    } catch {
      /* ignore */
    }
    return () => {
      unmounted.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  function applyResult(res: PreviewResult) {
    persist({ result: res });
    if (unmounted.current) return; // came back later; restore handles display
    setResult(res);
    setLoading(false);
    if (!res.success && res.error) setError(res.error);
    else if (res.success && res.rows.length === 0) setError(res.error || 'No rows found on this page.');
  }

  async function poll(taskId: string) {
    for (let i = 0; i < 75; i++) {
      if (unmounted.current) return; // task keeps running server-side; we resume on return
      let s;
      try {
        s = await taskStatus(taskId);
      } catch (err) {
        if (!unmounted.current) {
          setError((err as ApiError).message);
          setLoading(false);
        }
        return;
      }
      if (s.ready) {
        applyResult(
          s.successful && s.result
            ? (s.result as PreviewResult)
            : { success: false, columns: [], rows: [], error: s.error || 'Preview failed' },
        );
        return;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    if (!unmounted.current) {
      setError('Preview timed out');
      setLoading(false);
    }
  }

  async function run() {
    setError('');
    setResult(null);
    setLoading(true);
    try {
      const { task_id } = await previewScrape({ urls, prompt, use_js_rendering: useJs, selectors });
      persist({ taskId: task_id }); // so a return mid-run resumes polling
      poll(task_id);
    } catch (err) {
      setError((err as ApiError).message);
      setLoading(false);
    }
  }

  function clear() {
    setResult(null);
    setError('');
    persist(null);
  }

  return (
    <div style={{ marginTop: 12 }}>
      <div className="row" style={{ gap: 8 }}>
        <button
          type="button"
          className="secondary"
          onClick={run}
          disabled={loading || !canPreview}
          title={canPreview ? 'Run a quick sample without saving' : 'Enter a URL and prompt first'}
        >
          {loading ? 'Previewing… (can take ~1 min)' : '🔎 Preview output'}
        </button>
        {(result || error) && !loading && (
          <button type="button" className="secondary" onClick={clear}>Clear</button>
        )}
      </div>

      {error && <div className="error" style={{ marginTop: 8 }}>{error}</div>}

      {result && result.success && result.rows.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <p className="muted" style={{ fontSize: 12, margin: '0 0 6px' }}>
            Sample of {result.rows.length} row{result.rows.length === 1 ? '' : 's'} from the first page —
            the full run may return more.
          </p>
          <table>
            <thead>
              <tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr key={i}>
                  {result.columns.map((c) => (
                    <td key={c}>{formatCell(row[c])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatCell(v: any): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
