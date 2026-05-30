'use client';

import { useEffect, useRef } from 'react';
import { api, User } from '@/lib/api';

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '';

// Renders the official "Continue with Google" button — but only if a public
// Google client id is configured. Otherwise it renders nothing, so email/
// password still works out of the box.
export default function GoogleButton({
  onSession,
}: {
  onSession: (token: string, user: User) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!CLIENT_ID || !ref.current) return;

    function init() {
      const g = (window as any).google;
      if (!g?.accounts?.id) return;
      g.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: async (resp: any) => {
          try {
            const r = await api.google(resp.credential);
            onSession(r.access_token, r.user);
            location.href = '/';
          } catch (e: any) {
            alert(e.message || 'Google sign-in failed');
          }
        },
      });
      g.accounts.id.renderButton(ref.current, {
        theme: 'outline',
        size: 'large',
        text: 'continue_with',
        width: 280,
      });
    }

    const id = 'gis-script';
    if (document.getElementById(id)) {
      init();
      return;
    }
    const s = document.createElement('script');
    s.id = id;
    s.src = 'https://accounts.google.com/gsi/client';
    s.async = true;
    s.defer = true;
    s.onload = init;
    document.head.appendChild(s);
  }, []); // eslint-disable-line

  if (!CLIENT_ID) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted">
        <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
        or
        <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
      </div>
      <div ref={ref} className="flex justify-center" />
    </div>
  );
}
