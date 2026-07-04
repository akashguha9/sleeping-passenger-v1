'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

type NavItem = { href: string; label: string; icon: string };
type NavGroup = { id: string; title: string; description: string; items: NavItem[] };

// Sidebar groups follow the canonical workflow: Review → Decide → Learn → Admin.
// This is the explicit "what do I do next" structure for an operator who has
// never seen the app before. Keep route paths in sync with frontend/src/app.
const NAV_GROUPS: NavGroup[] = [
  {
    id: 'review',
    title: 'Review',
    description: 'See what is happening',
    items: [
      { href: '/', label: 'Dashboard', icon: '⬡' },
      { href: '/signal-inbox', label: 'Signal Inbox', icon: '◈' },
      { href: '/live-signals', label: 'Live Signals', icon: '◆' },
      { href: '/nbi', label: 'Narrative Branches', icon: '◬' },
      { href: '/chart-structure', label: 'Chart Structure', icon: '◫' },
      { href: '/securities', label: 'Securities', icon: '◐' },
    ],
  },
  {
    id: 'decide',
    title: 'Decide',
    description: 'Reflect, log, reconcile — manual only',
    items: [
      { href: '/reflection-desk', label: 'Reflection Desk', icon: '◎' },
      { href: '/manual-trade-log', label: 'Manual Trade Log', icon: '▣' },
      { href: '/reconciliation', label: 'Reconciliation', icon: '◧' },
    ],
  },
  {
    id: 'learn',
    title: 'Learn',
    description: 'Mistakes, lessons, exports',
    items: [
      { href: '/moltbook', label: 'Moltbook', icon: '◑' },
      { href: '/cockpit', label: 'Cockpit', icon: '◳' },
      { href: '/exports', label: 'Exports', icon: '▤' },
    ],
  },
  {
    id: 'admin',
    title: 'Admin',
    description: 'System, help, settings',
    items: [
      { href: '/help', label: 'Help', icon: '?' },
      { href: '/settings', label: 'Settings', icon: '◉' },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="fixed left-0 top-0 bottom-0 w-60 flex flex-col z-10"
      style={{
        background: 'linear-gradient(180deg, rgba(13,16,21,0.96), rgba(6,8,11,0.98))',
        borderRight: '1px solid var(--sp-line)',
        backdropFilter: 'blur(8px)',
      }}
    >
      {/* Brand header */}
      <div className="px-5 pt-6 pb-5" style={{ borderBottom: '1px solid var(--sp-line)' }}>
        <div className="sp-eyebrow mb-2">Signal Intelligence</div>
        <div className="flex items-baseline gap-1.5 leading-none">
          <span className="text-[11px] font-mono" style={{ color: 'var(--sp-gold)' }}>//</span>
          <span
            className="text-[15px] font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)', letterSpacing: '-0.005em' }}
          >
            SleepingPassenger
          </span>
          <span className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>v1</span>
        </div>
        <div className="mt-2 text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
          advisory · human-only
        </div>
        <div
          className="mt-2 text-[10px] leading-snug"
          style={{ color: 'var(--sp-mist)' }}
          title="This app does not place trades. Every action is logged manually by a human."
        >
          Does not place trades.
        </div>
      </div>

      {/* Nav — grouped by workflow phase */}
      <nav className="flex-1 p-3 overflow-y-auto" aria-label="Primary navigation">
        {NAV_GROUPS.map((group) => (
          <div key={group.id} className="mb-4" data-testid={`nav-group-${group.id}`}>
            <div
              className="px-3 pt-1 pb-1.5 text-[9px] font-mono uppercase tracking-widest"
              style={{ color: 'var(--sp-gold)', opacity: 0.7 }}
              title={group.description}
            >
              {group.title}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const active =
                  pathname === item.href ||
                  (item.href !== '/' && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    className="flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors"
                    style={
                      active
                        ? {
                            color: 'var(--sp-bone)',
                            background: 'rgba(200, 154, 74, 0.08)',
                            borderLeft: '1px solid rgba(200, 154, 74, 0.55)',
                            paddingLeft: 'calc(0.75rem - 1px)',
                          }
                        : {
                            color: 'var(--sp-mist)',
                          }
                    }
                  >
                    <span
                      className="text-base leading-none"
                      style={{ color: active ? 'var(--sp-gold)' : 'var(--sp-mist)' }}
                    >
                      {item.icon}
                    </span>
                    <span className="tracking-tight">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* System status footer */}
      <div className="p-4 space-y-2" style={{ borderTop: '1px solid var(--sp-line)' }}>
        <div className="flex items-center justify-between px-1">
          <span className="text-[10px] uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
            AI Executions
          </span>
          <span className="text-xs font-mono font-bold" style={{ color: 'var(--sp-cyan)' }}>0</span>
        </div>
        <div className="flex items-center justify-between px-1">
          <span className="text-[10px] uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
            Mode
          </span>
          <span className="text-xs font-mono" style={{ color: 'var(--sp-gold)' }}>HUMAN_ONLY</span>
        </div>
        <div
          className="mt-2 px-2.5 py-1.5 rounded text-center text-[10px] font-mono uppercase tracking-widest"
          style={{
            color: 'var(--sp-bone)',
            background: 'rgba(200, 154, 74, 0.06)',
            border: '1px solid rgba(200, 154, 74, 0.22)',
          }}
        >
          ADVISORY_ONLY
        </div>
      </div>
    </aside>
  );
}
