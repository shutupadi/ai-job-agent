'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { useAuth } from '../AuthProvider';

export default function ResetPasswordPage() {
  const { setSession } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    try {
      const e = localStorage.getItem('aijob_pending_email');
      if (e) setEmail(e);
    } catch {}
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    if (pw.length < 8) {
      setErr('Password must be at least 8 characters.');
      return;
    }
    setBusy(true);
    try {
      const r = await api.resetPassword(email.trim(), code.trim(), pw);
      try { localStorage.removeItem('aijob_pending_email'); } catch {}
      setSession(r.access_token, r.user);
      router.replace('/');
    } catch (e: any) {
      setErr(e.message || 'Reset failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[70vh] flex items-center justify-center">
      <div className="card w-full max-w-sm space-y-5">
        <div className="text-center">
          <div className="inline-flex items-center gap-2 font-bold text-lg">
            <span className="inline-block w-7 h-7 rounded-md bg-accent text-white leading-7 text-center">A</span>
            AI Job Agent
          </div>
          <h1 className="text-xl font-bold mt-3">Set a new password</h1>
          <p className="text-muted text-sm">Enter the code we emailed and your new password.</p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="email" placeholder="Email" value={email}
            onChange={e => setEmail(e.target.value)} required
          />
          <input
            className="w-full border rounded-md px-3 py-2 text-center text-lg tracking-[0.4em]"
            inputMode="numeric" placeholder="Code" value={code}
            onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 8))} required
          />
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="password" placeholder="New password (min 8 chars)" value={pw}
            onChange={e => setPw(e.target.value)} required minLength={8}
          />
          {err && <p className="text-bad text-sm">{err}</p>}
          <button className="btn w-full justify-center" disabled={busy || code.length < 4}>
            {busy ? 'Resetting...' : 'Reset password'}
          </button>
        </form>
        <p className="text-sm text-center text-muted">
          <Link href="/forgot-password" className="text-accent hover:underline">Resend code</Link>
          {' . '}
          <Link href="/login" className="text-accent hover:underline">Back to log in</Link>
        </p>
      </div>
    </div>
  );
}
