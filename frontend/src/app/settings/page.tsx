'use client';

import { useEffect, useState } from 'react';

type Settings = {
  apply_mode: string;
  min_rank_to_apply: number;
  max_applications_per_run: number;
  rate_limit_seconds: number;
  keywords: string[];
  locations: string[];
  greenhouse_boards: string[];
  lever_companies: string[];
  enable_greenhouse: boolean;
  enable_lever: boolean;
  enable_ycombinator: boolean;
  enable_workday: boolean;
  enable_oracle: boolean;
  enable_linkedin: boolean;
  enable_naukri: boolean;
  include_remote: boolean;
  include_international: boolean;
  geo_filter_enabled: boolean;
  experience_filter_enabled: boolean;
  max_experience_years: number;
  llm_provider: string;
  llm_model: string;
};

const BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [msg, setMsg] = useState('');

  async function load() {
    const r = await fetch(`${BASE}/api/settings`).then(r => r.json());
    setS(r);
  }
  useEffect(() => {
    load();
  }, []);

  async function save() {
    if (!s) return;
    const body = {
      apply_mode: s.apply_mode,
      min_rank_to_apply: s.min_rank_to_apply,
      max_applications_per_run: s.max_applications_per_run,
      rate_limit_seconds: s.rate_limit_seconds,
    };
    const res = await fetch(`${BASE}/api/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      setMsg('Saved (in-memory). For permanent changes edit .env and restart.');
      setTimeout(() => setMsg(''), 3500);
    } else {
      setMsg('Save failed.');
    }
  }

  if (!s) return <p className="text-muted">Loading…</p>;

  return (
    <div className="space-y-6 max-w-2xl">
      <header>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-muted text-sm">
          Tweak runtime knobs. Persistent changes belong in <code>.env</code>.
        </p>
      </header>

      {/* AI model */}
      <div className="card">
        <h2 className="font-semibold mb-2">AI model</h2>
        <div className="flex items-center gap-2 text-sm">
          <span className="pill-info">{s.llm_provider}</span>
          <span className="font-medium">{s.llm_model || '—'}</span>
        </div>
        <p className="kv mt-1">Used for ranking, résumé tailoring and cover letters.</p>
      </div>

      {/* Editable knobs */}
      <div className="card space-y-4">
        <h2 className="font-semibold">Behaviour</h2>
        <Row label="Apply mode">
          <select
            value={s.apply_mode}
            onChange={e => setS({ ...s, apply_mode: e.target.value })}
            className="border rounded-md px-3 py-2 text-sm"
          >
            <option value="approval">approval (review, no auto-apply)</option>
            <option value="auto">auto (legacy auto-apply)</option>
          </select>
        </Row>
        <Row label="Shortlist threshold (min rank 0–100)">
          <input
            type="number"
            min={0}
            max={100}
            value={s.min_rank_to_apply}
            onChange={e => setS({ ...s, min_rank_to_apply: Number(e.target.value) })}
            className="border rounded-md px-3 py-2 text-sm w-24"
          />
        </Row>
        <Row label="Max applications per run">
          <input
            type="number"
            value={s.max_applications_per_run}
            onChange={e =>
              setS({ ...s, max_applications_per_run: Number(e.target.value) })
            }
            className="border rounded-md px-3 py-2 text-sm w-24"
          />
        </Row>
        <Row label="Rate limit (seconds)">
          <input
            type="number"
            value={s.rate_limit_seconds}
            onChange={e =>
              setS({ ...s, rate_limit_seconds: Number(e.target.value) })
            }
            className="border rounded-md px-3 py-2 text-sm w-24"
          />
        </Row>

        <button onClick={save} className="btn">Save</button>
        {msg && <p className="text-sm text-muted">{msg}</p>}
      </div>

      {/* Filters */}
      <div className="card">
        <h2 className="font-semibold mb-3">Filters</h2>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <ReadOnly
            label="Fresher / entry-level"
            on={s.experience_filter_enabled}
            extra={s.experience_filter_enabled ? `≤ ${s.max_experience_years} yrs experience` : ''}
          />
          <ReadOnly
            label="Geo gate"
            on={s.geo_filter_enabled}
            extra={s.geo_filter_enabled ? 'India / remote / sponsored' : ''}
          />
          <ReadOnly label="Include remote" on={s.include_remote} extra="" />
          <ReadOnly label="Include international" on={s.include_international} extra="" />
        </div>
      </div>

      {/* Sources */}
      <div className="card">
        <h2 className="font-semibold mb-3">Sources</h2>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <ReadOnly label="Greenhouse" on={s.enable_greenhouse} extra={s.greenhouse_boards.join(', ')} />
          <ReadOnly label="Lever" on={s.enable_lever} extra={s.lever_companies.join(', ')} />
          <ReadOnly label="Y Combinator" on={s.enable_ycombinator} extra="" />
          <ReadOnly label="Workday" on={s.enable_workday} extra="" />
          <ReadOnly label="Oracle" on={s.enable_oracle} extra="" />
          <ReadOnly label="LinkedIn" on={s.enable_linkedin} extra="" />
          <ReadOnly label="Naukri" on={s.enable_naukri} extra="" />
        </div>
      </div>

      {/* Targeting */}
      <div className="card">
        <h2 className="font-semibold mb-2">Targeting</h2>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <div className="kv">Keywords</div>
            <div>{s.keywords.join(', ')}</div>
          </div>
          <div>
            <div className="kv">Locations</div>
            <div>{s.locations.join(', ')}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <label className="kv flex-1">{label}</label>
      <div>{children}</div>
    </div>
  );
}

function ReadOnly({ label, on, extra }: { label: string; on: boolean; extra: string }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="font-medium">{label}</span>
        <span className={on ? 'pill-good' : 'pill-mute'}>{on ? 'on' : 'off'}</span>
      </div>
      {extra && <div className="kv truncate">{extra}</div>}
    </div>
  );
}
