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

const PUBLIC = ['/login', '/signup'];

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const path = usePathname();
  const isPublic = PUBLIC.some(p => path.startsWith(p));

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

  // Route guard: bounce unauthenticated users to /login, authed users away from auth pages.
  useEffect(() => {
    if (loading) return;
    if (!user && !isPublic) router.replace('/login');
    if (user && isPublic) router.replace('/');
  }, [user, loading, isPublic]); // eslint-disable-line

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
  }

  return (
    <Ctx.Provider value={{ user, loading, setSession, logout, refresh }}>
      {body}
    </Ctx.Provider>
  );
}
