'use client';

import { useRef, useState } from 'react';
import { api, MasterResume } from '@/lib/api';

export default function ResumeUpload({
  onUploaded,
  label = 'Upload résumé (PDF / DOCX)',
}: {
  onUploaded?: (r: MasterResume) => void;
  label?: string;
}) {
  const inp = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  async function handle(file: File) {
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const r = await api.uploadResume(file);
      setMsg(`Parsed “${r.parsed_json?.name || file.name}” ✓`);
      onUploaded?.(r);
    } catch (e: any) {
      setErr(e.message || 'Upload failed');
    } finally {
      setBusy(false);
      if (inp.current) inp.current.value = '';
    }
  }

  return (
    <div className="space-y-2">
      <input
        ref={inp}
        type="file"
        accept=".pdf,.docx,.txt"
        className="hidden"
        onChange={e => {
          const f = e.target.files?.[0];
          if (f) handle(f);
        }}
      />
      <button className="btn" onClick={() => inp.current?.click()} disabled={busy}>
        {busy ? 'Parsing résumé…' : label}
      </button>
      {msg && <p className="text-sm text-good">{msg}</p>}
      {err && <p className="text-sm text-bad">{err}</p>}
    </div>
  );
}
