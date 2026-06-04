'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import {
  discoverSections, discoverItems, createJob, createRecipe, snapshot, mediaUrl, getToken,
  Section, DiscoverItem, SnapshotResult, ApiError,
} from '@/lib/api';

const DISCOVER_KEY = 'ss_discover_state';

export default function Discover() {
  const router = useRouter();

  const [url, setUrl] = useState('');
  const [useJs, setUseJs] = useState(false);
  const [respectRobots, setRespectRobots] = useState(true);

  const [sections, setSections] = useState<Section[] | null>(null);
  const [loadingSections, setLoadingSections] = useState(false);

  // The page currently being listed (a chosen section, or the entered URL itself).
  const [listingUrl, setListingUrl] = useState('');
  const [sectionLabel, setSectionLabel] = useState('');
  const [items, setItems] = useState<DiscoverItem[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loadingItems, setLoadingItems] = useState(false);

  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Web preview of a single entry (live screenshot via the snapshot endpoint).
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewShot, setPreviewShot] = useState<SnapshotResult | null>(null);
  const [previewing, setPreviewing] = useState(false);

  // Persist the wizard across navigation so a round-trip to the dashboard doesn't
  // wipe the discovered sections, entries, and selection.
  const restored = useRef(false);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(DISCOVER_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        if (s.url) setUrl(s.url);
        if (typeof s.useJs === 'boolean') setUseJs(s.useJs);
        if (typeof s.respectRobots === 'boolean') setRespectRobots(s.respectRobots);
        if (s.sections) setSections(s.sections);
        if (s.listingUrl) setListingUrl(s.listingUrl);
        if (s.sectionLabel) setSectionLabel(s.sectionLabel);
        if (s.items) setItems(s.items);
        if (Array.isArray(s.selected)) setSelected(new Set(s.selected));
        if (s.name) setName(s.name);
        if (s.prompt) setPrompt(s.prompt);
      }
    } catch {
      /* ignore */
    }
    restored.current = true;
  }, []);

  useEffect(() => {
    if (!restored.current) return; // don't clobber saved state on the first render
    try {
      localStorage.setItem(
        DISCOVER_KEY,
        JSON.stringify({
          url, useJs, respectRobots, sections, listingUrl, sectionLabel,
          items, selected: Array.from(selected), name, prompt,
        }),
      );
    } catch {
      /* ignore */
    }
  }, [url, useJs, respectRobots, sections, listingUrl, sectionLabel, items, selected, name, prompt]);

  function closePreview() {
    setPreviewUrl('');
    setPreviewShot(null);
  }

  async function preview(u: string) {
    setError('');
    setPreviewUrl(u);
    setPreviewShot(null);
    setPreviewing(true);
    try {
      setPreviewShot(await snapshot(u, useJs));
    } catch (err) {
      setError('Preview failed: ' + (err as ApiError).message);
      setPreviewUrl('');
    } finally {
      setPreviewing(false);
    }
  }

  if (typeof window !== 'undefined' && !getToken()) {
    router.push('/login');
  }

  function reset() {
    setSections(null);
    setItems(null);
    setSelected(new Set());
    setListingUrl('');
    setSectionLabel('');
    setError('');
    setNotice('');
    closePreview();
  }

  async function findSections(e: React.FormEvent) {
    e.preventDefault();
    reset();
    setLoadingSections(true);
    try {
      const res = await discoverSections(url, useJs);
      if (!res.success) throw new Error(res.error || 'Could not read this site');
      setSections(res.sections);
      if (res.sections.length === 0) {
        setNotice('No clear navigation found. You can still list this page directly below.');
      }
    } catch (err) {
      const e2 = err as ApiError;
      setError(typeof e2.detail === 'string' ? e2.detail : e2.message);
    } finally {
      setLoadingSections(false);
    }
  }

  async function listPage(targetUrl: string, label: string) {
    setError('');
    setNotice('');
    setItems(null);
    setSelected(new Set());
    setListingUrl(targetUrl);
    setSectionLabel(label);
    setLoadingItems(true);
    closePreview();
    try {
      const res = await discoverItems(targetUrl, useJs);
      if (!res.success) throw new Error(res.error || 'Could not read this page');
      setItems(res.items);
      // Nothing selected by default — the user opts into the entries they want.
      setSelected(new Set());
      if (res.items.length === 0) {
        setNotice('No repeating entries found here. You can scrape this page on its own.');
      }
    } catch (err) {
      const e2 = err as ApiError;
      setError(typeof e2.detail === 'string' ? e2.detail : e2.message);
    } finally {
      setLoadingItems(false);
    }
  }

  function toggle(u: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(u)) next.delete(u);
      else next.add(u);
      return next;
    });
  }

  function selectAll(on: boolean) {
    if (!items) return;
    setSelected(on ? new Set(items.map((it) => it.url)) : new Set());
  }

  // URLs to scrape: the chosen entries, or the listing page itself if none picked.
  function targetUrls(): string[] {
    const picked = (items || []).filter((it) => selected.has(it.url)).map((it) => it.url);
    return picked.length ? picked : (listingUrl ? [listingUrl] : []);
  }

  function selectionPayload() {
    return (items || []).filter((it) => selected.has(it.url));
  }

  async function createScrapeJob() {
    setError('');
    const urls = targetUrls();
    if (!name.trim()) return setError('Give the job a name.');
    if (!urls.length) return setError('Pick at least one entry, or list a page first.');
    if (!prompt.trim()) return setError('Describe what to extract from each entry.');
    setBusy('job');
    try {
      const job = await createJob({
        name,
        mode: 'prompt',
        configuration: { urls, prompt },
        use_js_rendering: useJs,
        respect_robots_txt: respectRobots,
        max_pages: 1,
      });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      const e2 = err as ApiError;
      setError(typeof e2.detail === 'string' ? e2.detail : JSON.stringify(e2.detail));
    } finally {
      setBusy('');
    }
  }

  async function saveAsRecipe() {
    setError('');
    setNotice('');
    if (!name.trim()) return setError('Give the recipe a name.');
    setBusy('recipe');
    try {
      await createRecipe({
        name,
        source_url: url,
        section_label: sectionLabel,
        prompt,
        items: selectionPayload(),
        use_js_rendering: useJs,
        respect_robots_txt: respectRobots,
      });
      setNotice('Saved as a recipe — reuse it anytime from the dashboard.');
    } catch (err) {
      const e2 = err as ApiError;
      setError(typeof e2.detail === 'string' ? e2.detail : JSON.stringify(e2.detail));
    } finally {
      setBusy('');
    }
  }

  const selectedCount = selected.size;

  return (
    <>
      <TopBar />
      <div className="container">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h1 style={{ margin: 0 }}>Discover &amp; scrape</h1>
          <div className="row" style={{ gap: 8 }}>
            <button className="secondary" onClick={() => { reset(); setUrl(''); setName(''); setPrompt(''); }}>
              Start over
            </button>
            <button className="secondary" onClick={() => router.push('/')}>← Dashboard</button>
          </div>
        </div>
        <p className="notice" style={{ margin: '6px 0 16px' }}>
          Paste a site URL, see what sections it has, pick a section, then choose the
          entries you want to scrape.
        </p>

        {/* Step 1 — URL */}
        <div className="card">
          <form onSubmit={findSections}>
            <label>Website URL</label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              placeholder="https://example.com"
            />
            <label className="row" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={useJs} onChange={(e) => setUseJs(e.target.checked)} style={{ width: 'auto' }} />
              <span>Render JavaScript (slower, needed for SPA sites)</span>
            </label>
            <label className="row" style={{ marginTop: 8 }}>
              <input type="checkbox" checked={respectRobots} onChange={(e) => setRespectRobots(e.target.checked)} style={{ width: 'auto' }} />
              <span>Respect robots.txt when scraping</span>
            </label>
            <div style={{ marginTop: 16 }} className="row">
              <button type="submit" disabled={loadingSections}>
                {loadingSections ? 'Reading…' : 'Find sections'}
              </button>
              {url && (
                <button type="button" className="secondary" onClick={() => listPage(url, '')}>
                  List this page directly
                </button>
              )}
            </div>
          </form>
        </div>

        {error && <div className="error" style={{ marginTop: 16 }}>{error}</div>}
        {notice && <div className="notice" style={{ marginTop: 16 }}>{notice}</div>}

        {/* Step 2 — sections */}
        {sections && sections.length > 0 && (
          <>
            <h1 style={{ marginTop: 28, fontSize: 20 }}>Sections on this site</h1>
            <div className="card">
              <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
                {sections.map((s) => (
                  <button
                    key={s.url}
                    className={listingUrl === s.url ? '' : 'secondary'}
                    onClick={() => listPage(s.url, s.label)}
                    title={s.url}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {/* Step 3 — items (also the live preview) */}
        {(loadingItems || items) && (
          <>
            <h1 style={{ marginTop: 28, fontSize: 20 }}>
              {sectionLabel ? `Entries in “${sectionLabel}”` : 'Entries on this page'}
            </h1>
            <div className="card">
              {loadingItems ? (
                <p className="muted">Loading entries…</p>
              ) : items && items.length > 0 ? (
                <>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                    <span className="muted">
                      {selectedCount} of {items.length} selected
                    </span>
                    <span className="row" style={{ gap: 8 }}>
                      <button className="secondary" onClick={() => selectAll(true)}>Select all</button>
                      <button className="secondary" onClick={() => selectAll(false)}>Clear</button>
                    </span>
                  </div>
                  <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                    {items.map((it) => (
                      <div
                        key={it.url}
                        className="row"
                        style={{ padding: '4px 0', gap: 8, justifyContent: 'space-between' }}
                      >
                        <span className="row" style={{ gap: 8, minWidth: 0 }}>
                          <input
                            type="checkbox"
                            checked={selected.has(it.url)}
                            onChange={() => toggle(it.url)}
                            style={{ width: 'auto' }}
                          />
                          <a
                            href={it.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={it.url}
                            style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          >
                            {it.title}
                          </a>
                        </span>
                        <button
                          className="secondary"
                          onClick={() => preview(it.url)}
                          style={{ padding: '2px 8px', fontSize: 12, flexShrink: 0 }}
                        >
                          👁 Preview
                        </button>
                      </div>
                    ))}
                  </div>

                  {previewUrl && (
                    <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                      <div className="row" style={{ justifyContent: 'space-between' }}>
                        <strong style={{ wordBreak: 'break-all', fontSize: 13 }}>{previewUrl}</strong>
                        <button className="secondary" onClick={closePreview} style={{ flexShrink: 0 }}>Close</button>
                      </div>
                      {previewing ? (
                        <p className="muted" style={{ marginTop: 8 }}>Loading preview…</p>
                      ) : previewShot ? (
                        <img
                          src={mediaUrl(previewShot.screenshot_url)}
                          alt="page preview"
                          style={{ maxWidth: '100%', border: '1px solid var(--border)', borderRadius: 6, marginTop: 8 }}
                        />
                      ) : (
                        <p className="muted" style={{ marginTop: 8 }}>No preview available.</p>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <p className="muted">No entries found. You can still scrape this page on its own below.</p>
              )}
            </div>

            {/* Step 4 — what to extract + actions */}
            <h1 style={{ marginTop: 28, fontSize: 20 }}>Scrape the selected entries</h1>
            <div className="card">
              <label>Job / recipe name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Latest reports" />

              <label style={{ marginTop: 12 }}>What do you want to extract from each entry?</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Title, publish date, and the summary paragraph."
              />

              <div className="row" style={{ marginTop: 16, gap: 8 }}>
                <button onClick={createScrapeJob} disabled={busy === 'job'}>
                  {busy === 'job' ? 'Creating…' : `Create scrape job (${targetUrls().length} URL${targetUrls().length === 1 ? '' : 's'})`}
                </button>
                <button className="secondary" onClick={saveAsRecipe} disabled={busy === 'recipe'}>
                  {busy === 'recipe' ? 'Saving…' : 'Save as recipe'}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
