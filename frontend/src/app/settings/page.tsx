'use client';

import { useEffect, useState } from 'react';
import { api, MasterResume } from '@/lib/api';
import { useAuth } from '../AuthProvider';
import ResumeUpload from '../ResumeUpload';

export default function SettingsPage() {
  const { user, refresh } = useAuth();
  const [s, setS] = useState<Record<string, any> | null>(null);
  const [resume, setResume] = useState<MasterResume | null>(null);
  const [msg, setMsg] = useState('');

  async function load() {
    try {
      setS(await api.settings());
    } catch {}
    try {
      setResume(await api.myResume());
    } catch {}
  }
  useEffect(() => {
    load();
  }, []);

  async function save() {
    if (!s) return;
    try {
      await api.patchSettings({
        apply_mode: s.apply_mode,
        min_rank_to_apply: s.min_rank_to_apply,
      });
      setMsg('Saved (in-memory). Persistent changes belong in .env.');
      setTimeout(() => setMsg(''), 3500);
    } catch (e: any) {
      setMsg(e.message || 'Save failed');
    }
  }

  if (!s) return <p className="text-muted">Loading…</p>;
  const admin = !!user?.is_admin;

  return (
    <div className="space-y-6 max-w-2xl">
      <header>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-muted text-sm">Your résumé and how matching works.</p>
      </header>

      {/* Résumé */}
      <div className="card space-y-3">
        <h2 className="font-semibold">Your résumé</h2>
        {resume?.has_resume ? (
          <p className="text-sm">
            Active: <b>{resume.parsed_json?.name || resume.filename || 'uploaded résumé'}</b>
            {resume.filename ? ` (${resume.filename})` : ''}
          </p>
        ) : (
          <p className="text-sm text-muted">No résumé yet — upload one to get matched.</p>
        )}
        <ResumeUpload
          label={resume?.has_resume ? 'Replace résumé' : 'Upload résumé (PDF / DOCX)'}
          onUploaded={r => {
            setResume(r);
            refresh();
          }}
        />
      </div>

      {/* AI model */}
      <div className="card">
        <h2 className="font-semibold mb-2">AI model</h2>
        <div className="flex items-center gap-2 text-sm">
          <span className="pill-info">{s.llm_provider}</span>
          <span className="font-medium">{s.llm_model || '—'}</span>
        </div>
      </div>

      {/* Behaviour (admin-only edits) */}
      <div className="card space-y-4">
        <h2 className="font-semibold">
          Behaviour {!admin && <span className="pill-mute">read-only</span>}
        </h2>
        <Row label="Apply mode">
          <select
            disabled={!admin}
            value={s.apply_mode}
            onChange={e => setS({ ...s, apply_mode: e.target.value })}
            className="border rounded-md px-3 py-2 text-sm disabled:opacity-60"
          >
            <option value="approval">approval (review)</option>
            <option value="auto">auto (legacy)</option>
          </select>
        </Row>
        <Row label="Shortlist threshold (0–100)">
          <input
            disabled={!admin}
            type="number" min={0} max={100}
            value={s.min_rank_to_apply}
            onChange={e => setS({ ...s, min_rank_to_apply: Number(e.target.value) })}
            className="border rounded-md px-3 py-2 text-sm w-24 disabled:opacity-60"
          />
        </Row>
        {admin && (
          <>
            <button onClick={save} className="btn">Save</button>
            {msg && <p className="text-sm text-muted">{msg}</p>}
          </>
        )}
      </div>

      {/* Filters (read-only) */}
      <div className="card">
        <h2 className="font-semibold mb-3">Filters</h2>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <ReadOnly
            label="Fresher / entry-level"
            on={s.experience_filter_enabled}
            extra={s.experience_filter_enabled ? `≤ ${s.max_experience_years} yrs` : ''}
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
