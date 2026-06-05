'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useAuth } from './AuthProvider';

const LINKS = [
  { href: '/', label: 'Dashboard' },
  { href: '/jobs', label: 'Shortlist' },
  { href: '/applications', label: 'Applications' },
  { href: '/preferences', label: 'Preferences' },
  { href: '/settings', label: 'Settings' },
];

export default function Nav() {
  const path = usePathname();
  const { user, logout } = useAuth();
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains('dark'));
  }, []);

  function toggleTheme() {
    const next = !document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', next);
    try {
      localStorage.setItem('theme', next ? 'dark' : 'light');
    } catch {}
    setDark(next);
  }

  // No nav chrome on the auth pages.
  if (path.startsWith('/login') || path.startsWith('/signup')) return null;

  return (
    <nav className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-4">
        <Link href="/" className="font-bold text-ink text-lg flex items-center gap-2">
          <span className="inline-block w-6 h-6 rounded-md bg-accent text-white text-sm leading-6 text-center">A</span>
          <span className="hidden sm:inline">AI Job Agent</span>
        </Link>
        {user && (
          <div className="flex items-center gap-1 text-sm">
            {(user.is_admin ? [...LINKS, { href: '/admin', label: 'Admin' }] : LINKS).map(l => {
              const active = l.href === '/' ? path === '/' : path.startsWith(l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  className={`px-3 py-1.5 rounded-lg transition ${
                    active
                      ? 'bg-blue-50 text-accent font-medium dark:bg-blue-900/40 dark:text-blue-300'
                      : 'text-muted hover:text-ink hover:bg-gray-50 dark:hover:bg-gray-700'
                  }`}
                >
                  {l.label}
                </Link>
              );
            })}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={toggleTheme}
            title="Toggle light / dark"
            aria-label="Toggle dark mode"
            className="px-2 py-1.5 rounded-lg text-muted hover:text-ink hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            {dark ? '☀️' : '🌙'}
          </button>
          {user && (
            <>
              <span className="text-sm text-muted hidden md:inline">{user.email}</span>
              <button onClick={logout} className="btn-ghost">Logout</button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
