'use client';

import { useEffect, useState } from 'react';
import {
  listDestinations, createDestination, deleteDestination, testDestination,
  Destination, ApiError,
} from '@/lib/api';

type DestType = Destination['dest_type'];

export default function Destinations({ jobId }: { jobId: number }) {
  const [dests, setDests] = useState<Destination[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');
  const [testMsg, setTestMsg] = useState<Record<number, string>>({});

  // add form
  const [name, setName] = useState('');
  const [type, setType] = useState<DestType>('webhook');
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => { load(); }, [jobId]);

  async function load() {
    try {
      setDests(await listDestinations(jobId));
    } catch (err) {
      setError((err as ApiError).message);
    }
  }

  function field(key: string) {
    return cfg[key] || '';
  }
  function setField(key: string, val: string) {
    setCfg({ ...cfg, [key]: val });
  }

  function buildConfig(): Record<string, any> {
    if (type === 'postgres') return { dsn: field('dsn'), table: field('table'), schema: field('schema') || 'public' };
    if (type === 'webhook') return { url: field('url'), secret: field('secret') || undefined };
    // google_sheets
    let creds: any = undefined;
    try { creds = field('credentials_json') ? JSON.parse(field('credentials_json')) : undefined; } catch { /* leave undefined */ }
    return { spreadsheet_id: field('spreadsheet_id'), worksheet: field('worksheet') || 'Sheet1', credentials: creds };
  }

  async function add() {
    setSaving(true);
    setError('');
    try {
      await createDestination({ job: jobId, name, dest_type: type, config: buildConfig() });
      setName(''); setCfg({}); setAdding(false);
      await load();
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
    } finally {
      setSaving(false);
    }
  }

  async function runTest(id: number) {
    setTestMsg({ ...testMsg, [id]: 'testing…' });
    try {
      const r = await testDestination(id);
      setTestMsg({ ...testMsg, [id]: r.success ? `OK (${r.rows_delivered} row)` : `Failed: ${r.error}` });
    } catch (err) {
      setTestMsg({ ...testMsg, [id]: `Failed: ${(err as ApiError).message}` });
    }
  }

  async function remove(id: number) {
    await deleteDestination(id);
    await load();
  }

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>Destinations</h2>
        <button className="secondary" onClick={() => setAdding(!adding)}>{adding ? 'Cancel' : '+ Add'}</button>
      </div>
      <p className="notice">Push each run's rows to an external Postgres table, a Google Sheet, or a webhook.</p>

      {dests.length === 0 ? (
        <p className="muted">No destinations yet.</p>
      ) : (
        <table>
          <thead><tr><th>Name</th><th>Type</th><th>Last</th><th>Rows</th><th></th></tr></thead>
          <tbody>
            {dests.map((d) => (
              <tr key={d.id}>
                <td>{d.name}</td>
                <td>{d.dest_type}</td>
                <td>
                  <span className={`badge ${d.last_status === 'success' ? 'success' : d.last_status === 'failed' ? 'failed' : ''}`}>
                    {d.last_status || 'never'}
                  </span>
                  {testMsg[d.id] && <div className="muted" style={{ fontSize: 11 }}>{testMsg[d.id]}</div>}
                </td>
                <td>{d.total_rows_delivered ?? 0}</td>
                <td className="row">
                  <button className="secondary" onClick={() => runTest(d.id)}>Test</button>
                  <button className="secondary" onClick={() => remove(d.id)}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {adding && (
        <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My warehouse" />
          <label>Type</label>
          <select value={type} onChange={(e) => { setType(e.target.value as DestType); setCfg({}); }}>
            <option value="webhook">Webhook</option>
            <option value="postgres">External Postgres</option>
            <option value="google_sheets">Google Sheets</option>
          </select>

          {type === 'postgres' && (
            <>
              <label>Connection string (DSN)</label>
              <input value={field('dsn')} onChange={(e) => setField('dsn', e.target.value)} placeholder="postgresql://user:pass@host:5432/db" />
              <label>Table</label>
              <input value={field('table')} onChange={(e) => setField('table', e.target.value)} placeholder="scraped_rows" />
              <label>Schema (optional)</label>
              <input value={field('schema')} onChange={(e) => setField('schema', e.target.value)} placeholder="public" />
            </>
          )}
          {type === 'webhook' && (
            <>
              <label>URL</label>
              <input value={field('url')} onChange={(e) => setField('url', e.target.value)} placeholder="https://example.com/hook" />
              <label>HMAC secret (optional)</label>
              <input value={field('secret')} onChange={(e) => setField('secret', e.target.value)} />
            </>
          )}
          {type === 'google_sheets' && (
            <>
              <label>Spreadsheet ID</label>
              <input value={field('spreadsheet_id')} onChange={(e) => setField('spreadsheet_id', e.target.value)} />
              <label>Worksheet (optional)</label>
              <input value={field('worksheet')} onChange={(e) => setField('worksheet', e.target.value)} placeholder="Sheet1" />
              <label>Service-account credentials (JSON)</label>
              <textarea value={field('credentials_json')} onChange={(e) => setField('credentials_json', e.target.value)} placeholder='{ "type": "service_account", ... }' />
            </>
          )}

          {error && <div className="error">{error}</div>}
          <div style={{ marginTop: 12 }}>
            <button onClick={add} disabled={saving || !name}>{saving ? 'Saving…' : 'Add destination'}</button>
          </div>
        </div>
      )}
    </div>
  );
}
