'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import TopBar from '@/components/TopBar';
import PreviewOutput from '@/components/PreviewOutput';
import {
  createJob, updateSchedule, updateJob, getToken,
  NotifyChannel, ApiError,
} from '@/lib/api';

type Unit = 'minutes' | 'hours' | 'days' | 'weeks';
type ChannelType = NotifyChannel['type'];

/**
 * "Monitor a page" — one flow that creates a job, puts it on a schedule, and turns on
 * change alerts. Combines what would otherwise be three separate steps (create →
 * schedule → alerts) into the retention-focused "watch this for me" use case.
 */
export default function Monitor() {
  const router = useRouter();

  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [prompt, setPrompt] = useState('');
  const [js, setJs] = useState(false);
  const [respectRobots, setRespectRobots] = useState(true);

  const [intervalValue, setIntervalValue] = useState('6');
  const [intervalUnit, setIntervalUnit] = useState<Unit>('hours');

  const [channelType, setChannelType] = useState<ChannelType>('slack');
  const [channelTarget, setChannelTarget] = useState('');

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (typeof window !== 'undefined' && !getToken()) {
    router.push('/login');
  }

  const urls = url.split(/[\n,]+/).map((u) => u.trim()).filter(Boolean);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (!name.trim() || urls.length === 0 || !prompt.trim()) {
      setError('Name, at least one URL, and a prompt are required.');
      return;
    }
    setBusy(true);
    try {
      // 1) create the job
      const job = await createJob({
        name,
        mode: 'prompt',
        configuration: { urls, prompt },
        use_js_rendering: js,
        respect_robots_txt: respectRobots,
      });

      // 2) put it on a schedule
      const value = Math.max(1, parseInt(intervalValue, 10) || 1);
      await updateSchedule(job.id, true, { type: 'interval', interval_value: value, interval_unit: intervalUnit });

      // 3) turn on change alerts (with a channel if one was given)
      const channels: NotifyChannel[] = channelTarget.trim()
        ? [{ type: channelType, target: channelTarget.trim() }]
        : [];
      await updateJob(job.id, { notify_on_change: true, notify_config: { channels } });

      router.push(`/jobs/${job.id}`);
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
      setBusy(false);
    }
  }

  return (
    <>
      <TopBar />
      <div className="container">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h1 style={{ margin: 0 }}>Monitor a page</h1>
          <button className="secondary" onClick={() => router.push('/')}>← Dashboard</button>
        </div>
        <p className="notice" style={{ margin: '6px 0 16px' }}>
          Set up a page to watch: it scrapes on a schedule and alerts you when the data changes.
          One step — create, schedule, and alerts together.
        </p>

        <div className="card">
          <form onSubmit={submit}>
            <label>Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="WB 2026 winners watch" />

            <label>URL(s) — one per line</label>
            <textarea value={url} onChange={(e) => setUrl(e.target.value)} required placeholder="https://example.com/listing" />

            <label>What to extract</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              required
              placeholder="Each row with its title, status, and link."
            />

            <label className="row" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={js} onChange={(e) => setJs(e.target.checked)} style={{ width: 'auto' }} />
              <span>Render JavaScript (slower, needed for SPA sites)</span>
            </label>
            <label className="row" style={{ marginTop: 8 }}>
              <input type="checkbox" checked={respectRobots} onChange={(e) => setRespectRobots(e.target.checked)} style={{ width: 'auto' }} />
              <span>Respect robots.txt</span>
            </label>

            <label style={{ marginTop: 14 }}>Check every</label>
            <div className="row" style={{ gap: 8 }}>
              <input
                type="number"
                min={1}
                value={intervalValue}
                onChange={(e) => setIntervalValue(e.target.value)}
                style={{ maxWidth: 100 }}
              />
              <select value={intervalUnit} onChange={(e) => setIntervalUnit(e.target.value as Unit)} style={{ maxWidth: 140 }}>
                <option value="minutes">minutes</option>
                <option value="hours">hours</option>
                <option value="days">days</option>
                <option value="weeks">weeks</option>
              </select>
            </div>

            <label style={{ marginTop: 14 }}>Alert me on change (optional)</label>
            <div className="row" style={{ gap: 8 }}>
              <select value={channelType} onChange={(e) => setChannelType(e.target.value as ChannelType)} style={{ maxWidth: 130 }}>
                <option value="slack">Slack</option>
                <option value="discord">Discord</option>
                <option value="webhook">Webhook</option>
                <option value="email">Email</option>
              </select>
              <input
                value={channelTarget}
                onChange={(e) => setChannelTarget(e.target.value)}
                placeholder={channelType === 'email' ? 'alerts@example.com' : 'https://hooks.slack.com/…'}
              />
            </div>
            <span className="muted" style={{ fontSize: 12 }}>
              Leave blank to track changes in-app only (you can add channels later on the job page).
            </span>

            <PreviewOutput storageKey="monitor" urls={urls} prompt={prompt} useJs={js} />

            {error && <div className="error">{error}</div>}
            <div style={{ marginTop: 16 }}>
              <button type="submit" disabled={busy}>{busy ? 'Setting up…' : 'Start monitoring'}</button>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
