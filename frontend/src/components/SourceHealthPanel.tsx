import type { SourceHealth } from '@/types';

interface Props {
  sources: SourceHealth[];
}

export function SourceHealthPanel({ sources }: Props) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Source Health</h3>
      <div className="space-y-2">
        {sources.map((s) => (
          <div key={s.source_file} className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  s.status === 'active' ? 'bg-emerald-400' : s.status === 'stale' ? 'bg-yellow-400' : 'bg-slate-500'
                }`}
              />
              <span className="text-xs font-mono text-slate-300 truncate">{s.source_file}</span>
            </div>
            <div className="flex items-center gap-3 shrink-0 text-xs text-slate-500">
              <span>{s.ticker_count} tickers</span>
              <span>{formatAge(s.last_seen)}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 pt-3 border-t border-slate-700/40 text-xs text-slate-600 flex items-center gap-3">
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" /> active</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-yellow-400 inline-block" /> stale</span>
        <span className="ml-auto">Read-only loaders. No execution.</span>
      </div>
    </div>
  );
}

function formatAge(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  } catch {
    return '—';
  }
}
