'use client';

import { useEffect, useState } from 'react';
import { api, Job, TailorResponse } from '@/lib/api';

export default function JobsPage() {
  const [items, setItems] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [minRank, setMinRank] = useState<number | ''>('');
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [docs, setDocs] = useState<Record<string, TailorResponse>>({});
  const [cfg, setCfg] = useState<Record<string, any> | null>(null);

  async function load(rank?: number | '') {
    const r = rank === undefined ? minRank : rank;
    const params: Record<string, any> = { limit: 100 };
    if (q) params.q = q;
    if (r !== '' && r != null) params.min_rank = Number(r);
    if (remoteOnly) params.remote_only = true;
    const res = await api.jobs(params);
    setItems(res.items);
    setTotal(res.total);
  }

  // On mount: read the shortlist threshold + active filters, then load.
  useEffect(() => {
    (async () => {
      try {
        const s = await api.settings();
        setCfg(s);
        const thr = typeof s.min_rank_to_apply === 'number' ? s.min_rank_to_apply : 70;
        setMinRank(thr);
        await load(thr);
      } catch {
        setMinRank(70);
        await load(70);
      }
    })();
  }, []); // eslint-disable-line

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

  const fileUrl = (u?: string | null) => (u ? `${api.base}${u}` : undefined);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Shortlist — review &amp; prepare</h1>
        <p className="text-muted text-sm">
          {total} matching role{total === 1 ? '' : 's'}
          {minRank !== '' ? ` scoring ≥ ${minRank}` : ''}. Nothing is auto-applied —
          review, tailor, then apply yourself and mark it.
        </p>
        {cfg && (
          <p className="text-xs text-gray-500 mt-1">
            Filters:{' '}
            {cfg.experience_filter_enabled
              ? `fresher/entry-level only (≤ ${cfg.max_experience_years} yrs)`
              : 'experience filter OFF'}
            {' · '}
            {cfg.geo_filter_enabled ? 'India / remote / sponsored only' : 'geo filter OFF'}
            {' · '}mode: {cfg.apply_mode}
          </p>
        )}
      </header>

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="kv">Search</label>
          <input
            className="block border rounded-md px-3 py-2 text-sm"
            placeholder="title, company, keyword"
            value={q}
            onChange={e => setQ(e.target.value)}
          />
        </div>
        <div>
          <label className="kv">Min rank</label>
          <input
            type="number"
            min={0}
            max={100}
            className="block border rounded-md px-3 py-2 text-sm w-24"
            value={minRank}
            onChange={e =>
              setMinRank(e.target.value === '' ? '' : Number(e.target.value))
            }
          />
        </div>
        <label className="flex items-center gap-2 mb-2 text-sm">
          <input
            type="checkbox"
            checked={remoteOnly}
            onChange={e => setRemoteOnly(e.target.checked)}
          />
          Remote only
        </label>
        <button onClick={() => load()} className="btn-ghost">Filter</button>
        <a href={api.rankOnlyCsvUrl} className="btn-ghost" download>
          Download shortlist CSV
        </a>
      </div>

      <div className="space-y-3">
        {items.map(j => {
          const d = docs[j.id];
          const resumeUrl = fileUrl(d?.resume?.download_url);
          const coverUrl = fileUrl(d?.cover_letter?.download_url);
          const prepared = Boolean(resumeUrl || coverUrl);
          return (
            <div key={j.id} className="card">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <a
                      href={j.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium hover:underline"
                    >
                      {j.title}
                    </a>
                    <span className="pill-mute">{j.source}</span>
                    {j.remote && <span className="pill-info">remote</span>}
                    <span className="pill-mute">{j.status}</span>
                    {j.applied_manually_at && <span className="pill-good">applied ✓</span>}
                  </div>
                  <div className="kv">
                    {j.company} • {j.location ?? '—'}
                    {j.salary_text ? ` • ${j.salary_text}` : ''}
                  </div>
                  {j.ats_keywords && j.ats_keywords.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {j.ats_keywords.slice(0, 12).map(k => (
                        <span key={k} className="pill-mute">{k}</span>
                      ))}
                    </div>
                  )}
                  {j.rank_reasoning && (
                    <p className="text-sm text-gray-700 mt-2">{j.rank_reasoning}</p>
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
                <div className="flex flex-col items-end gap-2">
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
                    <button
                      className="btn-ghost"
                      onClick={() => showFiles(j.id)}
                      disabled={busy === j.id}
                    >
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
                </div>
              </div>
            </div>
          );
        })}
        {items.length === 0 && (
          <p className="text-muted">
            No matching roles yet. Trigger a run, or lower the min rank.
          </p>
        )}
      </div>
    </div>
  );
}

function RankBadge({ score }: { score?: number | null }) {
  if (score == null) return <span className="pill-mute">unranked</span>;
  const tone = score >= 80 ? 'pill-good' : score >= 60 ? 'pill-info' : score >= 40 ? 'pill-warn' : 'pill-bad';
  return <span className={tone}>{score}</span>;
}
