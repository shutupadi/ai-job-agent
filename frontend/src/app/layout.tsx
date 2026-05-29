import './globals.css';
import Link from 'next/link';
import Nav from './Nav';
import { Analytics } from '@vercel/analytics/react';

export const metadata = {
  title: 'AI Job Agent',
  description: 'Automated job search + AI tailored applications.',
};

// Runs before paint to apply the saved/OS theme — avoids a light-mode flash.
const themeScript = `(function(){try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark');}}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen">
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <nav className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 sticky top-0 z-10">
          <div className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-6">
            <Link href="/" className="font-bold text-ink text-lg flex items-center gap-2">
              <span className="inline-block w-6 h-6 rounded-md bg-accent text-white text-sm leading-6 text-center">A</span>
              AI Job Agent
            </Link>
            <Nav />
          </div>
        </nav>
        <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
        <Analytics />
      </body>
    </html>
  );
}
