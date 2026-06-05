'use client';

import { useEffect, useState } from 'react';
import { api, AdminStats, AdminUser, Run, SourceHealth } from '@/lib/api';
import { useAuth } from '../AuthProvider';

export default function AdminPage() {
  const { user } = useAuth();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [health, setHealth] = useState<SourceHealth[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    if (user && !user.is_admin) return;
    (async () => {
      try {
        const [s, u, r, h] = await Promise.all([
          api.adminStats(), api.adminUsers(), api.adminRuns(), api.adminSourceHealth(),
        ]);
        setStats(s);
        setUsers(u);
        setRuns(r);
        setHealth(h);
      } catch (e: any) {
        setErr(e.message);
      }
    })();
  }, [user]);

  if (user && !user.is_admin) {
    return (
      <div className="card">
        <h1 className="text-xl font-bold">Admin</h1>
        <p className="text-muted text-sm mt-1">
          You don't have admin access. Ask an operator to add your email to{' '}
          <code>ADMIN_EMAILS</code> on the backend.
        </p>
      </div>
    );
  }

  if (err) return <p className="text-bad">Error: {err}</p>;
  if (!stats) return <p className="text-muted">Loading…</p>;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold">Admin</h1>
        <p className="text-muted text-sm">Read-only platform overview. No data is modified here.</p>
      </header>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Metric label="Users" value={stats.total_users} />
        <Metric label="Active" value={stats.active_users} />
        <Metric label="With résumé" value={stats.users_with_resume} />
        <Metric label="Jobs in pool" value={stats.total_jobs} />
        <Metric label="Rankings" value={stats.total_rankings} />
        <Metric label="Applications" value={stats.total_applications} />
        <Metric
          label="Last run"
          value={stats.last_run ? new Date(stats.last_run.started_at).toLocaleString() : '—'}
        />
      </section>

      <section>
        <h2 className="font-semibold mb-3">Users ({users.length})</h2>
        <div className="space-y-2">
          {users.map(u => (
            <div key={u.id} className="card">
              <button
                className="w-full text-left flex items-center justify-between gap-4"
                onClick={() => setOpen(open === u.id ? null : u.id)}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium truncate">{u.name || u.email}</span>
                    {u.is_admin && <span className="pill-warn">admin</span>}
                    {!u.is_active && <span className="pill-bad">disabled</span>}
                    <span className={u.experience_pref === 'fresher' ? 'pill-good' : 'pill-mute'}>
                      {u.experience_pref}
                    </span>
                    <span className="pill-mute">{u.login_method}</span>
                  </div>
                  <div className="kv truncate">{u.email}</div>
                </div>
                <div className="text-right text-sm shrink-0">
                  <div className="kv">
                    {u.n_ranked} ranked · {u.n_shortlisted} shortlisted · {u.n_applied} applied
                  </div>
                  <div className="kv">{u.n_resumes} résumé(s)</div>
                </div>
              </button>

              {open === u.id && (
                <div className="mt-3 border-t border-gray-200 dark:border-gray-700 pt-3 space-y-2">
                  {u.resumes.length === 0 && <p className="text-muted text-sm">No résumés uploaded.</p>}
                  {u.resumes.map(r => (
                    <div key={r.id} className="text-sm bg-gray-50 dark:bg-gray-800 rounded-md p-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium">{r.filename || '(unnamed)'}</span>
                        {r.is_active && <span className="pill-good">active</span>}
                        {r.role_direction && <span className="pill-info">{r.role_direction}</span>}
                        {r.seniority && <span className="pill-mute">{r.seniority}</span>}
                      </div>
                      <div className="kv mt-1">
                        exp: {r.experience_years ?? '—'} yrs · skills: {r.n_skills} · text:{' '}
                        {r.text_chars} chars ·{' '}
                        {r.on_disk ? 'file on disk' : 'file not on disk (ephemeral)'} · uploaded{' '}
                        {new Date(r.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="font-semibold mb-3">Source health</h2>
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="py-1 pr-4">Source</th>
                <th className="py-1 pr-4">Last run</th>
                <th className="py-1 pr-4">Found</th>
                <th className="py-1 pr-4">Added</th>
                <th className="py-1 pr-4">Failures</th>
                <th className="py-1">Last error</th>
              </tr>
            </thead>
            <tbody>
              {health.map(h => (
                <tr key={h.source} className="border-t border-gray-100 dark:border-gray-700">
                  <td className="py-1 pr-4 font-medium">{h.source}</td>
                  <td className="py-1 pr-4 text-muted">
                    {h.last_run_at ? new Date(h.last_run_at).toLocaleString() : '—'}
                  </td>
                  <td className="py-1 pr-4">{h.jobs_found}</td>
                  <td className="py-1 pr-4">{h.jobs_added}</td>
                  <td className={`py-1 pr-4 ${h.failures ? 'text-bad' : ''}`}>{h.failures}</td>
                  <td className="py-1 text-bad truncate max-w-xs" title={h.last_error || ''}>
                    {h.last_error || ''}
                  </td>
                </tr>
              ))}
              {health.length === 0 && (
                <tr><td colSpan={6} className="py-2 text-muted">No source runs recorded yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="font-semibold mb-3">Recent runs</h2>
        <div className="space-y-2">
          {runs.map(r => (
            <div key={r.id} className="card text-sm">
              <div className="flex items-center justify-between gap-4">
                <span className="font-mono text-xs text-muted">{r.id.slice(0, 8)}</span>
                <span className={r.status === 'success' ? 'pill-good' : r.status === 'running' ? 'pill-info' : 'pill-bad'}>
                  {r.status}
                </span>
                <span className="kv">{new Date(r.started_at).toLocaleString()}</span>
                <span className="kv">
                  found {r.jobs_found} · new {r.jobs_new} · ranked {r.ranked}
                </span>
              </div>
            </div>
          ))}
          {runs.length === 0 && <p className="text-muted text-sm">No runs yet.</p>}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card">
      <div className="kv">{label}</div>
      <div className="text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}
