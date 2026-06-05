'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api';
import { useAuth } from '../AuthProvider';
import GoogleButton from '../GoogleButton';

export default function SignupPage() {
  const { setSession } = useAuth();
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const hasGuest = typeof window !== 'undefined' && !!api.getGuestToken();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    if (pw.length < 8) {
      setErr('Password must be at least 8 characters.');
      return;
    }
    setBusy(true);
    try {
      const guestToken = api.getGuestToken() || undefined;
      const r = await api.signupStart(email.trim(), pw, name.trim() || undefined, guestToken);
      if ('access_token' in r) {
        // Verification not enforced (no email provider in prod) → straight in.
        api.clearGuestToken();
        setSession(r.access_token, r.user);
        router.replace('/');
      } else {
        // OTP sent → go verify. (Guest token stays until verification completes.)
        try { localStorage.setItem('aijob_pending_email', email.trim()); } catch {}
        router.push('/verify');
      }
    } catch (e: any) {
      setErr(e.message || 'Sign up failed');
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
          <h1 className="text-xl font-bold mt-3">Create your account</h1>
          <p className="text-muted text-sm">Find jobs tailored to your résumé</p>
          {hasGuest && (
            <p className="pill-good mt-2 inline-block">✓ Your uploaded résumé will be saved</p>
          )}
        </div>
        <form onSubmit={submit} className="space-y-3">
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="text" placeholder="Name (optional)" value={name}
            onChange={e => setName(e.target.value)}
          />
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="email" placeholder="Email" value={email}
            onChange={e => setEmail(e.target.value)} required
          />
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="password" placeholder="Password (min 8 chars)" value={pw}
            onChange={e => setPw(e.target.value)} required minLength={8}
          />
          {err && <p className="text-bad text-sm">{err}</p>}
          <button className="btn w-full justify-center" disabled={busy}>
            {busy ? 'Creating…' : 'Sign up'}
          </button>
        </form>
        <GoogleButton onSession={setSession} />
        <p className="text-sm text-center text-muted">
          Already have an account?{' '}
          <Link href="/login" className="text-accent hover:underline">Log in</Link>
        </p>
      </div>
    </div>
  );
}
