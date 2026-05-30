'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api';
import { useAuth } from '../AuthProvider';
import GoogleButton from '../GoogleButton';

export default function LoginPage() {
  const { setSession } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr('');
    setBusy(true);
    try {
      const r = await api.login(email.trim(), pw);
      setSession(r.access_token, r.user);
      router.replace('/');
    } catch (e: any) {
      setErr(e.message || 'Login failed');
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
          <h1 className="text-xl font-bold mt-3">Welcome back</h1>
          <p className="text-muted text-sm">Log in to your account</p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="email" placeholder="Email" value={email}
            onChange={e => setEmail(e.target.value)} required
          />
          <input
            className="w-full border rounded-md px-3 py-2 text-sm"
            type="password" placeholder="Password" value={pw}
            onChange={e => setPw(e.target.value)} required
          />
          {err && <p className="text-bad text-sm">{err}</p>}
          <button className="btn w-full justify-center" disabled={busy}>
            {busy ? 'Logging in…' : 'Log in'}
          </button>
        </form>
        <GoogleButton onSession={setSession} />
        <p className="text-sm text-center text-muted">
          No account?{' '}
          <Link href="/signup" className="text-accent hover:underline">Sign up</Link>
        </p>
      </div>
    </div>
  );
}
