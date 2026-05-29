'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, DashboardSummary } from '@/lib/api';

export default function HomePage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setData(await api.dashboard());
    } catch (e: any) {
      setErr(e.message);
    }
  }
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  async function trigger() {
    setBusy(true);
    try {
      await api.triggerRun();
      await new Promise(r => setTimeout(r, 1000));
      await load();
    } finally {
      setBusy(false);
    }
  }

  if (err) return <p className="text-bad">Error: {err}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;

  const lastRun = data.last_run;

  return (
    <div className="space-y-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-muted text-sm">
            Fresher-only job discovery → review → tailor → apply.
          </p>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <span className={data.apply_mode === 'approval' ? 'pill-info' : 'pill-warn'}>
              {data.apply_mode} mode
            </span>
            {data.llm_model && <span className="pill-mute">LLM: {data.llm_model}</span>}
            <span className="pill-mute">shortlist ≥ {data.min_rank_to_apply}</span>
          </div>
        </div>
        <button onClick={trigger} className="btn" disabled={busy}>
          {busy ? 'Triggering…' : 'Run pipeline now'}
        </button>
      </header>

      {/* Review queue CTA — the heart of the approval workflow */}
      <Link
        href="/jobs"
        className="card block hover:shadow-md transition border-l-4 border-l-accent"
      >
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="kv">Waiting for your review</div>
            <div className="text-3xl font-bold text-ink">
              {data.shortlisted}
              <span className="text-base font-medium text-muted"> shortlisted role{data.shortlisted === 1 ? '' : 's'}</span>
            </div>
            <div className="text-sm text-muted mt-1">
              Entry-level matches scoring ≥ {data.min_rank_to_apply}. Click to review, tailor &amp; apply →
            </div>
          </div>
          <span className="pill-good text-base px-3 py-1">Review →</span>
        </div>
      </Link>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Metric label="Jobs discovered" value={data.total_jobs} />
        <Metric label="Ranked" value={data.ranked} />
        <Metric label="Tailored" value={data.tailored} tone="good" />
        <Metric label="Applied" value={data.applied} tone="good" />
        <Metric label="Interviews" value={data.interviews} tone="good" />
        <Metric label="Rejected" value={data.rejected} tone="bad" />
        <Metric label="Failed (auto)" value={data.failed} tone={data.failed ? 'bad' : undefined} />
        <Metric
          label="Last run"
          value={lastRun ? new Date(lastRun.started_at).toLocaleString() : '—'}
        />
      </section>

      {lastRun && (
        <section className="card">
          <h2 className="font-semibold mb-2">Last run</h2>
          <pre className="text-xs whitespace-pre-wrap text-gray-700">{lastRun.summary ?? '—'}</pre>
        </section>
      )}

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold">Top matches</h2>
          <Link href="/jobs" className="text-sm text-accent hover:underline">View all →</Link>
        </div>
        <div className="space-y-3">
          {data.top_jobs.map(j => (
            <Link
              key={j.id}
              href="/jobs"
              className="card hover:shadow-md transition block"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium">{j.title}</span>
                    <span className="pill-mute">{j.source}</span>
                    {j.remote && <span className="pill-info">remote</span>}
                  </div>
                  <div className="kv">
                    {j.company} • {j.location ?? '—'}
                  </div>
                  {j.rank_reasoning && (
                    <div className="text-sm text-gray-700 mt-2 line-clamp-2">
                      {j.rank_reasoning}
                    </div>
                  )}
                </div>
                <RankBadge score={j.rank_score} />
              </div>
            </Link>
          ))}
          {data.top_jobs.length === 0 && (
            <p className="text-muted">
              No ranked jobs yet. Click <b>Run pipeline now</b> to fetch &amp; rank some.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: 'good' | 'bad' | 'warn';
}) {
  const color =
    tone === 'good'
      ? 'text-good'
      : tone === 'bad'
      ? 'text-bad'
      : tone === 'warn'
      ? 'text-warn'
      : 'text-ink';
  return (
    <div className="card">
      <div className="kv">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

function RankBadge({ score }: { score?: number | null }) {
  if (score == null) return <span className="pill-mute">unranked</span>;
  const tone = score >= 80 ? 'pill-good' : score >= 60 ? 'pill-info' : score >= 40 ? 'pill-warn' : 'pill-bad';
  return <span className={tone}>{score}</span>;
}
