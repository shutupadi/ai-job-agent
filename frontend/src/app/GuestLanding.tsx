'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';
import { api, GuestUploadResponse } from '@/lib/api';

export default function GuestLanding() {
  const inp = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [res, setRes] = useState<GuestUploadResponse | null>(null);

  async function handle(file: File) {
    setBusy(true);
    setErr('');
    try {
      const r = await api.guestUpload(file);
      api.setGuestToken(r.token); // carried into signup
      setRes(r);
    } catch (e: any) {
      setErr(e.message || 'Upload failed');
    } finally {
      setBusy(false);
      if (inp.current) inp.current.value = '';
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <header className="text-center pt-6">
        <div className="inline-flex items-center gap-2 font-bold text-lg">
          <span className="inline-block w-7 h-7 rounded-md bg-accent text-white leading-7 text-center">A</span>
          AI Job Agent
        </div>
        <h1 className="text-3xl font-bold mt-4">Upload your résumé. Get matched.</h1>
        <p className="text-muted mt-2">
          We parse your résumé and instantly preview your career profile and sample
          matches — no signup required to look.
        </p>
        <div className="mt-2">
          <Link href="/login" className="text-sm text-accent hover:underline">
            Already have an account? Log in
          </Link>
        </div>
      </header>

      {!res && (
        <div className="card text-center py-10 space-y-4 border-dashed border-2">
          <input
            ref={inp}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="hidden"
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) handle(f);
            }}
          />
          <p className="text-muted">PDF, DOCX, or TXT · max 5&nbsp;MB · never auto-applied</p>
          <button className="btn text-base px-5 py-3" onClick={() => inp.current?.click()} disabled={busy}>
            {busy ? 'Parsing your résumé…' : '📄 Upload résumé'}
          </button>
          {err && <p className="text-bad text-sm">{err}</p>}
        </div>
      )}

      {res && <Preview res={res} onReset={() => { setRes(null); api.clearGuestToken(); }} />}
    </div>
  );
}

function Preview({ res, onReset }: { res: GuestUploadResponse; onReset: () => void }) {
  const p = res.profile;
  const level =
    p.seniority === 'entry' ? 'Entry / fresher'
    : p.seniority === 'mid' ? 'Mid-level'
    : p.seniority === 'senior' ? 'Senior'
    : `${p.experience_years || 0} yrs`;

  return (
    <div className="space-y-5">
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-lg">Your career profile</h2>
          <button onClick={onReset} className="text-sm text-muted hover:text-ink">Upload a different file</button>
        </div>
        <div className="grid sm:grid-cols-2 gap-3 text-sm">
          <Info label="Name" value={p.name || '—'} />
          <Info label="Experience level" value={level} />
          <Info label="Role direction" value={p.role_direction || '—'} />
          <Info label="Experience (years)" value={String(p.experience_years ?? 0)} />
        </div>
        {p.target_titles?.length > 0 && (
          <Tags label="Target roles" items={p.target_titles} tone="pill-info" />
        )}
        {p.primary_skills?.length > 0 && (
          <Tags label="Primary skills" items={p.primary_skills} tone="pill-mute" />
        )}
      </div>

      {res.sample_matches.length > 0 && (
        <div className="card space-y-2">
          <h2 className="font-semibold">A few roles you might fit</h2>
          <p className="kv">Sample only — create an account for full AI ranking.</p>
          <div className="space-y-2 mt-1">
            {res.sample_matches.map((j, i) => (
              <div key={i} className="flex items-center justify-between gap-3 border-b last:border-0 border-gray-100 dark:border-gray-700 py-1.5">
                <div className="min-w-0">
                  <div className="font-medium truncate">{j.title}</div>
                  <div className="kv truncate">{j.company} • {j.location || '—'}</div>
                </div>
                {j.remote && <span className="pill-info shrink-0">remote</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card text-center space-y-3 border-l-4 border-l-accent">
        <h2 className="font-semibold text-lg">Create a free account to save this profile</h2>
        <p className="text-muted text-sm">
          Unlock full AI ranking, résumé tailoring, job alerts and your watchlist.
          Your uploaded résumé carries over automatically.
        </p>
        <div className="flex gap-3 justify-center">
          <Link href="/signup" className="btn text-base px-5 py-2.5">Create free account →</Link>
          <Link href="/login" className="btn-ghost">Log in</Link>
        </div>
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="kv">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

function Tags({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  return (
    <div>
      <div className="kv mb-1">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.slice(0, 14).map((t, i) => <span key={i} className={tone}>{t}</span>)}
      </div>
    </div>
  );
}
