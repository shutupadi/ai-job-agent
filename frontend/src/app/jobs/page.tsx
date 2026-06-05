'use client';

import { useEffect, useState } from 'react';
import { api, Job, TailorResponse } from '@/lib/api';
import { useAuth } from '../AuthProvider';

type Filters = {
  q: string;
  minRank: number | '';
  source: string;
  status: string;
  matchLevel: string;
  remoteOnly: boolean;
  topOnly: boolean;
  watchlistOnly: boolean;
  savedOnly: boolean;
  postedWithin: number | '';
  sort: 'rank' | 'recent';
};

const EMPTY: Filters = {
  q: '',
  minRank: '',
  source: '',
  status: '',
  matchLevel: '',
  remoteOnly: false,
  topOnly: false,
  watchlistOnly: false,
  savedOnly: false,
  postedWithin: '',
  sort: 'rank',
};

export default function JobsPage() {
  const { user, refresh } = useAuth();
  const [items, setItems] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [f, setF] = useState<Filters>(EMPTY);
  const [busy, setBusy] = useState<string | null>(null);
  const [reranking, setReranking] = useState(false);
  const [docs, setDocs] = useState<Record<string, TailorResponse>>({});
  const [cfg, setCfg] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);

  async function load(override?: Partial<Filters>) {
    const cur = { ...f, ...(override || {}) };
    const params: Record<string, any> = { limit: 100, sort: cur.sort };
    if (cur.q) params.q = cur.q;
    if (cur.minRank !== '' && cur.minRank != null) params.min_rank = Number(cur.minRank);
    if (cur.source) params.source = cur.source;
    if (cur.status) params.status = cur.status;
    if (cur.matchLevel) params.match_level = cur.matchLevel;
    if (cur.remoteOnly) params.remote_only = true;
    if (cur.topOnly) params.top_only = true;
    if (cur.watchlistOnly) params.watchlist_only = true;
    if (cur.savedOnly) params.saved_only = true;
    if (cur.postedWithin !== '' && cur.postedWithin != null)
      params.posted_within_days = Number(cur.postedWithin);
    const res = await api.jobs(params);
    setItems(res.items);
    setTotal(res.total);
  }

  // On mount: seed min rank from the shortlist threshold, then load.
  useEffect(() => {
    (async () => {
      let thr = 70;
      try {
        const s = await api.settings();
        setCfg(s);
        if (typeof s.min_rank_to_apply === 'number') thr = s.min_rank_to_apply;
      } catch {}
      setF(prev => ({ ...prev, minRank: thr }));
      await load({ minRank: thr });
      setLoading(false);
    })();
  }, []); // eslint-disable-line

  const fresher = (user?.experience_pref ?? 'fresher') === 'fresher';

  async function toggleFresher() {
    try {
      await api.setExperiencePref(fresher ? 'all' : 'fresher');
      await refresh();
      await load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function rerank() {
    if (
      !confirm(
        'Re-score your job matches against your current résumé and mode? ' +
          'Your tailored/applied jobs are kept. This runs in the background (~1 min).',
      )
    )
      return;
    setReranking(true);
    try {
      await api.rerank('ranked');
      // Give the background run a head start, then poll a couple of times.
      setTimeout(() => load(), 4000);
      setTimeout(() => load(), 12000);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setTimeout(() => setReranking(false), 12000);
    }
  }

  async function tailor(id: string) {
    setBusy(id);
    try {
      const resp = await api.tailor(id);
      setDocs(d => ({ ...d, [id]: resp }));
      await load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function showFiles(id: string) {
    setBusy(id);
    try {
      const resp = await api.forJobDocs(id);
      setDocs(d => ({ ...d, [id]: resp }));
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function markApplied(id: string) {
    setBusy(id);
    try {
      await api.markApplied(id);
      await load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function sendFeedback(
    id: string,
    action: 'save' | 'unsave' | 'not_relevant' | 'more_like_this' | 'hide_company',
    company?: string,
  ) {
    if (action === 'hide_company' && !confirm(`Hide all jobs from ${company}?`)) return;
    setBusy(id);
    try {
      await api.jobFeedback(id, action);
      // not_relevant / hide_company remove cards; save flips locally.
      if (action === 'not_relevant' || action === 'hide_company') {
        await load();
      } else {
        setItems(items => items.map(j => (j.id === id ? { ...j, saved: action === 'save' } : j)));
      }
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  const fileUrl = (u?: string | null) => (u ? `${api.base}${u}` : undefined);
  const set = (patch: Partial<Filters>) => setF(prev => ({ ...prev, ...patch }));

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">Shortlist — review &amp; prepare</h1>
          <p className="text-muted text-sm">
            {total} matching role{total === 1 ? '' : 's'}
            {f.minRank !== '' ? ` scoring ≥ ${f.minRank}` : ''}. Nothing is
            auto-applied — review, tailor, then apply yourself and mark it.
          </p>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <button
              onClick={toggleFresher}
              title="Fresher mode shows only entry-level roles. Turn off if you're experienced."
              className={fresher ? 'pill-good' : 'pill-mute'}
            >
              {fresher ? '🎓 Fresher mode: ON' : '💼 Experienced mode'}
            </button>
            {cfg && (
              <span className="pill-mute">
                {cfg.geo_filter_enabled ? 'India / remote / sponsored' : 'geo filter off'}
              </span>
            )}
          </div>
        </div>
        <button onClick={rerank} className="btn" disabled={reranking}>
          {reranking ? 'Re-ranking…' : '↻ Rerank jobs'}
        </button>
      </header>

      {/* Filter bar */}
      <div className="card grid grid-cols-2 md:grid-cols-4 gap-3 items-end">
        <div className="col-span-2 md:col-span-1">
          <label className="kv">Search</label>
          <input
            className="block w-full border rounded-md px-3 py-2 text-sm"
            placeholder="title, company, keyword"
            value={f.q}
            onChange={e => set({ q: e.target.value })}
            onKeyDown={e => e.key === 'Enter' && load()}
          />
        </div>
        <div>
          <label className="kv">Min rank</label>
          <input
            type="number"
            min={0}
            max={100}
            className="block w-full border rounded-md px-3 py-2 text-sm"
            value={f.minRank}
            onChange={e => set({ minRank: e.target.value === '' ? '' : Number(e.target.value) })}
          />
        </div>
        <div>
          <label className="kv">Status</label>
          <select
            className="block w-full border rounded-md px-3 py-2 text-sm"
            value={f.status}
            onChange={e => set({ status: e.target.value })}
          >
            <option value="">any</option>
            <option value="ranked">ranked</option>
            <option value="tailored">tailored</option>
            <option value="applied">applied</option>
          </select>
        </div>
        <div>
          <label className="kv">Posted within</label>
          <select
            className="block w-full border rounded-md px-3 py-2 text-sm"
            value={f.postedWithin}
            onChange={e => set({ postedWithin: e.target.value === '' ? '' : Number(e.target.value) })}
          >
            <option value="">any time</option>
            <option value={1}>24 hours</option>
            <option value={3}>3 days</option>
            <option value={7}>1 week</option>
            <option value={30}>1 month</option>
          </select>
        </div>
        <div>
          <label className="kv">Match level</label>
          <select
            className="block w-full border rounded-md px-3 py-2 text-sm"
            value={f.matchLevel}
            onChange={e => set({ matchLevel: e.target.value })}
          >
            <option value="">any</option>
            <option value="excellent">Excellent</option>
            <option value="good">Good</option>
            <option value="maybe">Maybe</option>
          </select>
        </div>
        <div>
          <label className="kv">Sort by</label>
          <select
            className="block w-full border rounded-md px-3 py-2 text-sm"
            value={f.sort}
            onChange={e => set({ sort: e.target.value as 'rank' | 'recent' })}
          >
            <option value="rank">best match</option>
            <option value="recent">most recent</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.remoteOnly} onChange={e => set({ remoteOnly: e.target.checked })} />
          Remote only
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.topOnly} onChange={e => set({ topOnly: e.target.checked })} />
          Top companies
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.watchlistOnly} onChange={e => set({ watchlistOnly: e.target.checked })} />
          ⭐ Watchlist only
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.savedOnly} onChange={e => set({ savedOnly: e.target.checked })} />
          🔖 Saved only
        </label>
        <div className="flex gap-2">
          <button onClick={() => load()} className="btn-ghost flex-1">Apply</button>
          <button
            onClick={() => {
              const reset = { ...EMPTY, minRank: f.minRank };
              setF(reset);
              load(reset);
            }}
            className="btn-ghost"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="space-y-3">
        {loading && <p className="text-muted">Loading…</p>}
        {!loading &&
          items.map(j => {
            const d = docs[j.id];
            const resumeUrl = fileUrl(d?.resume?.download_url);
            const coverUrl = fileUrl(d?.cover_letter?.download_url);
            const prepared = Boolean(resumeUrl || coverUrl);
            return (
              <div key={j.id} className="card">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <a
                        href={j.url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium hover:underline"
                      >
                        {j.title}
                      </a>
                      <MatchPill label={j.match_label} />
                      {j.watchlisted && <span className="pill-good" title="On your watchlist">⭐ Watchlist</span>}
                      <TierPill tier={j.company_tier} />
                      <span className="pill-mute">{j.source}</span>
                      {j.apply_type === 'discovery' && (
                        <span className="pill-warn" title="Link-out only; apply on the source site">discovery</span>
                      )}
                      {j.remote && <span className="pill-info">remote</span>}
                      {j.saved && <span className="pill-info">🔖 saved</span>}
                      {j.applied_manually_at && <span className="pill-good">applied ✓</span>}
                    </div>
                    <div className="kv">
                      <span className="font-medium text-ink">{j.company}</span>
                      {' • '}
                      {j.location ?? '—'}
                      {j.salary_text ? ` • 💰 ${j.salary_text}` : ''}
                      {' • '}
                      <PostedAgo at={j.posted_at || j.discovered_at} />
                    </div>
                    {j.match_signals && <Skills sig={j.match_signals} />}
                    {j.rank_breakdown && <Breakdown b={j.rank_breakdown} />}
                    {j.match_signals?.reasons && j.match_signals.reasons.length > 0 && (
                      <ul className="mt-2 text-sm text-gray-700 dark:text-gray-300 list-disc pl-5">
                        {j.match_signals.reasons.map((r, i) => <li key={i}>{r}</li>)}
                      </ul>
                    )}
                    {j.rank_reasoning && (
                      <p className="text-sm text-gray-700 dark:text-gray-300 mt-2">{j.rank_reasoning}</p>
                    )}
                    {prepared && (
                      <div className="mt-3 flex flex-wrap gap-3 text-sm">
                        {resumeUrl && (
                          <a href={resumeUrl} target="_blank" rel="noreferrer" className="pill-good">
                            ⬇ Tailored résumé
                          </a>
                        )}
                        {coverUrl && (
                          <a href={coverUrl} target="_blank" rel="noreferrer" className="pill-info">
                            ⬇ Cover letter
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <RankBadge score={j.rank_score} />
                    <a href={j.url} target="_blank" rel="noreferrer" className="btn-ghost">
                      Open posting
                    </a>
                    <button
                      className="btn-ghost"
                      onClick={() => tailor(j.id)}
                      disabled={busy === j.id}
                      title="Generate a résumé + cover letter tailored to this job"
                    >
                      {busy === j.id ? 'Preparing…' : prepared ? 'Re-tailor' : 'Tailor & prepare'}
                    </button>
                    {!prepared && j.status === 'tailored' && (
                      <button className="btn-ghost" onClick={() => showFiles(j.id)} disabled={busy === j.id}>
                        Show files
                      </button>
                    )}
                    {j.status !== 'applied' && !j.applied_manually_at && (
                      <button
                        className="btn-ghost"
                        onClick={() => markApplied(j.id)}
                        disabled={busy === j.id}
                        title="You applied on the source site — record it here"
                      >
                        {busy === j.id ? 'Saving…' : 'Mark as applied'}
                      </button>
                    )}
                    <div className="flex flex-wrap gap-1 justify-end text-xs text-muted pt-1">
                      <button title={j.saved ? 'Unsave' : 'Save'} className="hover:text-ink"
                        onClick={() => sendFeedback(j.id, j.saved ? 'unsave' : 'save')}>
                        {j.saved ? '🔖 Saved' : '🔖 Save'}
                      </button>
                      <span>·</span>
                      <button title="Boost similar roles" className="hover:text-ink"
                        onClick={() => sendFeedback(j.id, 'more_like_this')}>👍 More like this</button>
                      <span>·</span>
                      <button title="Hide & downrank similar" className="hover:text-ink"
                        onClick={() => sendFeedback(j.id, 'not_relevant')}>🚫 Not relevant</button>
                      <span>·</span>
                      <button title="Never show this company" className="hover:text-bad"
                        onClick={() => sendFeedback(j.id, 'hide_company', j.company)}>Hide {j.company.slice(0, 16)}</button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        {!loading && items.length === 0 && (
          <div className="card text-center py-10">
            <p className="text-muted">No matching roles for these filters.</p>
            <p className="text-sm text-muted mt-1">
              Try lowering the min rank, clearing filters, or click{' '}
              <b>Rerank jobs</b> to re-score the latest pool.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function PostedAgo({ at }: { at?: string | null }) {
  if (!at) return <span>—</span>;
  const days = Math.floor((Date.now() - new Date(at).getTime()) / 86400000);
  const label = days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days}d ago`;
  return <span title={new Date(at).toLocaleString()}>{label}</span>;
}

function MatchPill({ label }: { label?: string | null }) {
  if (!label) return null;
  const map: Record<string, [string, string]> = {
    excellent: ['pill-good', 'Excellent match'],
    good: ['pill-info', 'Good match'],
    maybe: ['pill-warn', 'Maybe'],
    not_recommended: ['pill-bad', 'Not recommended'],
  };
  const [cls, text] = map[label] || ['pill-mute', label];
  return <span className={cls}>{text}</span>;
}

function TierPill({ tier }: { tier?: number | null }) {
  if (!tier || tier >= 4) return null;
  const text = tier === 1 ? 'Tier 1' : tier === 2 ? 'Tier 2' : 'Tier 3';
  return <span className="pill-mute" title="Company quality tier">{text}</span>;
}

function Skills({ sig }: { sig: NonNullable<Job['match_signals']> }) {
  const matched = sig.matched_skills || [];
  const missing = sig.missing_skills || [];
  if (matched.length === 0 && missing.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1 items-center">
      {matched.slice(0, 8).map(k => (
        <span key={`m${k}`} className="pill-good" title="You have this">✓ {k}</span>
      ))}
      {missing.slice(0, 6).map(k => (
        <span key={`x${k}`} className="pill-mute" title="In the JD, not on your résumé">+ {k}</span>
      ))}
    </div>
  );
}

function Breakdown({ b }: { b: Record<string, number> }) {
  const labels: Record<string, string> = {
    ats_match: 'Role fit',
    shortlist_likelihood: 'Shortlist',
    company_quality: 'Company',
    salary_estimate: 'Salary',
    growth_opportunity: 'Growth',
    remote_flexibility: 'Remote',
  };
  const keys = Object.keys(labels).filter(k => typeof b[k] === 'number');
  if (keys.length === 0) return null;
  return (
    <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 max-w-xl">
      {keys.map(k => (
        <div key={k} className="flex items-center gap-2">
          <span className="kv w-20 shrink-0">{labels[k]}</span>
          <div className="flex-1 h-1.5 rounded bg-gray-200 dark:bg-gray-700 overflow-hidden">
            <div
              className="h-full bg-accent"
              style={{ width: `${Math.max(0, Math.min(100, b[k]))}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function RankBadge({ score }: { score?: number | null }) {
  if (score == null) return <span className="pill-mute">unranked</span>;
  const tone = score >= 80 ? 'pill-good' : score >= 60 ? 'pill-info' : score >= 40 ? 'pill-warn' : 'pill-bad';
  return <span className={`${tone} text-base px-2.5 py-1 font-semibold`}>{score}</span>;
}
