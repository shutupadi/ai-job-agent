'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';

const LINKS = [
  { href: '/', label: 'Dashboard' },
  { href: '/jobs', label: 'Shortlist' },
  { href: '/applications', label: 'Applications' },
  { href: '/settings', label: 'Settings' },
];

export default function Nav() {
  const path = usePathname();
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

  return (
    <div className="flex items-center gap-1 text-sm flex-1">
      {LINKS.map(l => {
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
      <button
        onClick={toggleTheme}
        title="Toggle light / dark"
        aria-label="Toggle dark mode"
        className="ml-auto px-2 py-1.5 rounded-lg text-muted hover:text-ink hover:bg-gray-50 dark:hover:bg-gray-700"
      >
        {dark ? '☀️' : '🌙'}
      </button>
    </div>
  );
}
