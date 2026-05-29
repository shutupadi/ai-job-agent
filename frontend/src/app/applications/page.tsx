'use client';

import { useEffect, useState } from 'react';
import { api, Application } from '@/lib/api';

const STATUSES = [
  'all',
  'queued',
  'awaiting_approval',
  'manual_pending',
  'submitted',
  'failed',
  'interview',
  'rejected',
  'offer',
];

export default function ApplicationsPage() {
  const [items, setItems] = useState<Application[]>([]);
  const [status, setStatus] = useState('all');
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    const params: Record<string, any> = { limit: 100 };
    if (status !== 'all') params.status = status;
    const r = await api.applications(params);
    setItems(r.items);
  }
  useEffect(() => {
    load();
  }, [status]); // eslint-disable-line

  async function approve(id: string) {
    setBusy(id);
    try {
      await api.approveApplication(id);
      await load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function setRowStatus(id: string, newStatus: string) {
    setBusy(id);
    try {
      await api.patchApplicationStatus(id, newStatus);
      await load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Applications</h1>
        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="border rounded-md px-3 py-2 text-sm"
        >
          {STATUSES.map(s => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </header>

      <div className="space-y-3">
        {items.map(a => (
          <div key={a.id} className="card">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="text-xs text-muted">Application {a.id.slice(0, 8)}</div>
                <div className="text-sm">
                  Job: <a className="underline" href={`/jobs?focus=${a.job_id}`}>{a.job_id.slice(0, 8)}</a>
                </div>
                <div className="kv">
                  Attempts: {a.attempts} • Created {new Date(a.created_at).toLocaleString()}
                </div>
                {a.error && <p className="text-bad text-sm mt-1">{a.error}</p>}
                {a.screenshot_path && (
                  <a
                    target="_blank"
                    rel="noreferrer"
                    className="text-sm underline text-accent"
                    href={`${api.base}/files/${a.screenshot_path.split('/storage/')[1] ?? ''}`}
                  >
                    screenshot
                  </a>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className={pillFor(a.status)}>{a.status}</span>
                {a.status === 'awaiting_approval' && (
                  <button
                    className="btn"
                    onClick={() => approve(a.id)}
                    disabled={busy === a.id}
                  >
                    {busy === a.id ? '…' : 'Approve'}
                  </button>
                )}
                {(a.status === 'submitted' || a.status === 'interview') && (
                  <button
                    className="btn-ghost"
                    onClick={() =>
                      setRowStatus(a.id, a.status === 'submitted' ? 'interview' : 'offer')
                    }
                    disabled={busy === a.id}
                  >
                    {a.status === 'submitted' ? 'Mark interview' : 'Mark offer'}
                  </button>
                )}
                {a.status !== 'rejected' && (
                  <button
                    className="btn-ghost"
                    onClick={() => setRowStatus(a.id, 'rejected')}
                    disabled={busy === a.id}
                  >
                    Reject
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
        {items.length === 0 && <p className="text-muted">No applications yet.</p>}
      </div>
    </div>
  );
}

function pillFor(status: string) {
  switch (status) {
    case 'submitted':
      return 'pill-info';
    case 'interview':
      return 'pill-good';
    case 'offer':
      return 'pill-good';
    case 'awaiting_approval':
      return 'pill-warn';
    case 'failed':
    case 'rejected':
      return 'pill-bad';
    default:
      return 'pill-mute';
  }
}
