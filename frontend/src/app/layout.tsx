import './globals.css';
import AuthProvider from './AuthProvider';
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
        <AuthProvider>
          <Nav />
          <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
        </AuthProvider>
        <Analytics />
      </body>
    </html>
  );
}
