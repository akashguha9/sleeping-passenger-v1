import type { Metadata } from 'next';
import './globals.css';
import { Sidebar } from '@/components/layout/Sidebar';
import { NoExecutionBanner } from '@/components/NoExecutionBanner';

export const metadata: Metadata = {
  title: '//SleepingPassenger v1',
  description: 'Advisory-only signal intelligence. This system does not place trades.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="text-slate-100 min-h-screen">
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex-1 flex flex-col min-h-screen ml-60">
            <NoExecutionBanner />
            <main className="flex-1 p-8 overflow-auto">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
