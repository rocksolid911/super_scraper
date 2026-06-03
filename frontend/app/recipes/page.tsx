'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import { listRecipes, createJobFromRecipe, deleteRecipe, getToken, Recipe, ApiError } from '@/lib/api';

export default function Recipes() {
  const router = useRouter();
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push('/login');
      return;
    }
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      setRecipes(await listRecipes());
    } catch (err) {
      const e = err as ApiError;
      if (e.status === 401) router.push('/login');
      else setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function runRecipe(id: number) {
    setError('');
    setBusy(id);
    try {
      const job = await createJobFromRecipe(id);
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(null);
    }
  }

  async function remove(id: number) {
    setError('');
    try {
      await deleteRecipe(id);
      await refresh();
    } catch (err) {
      setError((err as ApiError).message);
    }
  }

  return (
    <>
      <TopBar />
      <div className="container">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h1 style={{ margin: 0 }}>Saved recipes</h1>
          <div className="row" style={{ gap: 8 }}>
            <button className="secondary" onClick={() => router.push('/discover')}>🧭 Discover</button>
            <button className="secondary" onClick={() => router.push('/')}>← Dashboard</button>
          </div>
        </div>
        <p className="notice" style={{ margin: '6px 0 16px' }}>
          Recipes are saved selections from Discover. Run one to spin up a fresh job with its URLs
          and prompt already filled in.
        </p>

        {error && <div className="error">{error}</div>}

        {loading ? (
          <p className="muted">Loading…</p>
        ) : recipes.length === 0 ? (
          <p className="muted">
            No recipes yet. Open <a href="#" onClick={(e) => { e.preventDefault(); router.push('/discover'); }}>Discover</a>,
            pick some entries, and choose “Save as recipe”.
          </p>
        ) : (
          <div className="grid">
            {recipes.map((r) => (
              <div className="card" key={r.id}>
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <strong>{r.name}</strong>
                  <span className="badge">{r.item_urls?.length ?? 0} URL{(r.item_urls?.length ?? 0) === 1 ? '' : 's'}</span>
                </div>
                {r.section_label && <p className="muted" style={{ margin: '6px 0 0' }}>Section: {r.section_label}</p>}
                {r.prompt && (
                  <p className="muted" style={{ margin: '6px 0 0', fontSize: 13 }}>
                    “{r.prompt.length > 120 ? r.prompt.slice(0, 120) + '…' : r.prompt}”
                  </p>
                )}
                <p className="muted" style={{ margin: '6px 0 0', fontSize: 12, wordBreak: 'break-all' }}>
                  {r.source_url}
                </p>
                <div className="row" style={{ marginTop: 12, gap: 8 }}>
                  <button onClick={() => runRecipe(r.id)} disabled={busy === r.id}>
                    {busy === r.id ? 'Creating…' : 'Run as job'}
                  </button>
                  <button className="secondary" onClick={() => remove(r.id)}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
