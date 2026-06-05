'use client';

import { useEffect, useState } from 'react';
import {
  api,
  CareerProfile,
  UserPreferences,
  WatchlistItem,
} from '@/lib/api';

const toList = (s: string) =>
  s.split(',').map(x => x.trim()).filter(Boolean);
const fromList = (a?: string[]) => (a || []).join(', ');

export default function PreferencesPage() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [profile, setProfile] = useState<CareerProfile | null>(null);
  const [noResume, setNoResume] = useState(false);
  const [watch, setWatch] = useState<WatchlistItem[]>([]);
  const [msg, setMsg] = useState('');

  async function loadAll() {
    try { setPrefs(await api.preferences()); } catch {}
    try { setProfile(await api.careerProfile()); } catch { setNoResume(true); }
    try { setWatch(await api.watchlist()); } catch {}
  }
  useEffect(() => { loadAll(); }, []);

  function flash(m: string) {
    setMsg(m);
    setTimeout(() => setMsg(''), 3000);
  }

  if (!prefs) return <p className="text-muted">Loading…</p>;

  return (
    <div className="space-y-6 max-w-3xl">
      <header>
        <h1 className="text-2xl font-bold">Preferences</h1>
        <p className="text-muted text-sm">
          These drive what gets ranked and how. The more accurate, the better your matches.
        </p>
      </header>
      {msg && <div className="pill-good">{msg}</div>}

      <CareerProfileCard profile={profile} noResume={noResume} onSaved={(p) => { setProfile(p); flash('Career profile saved'); }} />

      <PrefsCard prefs={prefs} onSaved={(p) => { setPrefs(p); flash('Preferences saved'); }} />

      <WatchlistCard items={watch} onChange={setWatch} />
    </div>
  );
}

function CareerProfileCard({
  profile, noResume, onSaved,
}: {
  profile: CareerProfile | null;
  noResume: boolean;
  onSaved: (p: CareerProfile) => void;
}) {
  const [p, setP] = useState<CareerProfile | null>(profile);
  useEffect(() => setP(profile), [profile]);
  if (noResume)
    return (
      <div className="card">
        <h2 className="font-semibold">Career profile</h2>
        <p className="text-sm text-muted mt-1">Upload your résumé (Settings) to build your profile.</p>
      </div>
    );
  if (!p) return null;

  async function save() {
    if (!p) return;
    const saved = await api.updateCareerProfile({
      experience_years: Number(p.experience_years) || 0,
      seniority: p.seniority,
      role_direction: p.role_direction,
      current_role: p.current_role,
      current_company: p.current_company,
      target_titles: p.target_titles,
      domains: p.domains,
      primary_skills: p.primary_skills,
    });
    onSaved(saved);
  }

  return (
    <div className="card space-y-3">
      <div>
        <h2 className="font-semibold">Career profile</h2>
        <p className="text-xs text-muted">AI-extracted from your résumé — fix anything that's wrong.</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Experience (years)">
          <input type="number" min={0} className="inp" value={p.experience_years}
            onChange={e => setP({ ...p, experience_years: Number(e.target.value) })} />
        </Field>
        <Field label="Seniority">
          <select className="inp" value={p.seniority} onChange={e => setP({ ...p, seniority: e.target.value })}>
            {['', 'entry', 'mid', 'senior'].map(s => <option key={s} value={s}>{s || '—'}</option>)}
          </select>
        </Field>
        <Field label="Role direction">
          <input className="inp" value={p.role_direction} onChange={e => setP({ ...p, role_direction: e.target.value })} />
        </Field>
        <Field label="Current role">
          <input className="inp" value={p.current_role} onChange={e => setP({ ...p, current_role: e.target.value })} />
        </Field>
        <Field label="Target titles (comma-separated)" wide>
          <input className="inp" value={fromList(p.target_titles)} onChange={e => setP({ ...p, target_titles: toList(e.target.value) })} />
        </Field>
        <Field label="Primary skills (comma-separated)" wide>
          <input className="inp" value={fromList(p.primary_skills)} onChange={e => setP({ ...p, primary_skills: toList(e.target.value) })} />
        </Field>
      </div>
      <button onClick={save} className="btn">Save profile</button>
    </div>
  );
}

function PrefsCard({ prefs, onSaved }: { prefs: UserPreferences; onSaved: (p: UserPreferences) => void }) {
  const [p, setP] = useState(prefs);
  useEffect(() => setP(prefs), [prefs]);

  async function save() {
    onSaved(await api.updatePreferences(p));
  }

  return (
    <div className="card space-y-3">
      <h2 className="font-semibold">Search preferences</h2>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Target roles" wide>
          <input className="inp" value={fromList(p.target_roles)} onChange={e => setP({ ...p, target_roles: toList(e.target.value) })} />
        </Field>
        <Field label="Min salary (LPA)">
          <input type="number" className="inp" value={p.min_salary_lpa ?? ''} onChange={e => setP({ ...p, min_salary_lpa: e.target.value === '' ? null : Number(e.target.value) })} />
        </Field>
        <Field label="Work mode">
          <input className="inp" placeholder="remote, hybrid, onsite" value={fromList(p.work_modes)} onChange={e => setP({ ...p, work_modes: toList(e.target.value) })} />
        </Field>
        <Field label="Preferred cities" wide>
          <input className="inp" value={fromList(p.preferred_cities)} onChange={e => setP({ ...p, preferred_cities: toList(e.target.value) })} />
        </Field>
        <Field label="Job types">
          <input className="inp" placeholder="full-time, internship" value={fromList(p.job_types)} onChange={e => setP({ ...p, job_types: toList(e.target.value) })} />
        </Field>
        <Field label="Must-have skills" wide>
          <input className="inp" value={fromList(p.must_have_skills)} onChange={e => setP({ ...p, must_have_skills: toList(e.target.value) })} />
        </Field>
        <Field label="Nice-to-have skills" wide>
          <input className="inp" value={fromList(p.nice_to_have_skills)} onChange={e => setP({ ...p, nice_to_have_skills: toList(e.target.value) })} />
        </Field>
        <Field label="Blocked industries" wide>
          <input className="inp" value={fromList(p.blocked_industries)} onChange={e => setP({ ...p, blocked_industries: toList(e.target.value) })} />
        </Field>
        <Field label="Excluded keywords" wide>
          <input className="inp" placeholder="e.g. unpaid, commission-only" value={fromList(p.excluded_keywords)} onChange={e => setP({ ...p, excluded_keywords: toList(e.target.value) })} />
        </Field>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={p.needs_sponsorship} onChange={e => setP({ ...p, needs_sponsorship: e.target.checked })} />
        I need visa sponsorship
      </label>

      <div className="border-t border-gray-200 dark:border-gray-700 pt-3">
        <h3 className="font-medium text-sm mb-2">Alerts</h3>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={p.alert_instant} onChange={e => setP({ ...p, alert_instant: e.target.checked })} />
          Email me instantly about <b>excellent</b> matches
        </label>
        <label className="flex items-center gap-2 text-sm mt-1">
          <input type="checkbox" checked={p.alert_daily_digest} onChange={e => setP({ ...p, alert_daily_digest: e.target.checked })} />
          Send me a daily digest
        </label>
        <p className="text-xs text-muted mt-1">Emails only send if the server has an email provider configured.</p>
      </div>

      <button onClick={save} className="btn">Save preferences</button>
    </div>
  );
}

function WatchlistCard({ items, onChange }: { items: WatchlistItem[]; onChange: (i: WatchlistItem[]) => void }) {
  const [company, setCompany] = useState('');

  async function add(priority = 'prioritize') {
    if (!company.trim()) return;
    try {
      await api.addWatchlist(company.trim(), priority);
      onChange(await api.watchlist());
      setCompany('');
    } catch (e: any) { alert(e.message); }
  }
  async function setPriority(id: string, priority: string) {
    await api.patchWatchlist(id, priority);
    onChange(await api.watchlist());
  }
  async function remove(id: string) {
    await api.removeWatchlist(id);
    onChange(await api.watchlist());
  }

  const prioritized = items.filter(i => i.priority === 'prioritize');
  const blocked = items.filter(i => i.priority === 'block');

  return (
    <div className="card space-y-3">
      <div>
        <h2 className="font-semibold">Company watchlist</h2>
        <p className="text-xs text-muted">
          Prioritised companies are checked more often and boosted (only when role fit is good). Blocked companies are never shown.
        </p>
      </div>
      <div className="flex gap-2">
        <input className="inp flex-1" placeholder="Add a company (e.g. Stripe)" value={company}
          onChange={e => setCompany(e.target.value)} onKeyDown={e => e.key === 'Enter' && add('prioritize')} />
        <button onClick={() => add('prioritize')} className="btn-ghost">Prioritize</button>
        <button onClick={() => add('block')} className="btn-ghost">Block</button>
      </div>

      {prioritized.length > 0 && (
        <div>
          <div className="kv mb-1">⭐ Prioritized</div>
          <div className="flex flex-wrap gap-2">
            {prioritized.map(i => (
              <span key={i.id} className="pill-good flex items-center gap-1">
                {i.company}
                <button title="Block instead" onClick={() => setPriority(i.id, 'block')} className="ml-1 opacity-70 hover:opacity-100">🚫</button>
                <button title="Remove" onClick={() => remove(i.id)} className="opacity-70 hover:opacity-100">✕</button>
              </span>
            ))}
          </div>
        </div>
      )}
      {blocked.length > 0 && (
        <div>
          <div className="kv mb-1">🚫 Blocked</div>
          <div className="flex flex-wrap gap-2">
            {blocked.map(i => (
              <span key={i.id} className="pill-bad flex items-center gap-1">
                {i.company}
                <button title="Remove" onClick={() => remove(i.id)} className="ml-1 opacity-70 hover:opacity-100">✕</button>
              </span>
            ))}
          </div>
        </div>
      )}
      {items.length === 0 && <p className="text-sm text-muted">No companies yet. Add the ones you'd love to work at.</p>}
    </div>
  );
}

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-2' : ''}>
      <label className="kv block mb-1">{label}</label>
      {children}
    </div>
  );
}
