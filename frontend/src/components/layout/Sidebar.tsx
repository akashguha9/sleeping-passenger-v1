'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard', icon: '⬡' },
  { href: '/signal-inbox', label: 'Signal Inbox', icon: '◈' },
  { href: '/reflection-desk', label: 'Reflection Desk', icon: '◎' },
  { href: '/moltbook', label: 'Moltbook', icon: '◑' },
  { href: '/manual-trade-log', label: 'Manual Trade Log', icon: '▣' },
  { href: '/reconciliation', label: 'Reconciliation', icon: '◧' },
  { href: '/exports', label: 'Exports', icon: '▤' },
  { href: '/settings', label: 'Settings', icon: '◉' },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-60 bg-slate-900 border-r border-slate-800 flex flex-col z-10">
      {/* Header */}
      <div className="p-4 border-b border-slate-800">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-1">
          Signal Intelligence
        </div>
        <div className="text-sm font-bold text-slate-100 leading-tight">
          Cockpit v5.7
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors ${
                active
                  ? 'bg-slate-700 text-white font-medium'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              <span className="text-base leading-none">{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* System status footer */}
      <div className="p-3 border-t border-slate-800 space-y-2">
        <div className="flex items-center justify-between px-2">
          <span className="text-xs text-slate-500">AI Executions</span>
          <span className="text-xs font-mono font-bold text-emerald-400">0</span>
        </div>
        <div className="flex items-center justify-between px-2">
          <span className="text-xs text-slate-500">Mode</span>
          <span className="text-xs font-mono text-amber-400">HUMAN_ONLY</span>
        </div>
        <div className="px-2 py-1.5 rounded bg-slate-800 text-center">
          <span className="text-xs text-slate-400 font-medium">ADVISORY_ONLY</span>
        </div>
      </div>
    </aside>
  );
}
