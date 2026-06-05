'use client';

import { useEffect, useState } from 'react';
import { api, AdminSource, AdminStats, AdminUser, Run, SystemHealth } from '@/lib/api';
import { useAuth } from '../AuthProvider';

export default function AdminPage() {
  const { user } = useAuth();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [sources, setSources] = useState<AdminSource[]>([]);
  const [sys, setSys] = useState<SystemHealth | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    if (user && !user.is_admin) return;
    (async () => {
      try {
        const [s, u, r, src, sh] = await Promise.all([
          api.adminStats(), api.adminUsers(), api.adminRuns(),
          api.adminSources(), api.adminSystemHealth(),
        ]);
        setStats(s);
        setUsers(u);
        setRuns(r);
        setSources(src);
        setSys(sh);
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

      <EmailDiagnostics />


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

      {sys && (
        <section className="card space-y-2">
          <h2 className="font-semibold">System health</h2>
          <div className="flex flex-wrap gap-2 text-sm">
            <span className="pill-mute">env: {sys.app_env}</span>
            <span className="pill-mute">email: {sys.email_provider || 'none'}</span>
            <span className={sys.email_enabled ? 'pill-good' : 'pill-warn'}>
              email {sys.email_enabled ? 'configured' : 'not configured'}
            </span>
            <span className={sys.verification_active ? 'pill-good' : 'pill-warn'}>
              OTP {sys.verification_active ? 'enforced' : 'off'}
            </span>
          </div>
          {sys.email_misconfigured && (
            <p className="text-bad text-sm">
              ⚠ Verification is required in production but no email provider is configured —
              new signups can't verify. Set EMAIL_PROVIDER + key + EMAIL_FROM (or disable
              REQUIRE_EMAIL_VERIFICATION).
            </p>
          )}
          {sys.sender_freemail && (
            <p className="text-warn text-sm">
              ⚠ EMAIL_FROM ({sys.email_from}) uses a freemail domain. Gmail/Outlook often
              drop or spam-folder mail "from" gmail/yahoo/outlook even when the API says
              "sent" (DMARC). Verify your own domain in {sys.email_provider || 'your provider'}{' '}
              and send from e.g. noreply@yourdomain — otherwise OTP/reset codes may not arrive.
            </p>
          )}
        </section>
      )}

      <section>
        <h2 className="font-semibold mb-3">Sources</h2>
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="py-1 pr-4">Source</th>
                <th className="py-1 pr-4">Status</th>
                <th className="py-1 pr-4">Confidence</th>
                <th className="py-1 pr-4">Last run</th>
                <th className="py-1 pr-4">Found</th>
                <th className="py-1 pr-4">Added</th>
                <th className="py-1 pr-4">Fails</th>
                <th className="py-1">Notes</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(s => (
                <tr key={s.name} className="border-t border-gray-100 dark:border-gray-700">
                  <td className="py-1 pr-4 font-medium">{s.name}</td>
                  <td className="py-1 pr-4">
                    <span className={s.enabled ? 'pill-good' : 'pill-mute'}>
                      {s.enabled ? 'on' : 'off'}
                    </span>
                    {s.stub && <span className="pill-warn ml-1">stub</span>}
                  </td>
                  <td className="py-1 pr-4">
                    <span className={
                      s.confidence === 'high' ? 'pill-good'
                      : s.confidence === 'medium' ? 'pill-info' : 'pill-warn'
                    }>{s.confidence}</span>
                  </td>
                  <td className="py-1 pr-4 text-muted">
                    {s.last_run_at ? new Date(s.last_run_at).toLocaleString() : '—'}
                  </td>
                  <td className="py-1 pr-4">{s.jobs_found}</td>
                  <td className="py-1 pr-4">{s.jobs_added}</td>
                  <td className={`py-1 pr-4 ${s.failures ? 'text-bad' : ''}`}>{s.failures}</td>
                  <td className="py-1 max-w-xs">
                    {s.enabled && !s.configured && (
                      <span className="text-warn" title="Missing credentials">
                        missing: {s.missing_credentials.join(', ')}
                      </span>
                    )}
                    {s.last_error && (
                      <span className="text-bad truncate block" title={s.last_error}>
                        {s.last_error}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
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

function EmailDiagnostics() {
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.adminEmailTest>> | null>(null);

  async function run() {
    setBusy(true);
    setRes(null);
    try {
      setRes(await api.adminEmailTest(to.trim() || undefined));
    } catch (e: any) {
      setRes({ provider: '', enabled: false, from: '', to, ok: false, error: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-3">
      <h2 className="font-semibold">Email / OTP diagnostics</h2>
      <p className="kv">
        Sends a real test email and shows exactly what the provider returned —
        use this to debug OTP delivery.
      </p>
      <div className="flex flex-wrap gap-2 items-center">
        <input
          className="inp max-w-xs"
          placeholder="send to (defaults to your email)"
          value={to}
          onChange={e => setTo(e.target.value)}
        />
        <button className="btn" onClick={run} disabled={busy}>
          {busy ? 'Sending…' : 'Send test email'}
        </button>
      </div>
      {res && (
        <div className="text-sm space-y-1">
          <div className="flex flex-wrap gap-2">
            <span className="pill-mute">provider: {res.provider || '—'}</span>
            <span className={res.enabled ? 'pill-good' : 'pill-bad'}>
              {res.enabled ? 'configured' : 'not configured'}
            </span>
            <span className={res.verification_active ? 'pill-good' : 'pill-warn'}>
              OTP {res.verification_active ? 'enforced' : 'auto-verify (off)'}
            </span>
            <span className={res.ok ? 'pill-good' : 'pill-bad'}>
              {res.ok ? 'sent ✓' : 'send failed'}
            </span>
          </div>
          <div className="kv">from: {res.from || '—'} → to: {res.to}</div>
          {res.error && (
            <pre className="text-xs text-bad whitespace-pre-wrap bg-rose-50 dark:bg-rose-900/20 rounded p-2">
              {res.error}
            </pre>
          )}
          {res.ok && <p className="text-good">Check that inbox (and spam).</p>}
        </div>
      )}
    </section>
  );
}
