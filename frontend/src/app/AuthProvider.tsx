'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { api, User } from '@/lib/api';

type AuthCtx = {
  user: User | null;
  loading: boolean;
  setSession: (token: string, user: User) => void;
  logout: () => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthCtx>({
  user: null,
  loading: true,
  setSession: () => {},
  logout: () => {},
  refresh: async () => {},
});

export const useAuth = () => useContext(Ctx);

// '/' is public so guests can upload a résumé before signing up; page.tsx shows
// the guest landing when logged out and the dashboard when logged in.
const PUBLIC = ['/', '/login', '/signup', '/verify'];
const AUTH_PAGES = ['/login', '/signup', '/verify'];

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const path = usePathname();
  // Exact match for '/', prefix match for the rest.
  const isPublic = path === '/' || PUBLIC.filter(p => p !== '/').some(p => path.startsWith(p));
  const onAuthPage = AUTH_PAGES.some(p => path.startsWith(p));
  const verified = !user || user.email_verified !== false;

  async function refresh() {
    if (!api.isAuthed()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []); // eslint-disable-line

  // Route guard:
  //  • not logged in + on a protected page → /login
  //  • logged in but email NOT verified → /verify (locked out of everything else)
  //  • logged in + verified, sitting on an auth page → /
  useEffect(() => {
    if (loading) return;
    if (!user && !isPublic) {
      router.replace('/login');
    } else if (user && !verified && path !== '/verify') {
      router.replace('/verify');
    } else if (user && verified && onAuthPage) {
      router.replace('/');
    }
  }, [user, loading, isPublic, onAuthPage, verified, path]); // eslint-disable-line

  function setSession(token: string, u: User) {
    api.setToken(token);
    setUser(u);
  }
  function logout() {
    api.clearToken();
    setUser(null);
    router.replace('/login');
  }

  let body: React.ReactNode = children;
  if (loading) {
    body = <div className="max-w-6xl mx-auto px-6 py-16 text-muted">Loading…</div>;
  } else if (!user && !isPublic) {
    body = <div className="max-w-6xl mx-auto px-6 py-16 text-muted">Redirecting…</div>;
  } else if (user && !verified && path !== '/verify') {
    body = <div className="max-w-6xl mx-auto px-6 py-16 text-muted">Redirecting…</div>;
  }

  return (
    <Ctx.Provider value={{ user, loading, setSession, logout, refresh }}>
      {body}
    </Ctx.Provider>
  );
}
