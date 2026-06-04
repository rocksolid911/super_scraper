'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import {
  snapshot, inferSelectors, createJob, getToken, mediaUrl, parsePages,
  SnapshotResult, SnapshotElement, FieldDef, InferResult, ApiError,
} from '@/lib/api';

function defaultAttr(el: SnapshotElement): { attr: string; type: string } {
  if (el.tag === 'a' && el.href) return { attr: 'href', type: 'url' };
  if (el.tag === 'img' && el.src) return { attr: 'src', type: 'url' };
  return { attr: 'text', type: 'string' };
}

export default function VisualSelector() {
  const router = useRouter();
  const [url, setUrl] = useState('');
  const [useJs, setUseJs] = useState(false);
  const [loading, setLoading] = useState(false);
  const [snap, setSnap] = useState<SnapshotResult | null>(null);
  const [fields, setFields] = useState<FieldDef[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  const [preview, setPreview] = useState<InferResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [respectRobots, setRespectRobots] = useState(true);
  const [pages, setPages] = useState('1');
  const [error, setError] = useState('');

  if (typeof window !== 'undefined' && !getToken()) {
    router.push('/login');
  }

  async function loadPage() {
    setError('');
    setLoading(true);
    setSnap(null);
    setFields([]);
    setPreview(null);
    try {
      const s = await snapshot(url, useJs);
      setSnap(s);
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : e.message);
    } finally {
      setLoading(false);
    }
  }

  function pick(el: SnapshotElement) {
    if (fields.some((f) => f.selector === el.selector)) return;
    const { attr, type } = defaultAttr(el);
    const base = (el.text || el.tag).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 20) || 'field';
    let nm = base;
    let i = 2;
    while (fields.some((f) => f.name === nm)) nm = `${base}_${i++}`;
    setFields([...fields, { name: nm, selector: el.selector, attr, type }]);
    setPreview(null);
  }

  function updateField(idx: number, patch: Partial<FieldDef>) {
    setFields(fields.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
    setPreview(null);
  }
  function removeField(idx: number) {
    setFields(fields.filter((_, i) => i !== idx));
    setPreview(null);
  }

  async function doPreview() {
    setError('');
    setPreviewing(true);
    try {
      const r = await inferSelectors(url, fields, useJs);
      setPreview(r);
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : e.message);
    } finally {
      setPreviewing(false);
    }
  }

  async function save() {
    if (!preview) return;
    setSaving(true);
    setError('');
    try {
      const job = await createJob({
        name: name || `Visual: ${url}`,
        mode: 'visual',
        configuration: { urls: [url], selectors: preview.selectors },
        use_js_rendering: useJs,
        respect_robots_txt: respectRobots,
        max_pages: parsePages(pages),
      });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
    } finally {
      setSaving(false);
    }
  }

  const sampleItems = preview?.sample?.items || [];
  const sampleCols = sampleItems.length
    ? Array.from(new Set(sampleItems.flatMap((r: any) => Object.keys(r))))
    : [];

  return (
    <>
      <TopBar />
      <div className="container" style={{ maxWidth: 1280 }}>
        <a href="#" onClick={(e) => { e.preventDefault(); router.push('/'); }}>← All jobs</a>
        <h1 style={{ marginTop: 12 }}>Visual selector</h1>

        <div className="card">
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <div style={{ flex: 1, minWidth: 280 }}>
              <label>Page URL</label>
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://quotes.toscrape.com/" />
            </div>
            <label className="row" style={{ width: 'auto' }}>
              <input type="checkbox" checked={useJs} onChange={(e) => setUseJs(e.target.checked)} style={{ width: 'auto' }} />
              <span>Render JS</span>
            </label>
            <button onClick={loadPage} disabled={loading || !url}>{loading ? 'Loading…' : 'Load page'}</button>
          </div>
          <p className="notice" style={{ marginTop: 8 }}>
            Load a page, then click elements in the preview to pick fields. Click the same kind of
            element in two different rows for best list detection.
          </p>
          {error && <div className="error">{error}</div>}
        </div>

        {snap && (
          <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 16, alignItems: 'start' }}>
            {/* Screenshot + overlays */}
            <div className="card" style={{ padding: 0, overflow: 'auto', maxHeight: 640 }}>
              <div style={{ position: 'relative', width: '100%' }}>
                <img
                  src={mediaUrl(snap.screenshot_url)}
                  alt="page snapshot"
                  style={{ width: '100%', display: 'block' }}
                />
                {snap.elements.map((el) => {
                  const selected = fields.some((f) => f.selector === el.selector);
                  return (
                    <div
                      key={el.id}
                      title={el.text || el.tag}
                      onMouseEnter={() => setHover(el.id)}
                      onMouseLeave={() => setHover((h) => (h === el.id ? null : h))}
                      onClick={() => pick(el)}
                      style={{
                        position: 'absolute',
                        left: `${(el.box.x / snap.width) * 100}%`,
                        top: `${(el.box.y / snap.height) * 100}%`,
                        width: `${(el.box.w / snap.width) * 100}%`,
                        height: `${(el.box.h / snap.height) * 100}%`,
                        cursor: 'pointer',
                        border: selected
                          ? '2px solid #22c55e'
                          : hover === el.id
                          ? '2px solid #6366f1'
                          : '1px solid transparent',
                        background: selected ? 'rgba(34,197,94,0.15)' : hover === el.id ? 'rgba(99,102,241,0.15)' : 'transparent',
                        boxSizing: 'border-box',
                      }}
                    />
                  );
                })}
              </div>
            </div>

            {/* Fields + preview */}
            <div>
              <div className="card">
                <h2>Fields ({fields.length})</h2>
                {fields.length === 0 ? (
                  <p className="muted">Click elements in the preview to add fields.</p>
                ) : (
                  fields.map((f, i) => (
                    <div key={i} style={{ borderBottom: '1px solid var(--border)', paddingBottom: 8, marginBottom: 8 }}>
                      <div className="row">
                        <input
                          value={f.name}
                          onChange={(e) => updateField(i, { name: e.target.value })}
                          style={{ flex: 1 }}
                        />
                        <select
                          value={f.attr}
                          onChange={(e) => updateField(i, { attr: e.target.value })}
                          style={{ width: 110 }}
                        >
                          <option value="text">text</option>
                          <option value="href">href</option>
                          <option value="src">src</option>
                          <option value="html">html</option>
                        </select>
                        <button className="secondary" onClick={() => removeField(i)}>✕</button>
                      </div>
                      <div className="muted" style={{ fontSize: 11, marginTop: 4, wordBreak: 'break-all' }}>{f.selector}</div>
                    </div>
                  ))
                )}
                <div className="row" style={{ marginTop: 8 }}>
                  <button onClick={doPreview} disabled={previewing || fields.length === 0}>
                    {previewing ? 'Sampling…' : 'Preview rows'}
                  </button>
                </div>
              </div>

              {preview && (
                <div className="card">
                  <h2>Preview</h2>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 8, wordBreak: 'break-all' }}>
                    container: <code>{preview.selectors.container || '(single item)'}</code>
                  </div>
                  {preview.sample?.error && <div className="error">{preview.sample.error}</div>}
                  {sampleItems.length === 0 ? (
                    <p className="muted">No rows matched. Try picking fields inside a repeating item.</p>
                  ) : (
                    <div className="table-wrap" style={{ maxHeight: 240 }}>
                      <table>
                        <thead><tr>{sampleCols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                        <tbody>
                          {sampleItems.slice(0, 10).map((r: any, ri: number) => (
                            <tr key={ri}>{sampleCols.map((c) => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <label>Job name</label>
                  <input value={name} onChange={(e) => setName(e.target.value)} placeholder={`Visual: ${url}`} />
                  <label className="row" style={{ marginTop: 10, width: 'auto' }}>
                    <input type="checkbox" checked={respectRobots} onChange={(e) => setRespectRobots(e.target.checked)} style={{ width: 'auto' }} />
                    <span>Respect robots.txt (uncheck only if you have permission to scrape the site)</span>
                  </label>
                  <label style={{ marginTop: 10 }}>Pages to scrape</label>
                  <input
                    value={pages}
                    onChange={(e) => setPages(e.target.value)}
                    placeholder='1, 2, 3… or "all"'
                    style={{ maxWidth: 220 }}
                  />
                  <span className="muted" style={{ fontSize: 12 }}>
                    Follows the “next” link automatically across pages. Use “all” to paginate to the end.
                  </span>
                  <div style={{ marginTop: 12 }}>
                    <button onClick={save} disabled={saving || sampleItems.length === 0}>
                      {saving ? 'Saving…' : 'Save as job'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
