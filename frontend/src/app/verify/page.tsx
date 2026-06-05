'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { useAuth } from '../AuthProvider';

const PENDING_KEY = 'aijob_pending_email';

export default function VerifyPage() {
  const { setSession, user, logout } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const timer = useRef<any>(null);

  // Seed the email: from a logged-in unverified session, else the pending key.
  useEffect(() => {
    let e = user?.email || '';
    if (!e && typeof window !== 'undefined') e = localStorage.getItem(PENDING_KEY) || '';
    setEmail(e);
  }, [user]);

  useEffect(() => {
    if (cooldown <= 0) return;
    timer.current = setTimeout(() => setCooldown(c => c - 1), 1000);
    return () => clearTimeout(timer.current);
  }, [cooldown]);

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    setMsg('');
    setBusy(true);
    try {
      const r = await api.verifyEmail(email.trim(), code.trim());
      try { localStorage.removeItem(PENDING_KEY); } catch {}
      api.clearGuestToken();
      setSession(r.access_token, r.user);
      router.replace('/');
    } catch (e: any) {
      setErr(e.message || 'Verification failed');
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setErr('');
    setMsg('');
    try {
      const r = await api.resendOtp(email.trim());
      setCooldown(60);
      setMsg(r.dev_otp ? `Dev mode — your code is ${r.dev_otp}` : 'A new code is on its way.');
    } catch (e: any) {
      setErr(e.message || 'Could not resend code');
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
          <h1 className="text-xl font-bold mt-3">Verify your email</h1>
          <p className="text-muted text-sm">
            We sent a 6-digit code to{' '}
            <b>{email || 'your email'}</b>. Enter it below to finish.
          </p>
        </div>
        <form onSubmit={verify} className="space-y-3">
          {!email && (
            <input
              className="w-full border rounded-md px-3 py-2 text-sm"
              type="email" placeholder="Email" value={email}
              onChange={e => setEmail(e.target.value)} required
            />
          )}
          <input
            className="w-full border rounded-md px-3 py-2 text-center text-lg tracking-[0.5em]"
            inputMode="numeric" placeholder="••••••" value={code}
            onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
            required
          />
          {err && <p className="text-bad text-sm">{err}</p>}
          {msg && <p className="text-good text-sm">{msg}</p>}
          <button className="btn w-full justify-center" disabled={busy || code.length < 4}>
            {busy ? 'Verifying…' : 'Verify & continue'}
          </button>
        </form>
        <div className="flex items-center justify-between text-sm">
          <button
            onClick={resend}
            disabled={cooldown > 0}
            className="text-accent hover:underline disabled:text-muted disabled:no-underline"
          >
            {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
          </button>
          <button onClick={logout} className="text-muted hover:text-ink">Use a different account</button>
        </div>
      </div>
    </div>
  );
}
