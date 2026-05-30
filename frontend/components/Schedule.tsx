'use client';

import { useState } from 'react';
import { updateSchedule, Job, ScheduleConfig, ApiError } from '@/lib/api';

export default function Schedule({ job, onUpdated }: { job: Job; onUpdated: () => void }) {
  const sc = job.schedule_config || {};
  const [enabled, setEnabled] = useState(!!job.is_scheduled);
  const [type, setType] = useState<'interval' | 'cron' | 'once'>(sc.type || 'interval');
  const [intervalValue, setIntervalValue] = useState<number>(sc.interval_value || 1);
  const [intervalUnit, setIntervalUnit] = useState(sc.interval_unit || 'hours');
  const [cron, setCron] = useState(sc.cron_expression || '0 * * * *');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  async function save() {
    setBusy(true);
    setMsg('');
    setError('');
    try {
      let config: ScheduleConfig;
      if (type === 'interval') config = { type, interval_value: Number(intervalValue), interval_unit: intervalUnit as any };
      else if (type === 'cron') config = { type, cron_expression: cron };
      else config = { type: 'once' };
      await updateSchedule(job.id, enabled, enabled ? config : undefined);
      setMsg('Schedule saved.');
      onUpdated();
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>Schedule</h2>
      <label className="row" style={{ width: 'auto' }}>
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} style={{ width: 'auto' }} />
        <span>Run this job automatically</span>
      </label>

      {enabled && (
        <>
          <label>Frequency</label>
          <select value={type} onChange={(e) => setType(e.target.value as any)}>
            <option value="interval">Every…</option>
            <option value="cron">Cron expression</option>
            <option value="once">Once (at next due time)</option>
          </select>

          {type === 'interval' && (
            <div className="row" style={{ marginTop: 8 }}>
              <input
                type="number"
                min={1}
                value={intervalValue}
                onChange={(e) => setIntervalValue(Number(e.target.value))}
                style={{ width: 100 }}
              />
              <select value={intervalUnit} onChange={(e) => setIntervalUnit(e.target.value)} style={{ width: 140 }}>
                <option value="minutes">minutes</option>
                <option value="hours">hours</option>
                <option value="days">days</option>
                <option value="weeks">weeks</option>
              </select>
            </div>
          )}

          {type === 'cron' && (
            <>
              <label>Cron expression</label>
              <input value={cron} onChange={(e) => setCron(e.target.value)} placeholder="0 * * * *" />
            </>
          )}
        </>
      )}

      {job.next_run_at && (
        <p className="muted" style={{ marginTop: 10 }}>
          Next run: {new Date(job.next_run_at).toLocaleString()}
        </p>
      )}
      {error && <div className="error">{error}</div>}
      {msg && <p className="notice" style={{ color: 'var(--green)' }}>{msg}</p>}
      <div style={{ marginTop: 12 }}>
        <button onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save schedule'}</button>
      </div>
    </div>
  );
}
