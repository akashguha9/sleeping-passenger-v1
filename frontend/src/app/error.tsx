'use client';

import { useEffect } from 'react';

interface Props {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ErrorBoundary({ error, reset }: Props) {
  useEffect(() => {
    // Keep error surfacing in the browser console — no remote logging.
    // Advisory-only stamps are intentionally not modified here; this is a
    // UI fallback, not an execution path.
    console.error('[sleeping-passenger] route error:', error);
  }, [error]);

  return (
    <div className="max-w-2xl mx-auto py-16 px-4">
      <div className="bg-slate-900 border border-amber-800/60 rounded-lg p-6 space-y-4">
        <div className="flex items-center gap-2">
          <span className="text-amber-400 font-semibold text-sm font-mono">
            ROUTE_ERROR
          </span>
          <span className="text-xs text-slate-500 font-mono">advisory-only</span>
        </div>
        <h1 className="text-xl font-semibold text-white">
          Something went wrong rendering this screen
        </h1>
        <p className="text-sm text-slate-400">
          The dashboard caught a client-side error. No execution path was
          touched. <span className="text-slate-300">ai_execution_count</span>{' '}
          remains <span className="font-mono text-emerald-400">0</span> and{' '}
          <span className="text-slate-300">broker_api_called</span> remains{' '}
          <span className="font-mono text-emerald-400">false</span>.
        </p>
        {error?.message && (
          <pre className="text-xs text-slate-500 font-mono bg-slate-950/60 border border-slate-700/40 rounded p-3 overflow-auto">
            {error.message}
          </pre>
        )}
        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            onClick={() => reset()}
            className="px-4 py-2 rounded text-sm font-medium bg-slate-700 hover:bg-slate-600 text-white transition-colors"
          >
            Try again
          </button>
          <a
            href="/"
            className="text-xs text-slate-400 hover:text-slate-200"
          >
            Return to dashboard
          </a>
        </div>
        <p className="text-[10px] text-slate-600 font-mono uppercase tracking-widest pt-2 border-t border-slate-700/40">
          ADVISORY_ONLY · HUMAN_ONLY · execution_gate=LOCKED
        </p>
      </div>
    </div>
  );
}
