import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="max-w-2xl mx-auto py-16 px-4">
      <div className="bg-slate-900 border border-slate-700/60 rounded-lg p-6 space-y-4">
        <div className="flex items-center gap-2">
          <span className="text-slate-400 font-semibold text-sm font-mono">
            ROUTE_NOT_FOUND
          </span>
          <span className="text-xs text-slate-600 font-mono">advisory-only</span>
        </div>
        <h1 className="text-xl font-semibold text-white">
          Route not found
        </h1>
        <p className="text-sm text-slate-400">
          The page you requested doesn&apos;t exist in this dashboard. Nothing was
          executed; <span className="font-mono text-emerald-400">ai_execution_count=0</span>{' '}
          stays locked.
        </p>
        <div className="flex items-center gap-3 pt-2">
          <Link
            href="/"
            className="px-4 py-2 rounded text-sm font-medium bg-slate-700 hover:bg-slate-600 text-white transition-colors"
          >
            Dashboard
          </Link>
          <Link
            href="/signal-inbox"
            className="text-xs text-slate-400 hover:text-slate-200"
          >
            Signal Inbox
          </Link>
          <Link
            href="/settings"
            className="text-xs text-slate-400 hover:text-slate-200"
          >
            Settings
          </Link>
        </div>
        <p className="text-[10px] text-slate-600 font-mono uppercase tracking-widest pt-2 border-t border-slate-700/40">
          ADVISORY_ONLY · HUMAN_ONLY · execution_gate=LOCKED
        </p>
      </div>
    </div>
  );
}
