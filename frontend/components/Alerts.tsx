'use client';

import { useState } from 'react';
import { updateJob, testAlert, Job, NotifyChannel, ApiError } from '@/lib/api';

type ChannelType = NotifyChannel['type'];

export default function Alerts({ job, onUpdated }: { job: Job; onUpdated: () => void }) {
  const [enabled, setEnabled] = useState(!!job.notify_on_change);
  const [channels, setChannels] = useState<NotifyChannel[]>(job.notify_config?.channels || []);
  const [type, setType] = useState<ChannelType>('slack');
  const [target, setTarget] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [testMsg, setTestMsg] = useState('');

  function addChannel() {
    if (!target.trim()) return;
    setChannels([...channels, { type, target: target.trim() }]);
    setTarget('');
  }
  function removeChannel(i: number) {
    setChannels(channels.filter((_, idx) => idx !== i));
  }

  async function save() {
    setSaving(true);
    setError('');
    setTestMsg('');
    try {
      await updateJob(job.id, { notify_on_change: enabled, notify_config: { channels } });
      onUpdated();
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    setTestMsg('testing…');
    try {
      const r = await testAlert(job.id);
      setTestMsg(
        r.success
          ? 'Sent to all channels ✓'
          : 'Some channels failed: ' + r.results.filter((x) => !x.success).map((x) => `${x.label}: ${x.error}`).join('; ')
      );
    } catch (err) {
      setTestMsg('Failed: ' + (err as ApiError).message);
    }
  }

  const targetPlaceholder =
    type === 'email' ? 'alerts@example.com' : 'https://hooks.slack.com/services/…';

  return (
    <div className="card">
      <h2 style={{ margin: 0 }}>Change alerts</h2>
      <p className="notice">
        Get notified when a run&apos;s scraped data differs from the previous run.
      </p>

      <label className="row" style={{ width: 'auto' }}>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          style={{ width: 'auto' }}
        />
        <span>Notify me when this job&apos;s data changes</span>
      </label>

      {channels.length > 0 ? (
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>Channel</th><th>Target</th><th></th></tr></thead>
          <tbody>
            {channels.map((c, i) => (
              <tr key={i}>
                <td>{c.type}</td>
                <td className="muted" style={{ wordBreak: 'break-all' }}>{c.target}</td>
                <td><button className="secondary" onClick={() => removeChannel(i)}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted" style={{ marginTop: 12 }}>No channels yet.</p>
      )}

      <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
        <label>Add a channel</label>
        <div className="row" style={{ gap: 8 }}>
          <select value={type} onChange={(e) => setType(e.target.value as ChannelType)} style={{ maxWidth: 130 }}>
            <option value="slack">Slack</option>
            <option value="discord">Discord</option>
            <option value="webhook">Webhook</option>
            <option value="email">Email</option>
          </select>
          <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={targetPlaceholder} />
          <button className="secondary" onClick={addChannel}>Add</button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      <div className="row" style={{ marginTop: 12, gap: 8 }}>
        <button onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save alerts'}</button>
        <button className="secondary" onClick={runTest} disabled={channels.length === 0}>Send test</button>
        {testMsg && <span className="muted" style={{ fontSize: 12 }}>{testMsg}</span>}
      </div>
    </div>
  );
}
