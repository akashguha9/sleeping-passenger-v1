'use client';

import Link from 'next/link';
import type { InboxItem } from '@/types';
import { BullStateBadge } from './BullStateBadge';
import { AdvisoryOnlyBadge } from './AdvisoryOnlyBadge';

const STATUS_STYLE: Record<string, string> = {
  pending:      'text-slate-400 bg-slate-800',
  watchlist:    'text-blue-400 bg-blue-950/40',
  human_review: 'text-amber-400 bg-amber-950/40',
  rejected:     'text-red-400 bg-red-950/40',
  reconciled:   'text-emerald-400 bg-emerald-950/40',
};

interface Props {
  item: InboxItem;
}

export function SignalCard({ item }: Props) {
  const statusCls = STATUS_STYLE[item.user_status] ?? STATUS_STYLE['pending'];

  return (
    <Link href={`/signal-inbox/${item.event_id}`} className="block">
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4 hover:border-slate-600 hover:bg-slate-800 transition-colors cursor-pointer">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5">
            <span className="text-lg font-bold text-white font-mono">{item.ticker}</span>
            <BullStateBadge state={item.signal_state} />
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${statusCls}`}>
              {item.user_status.replace('_', ' ')}
            </span>
            <AdvisoryOnlyBadge />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-3">
          <ScoreCell label="Priority" value={item.priority_score} />
          <ScoreCell label="Persistence" value={item.persistence_score} />
          <ScoreCell label="Kill Rate" value={item.kill_rate_score} invert />
        </div>

        {item.rejection_dimensions.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {item.rejection_dimensions.map((d) => (
              <span key={d} className="text-xs px-1.5 py-0.5 rounded bg-red-950/30 text-red-400 border border-red-900/40 font-mono">
                {d}
              </span>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>{item.entry_type}</span>
          <div className="flex items-center gap-2">
            {item.has_reflection && <span className="text-purple-400">◎ reflection</span>}
            {item.has_ai_summary && <span className="text-sky-400">AI context</span>}
            <span>{formatTs(item.observed_at)}</span>
          </div>
        </div>
      </div>
    </Link>
  );
}

function ScoreCell({ label, value, invert }: { label: string; value: number; invert?: boolean }) {
  const pct = Math.round(value * 100);
  const color = invert
    ? value > 0.6 ? 'bg-red-500' : value > 0.3 ? 'bg-yellow-500' : 'bg-emerald-500'
    : value > 0.7 ? 'bg-emerald-500' : value > 0.4 ? 'bg-yellow-500' : 'bg-red-500';

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-500">{label}</span>
        <span className="text-slate-300 font-mono">{value.toFixed(2)}</span>
      </div>
      <div className="h-1 rounded-full bg-slate-700">
        <div className={`h-1 rounded-full ${color} score-bar`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}
