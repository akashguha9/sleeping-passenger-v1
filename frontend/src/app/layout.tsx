import type { Metadata } from 'next';
import './globals.css';
import { Sidebar } from '@/components/layout/Sidebar';
import { NoExecutionBanner } from '@/components/NoExecutionBanner';

export const metadata: Metadata = {
  title: 'Signal Intelligence Cockpit',
  description: 'Advisory-only signal inbox. This system does not place trades.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100 min-h-screen">
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex-1 flex flex-col min-h-screen ml-60">
            <NoExecutionBanner />
            <main className="flex-1 p-6 overflow-auto">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
