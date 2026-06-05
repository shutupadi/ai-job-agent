'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api';

export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    setMsg('');
    setBusy(true);
    try {
      const r = await api.forgotPassword(email.trim());
      try { localStorage.setItem('aijob_pending_email', email.trim()); } catch {}
      setMsg(
        r.dev_otp
          ? `Dev mode - your reset code is ${r.dev_otp}`
          : 'If an account exists for that email, a reset code is on its way.',
      );
      setTimeout(() => router.push('/reset-password'), 900);
    } catch (e: any) {
      setErr(e.message || 'Request failed');
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
          <h1 className="text-xl font-bold mt-3">Reset your password</h1>
          <p className="text-muted text-sm">Enter your email and we'll send a reset code.</p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="email" placeholder="Email" value={email}
            onChange={e => setEmail(e.target.value)} required
          />
          {err && <p className="text-bad text-sm">{err}</p>}
          {msg && <p className="text-good text-sm">{msg}</p>}
          <button className="btn w-full justify-center" disabled={busy}>
            {busy ? 'Sending...' : 'Send reset code'}
          </button>
        </form>
        <p className="text-sm text-center text-muted">
          <Link href="/login" className="text-accent hover:underline">Back to log in</Link>
        </p>
      </div>
    </div>
  );
}
