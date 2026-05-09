'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getMockSignalDetail } from '@/lib/mockData';
import { BullStateBadge } from '@/components/BullStateBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { SignalScorePanel } from '@/components/SignalScorePanel';
import { EvidenceTimeline } from '@/components/EvidenceTimeline';
import { ReflectionChatPanel } from '@/components/ReflectionChatPanel';
import { ManualTradeLogForm } from '@/components/ManualTradeLogForm';

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-slate-400',
  watchlist: 'text-blue-400',
  human_review: 'text-amber-400',
  rejected: 'text-red-400',
  reconciled: 'text-emerald-400',
};

export default function SignalDetailPage() {
  const params = useParams();
  const eventId = decodeURIComponent(String(params.id));
  const detail = getMockSignalDetail(eventId);
  const { signal, reflections, ai_summaries, manual_trades } = detail;

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Link href="/signal-inbox" className="hover:text-slate-300">Signal Inbox</Link>
        <span>/</span>
        <span className="text-slate-300 font-mono">{signal.ticker}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-2xl font-bold font-mono text-white">{signal.ticker}</h1>
            <BullStateBadge state={signal.signal_state} size="lg" />
            <span className={`text-sm font-medium ${STATUS_COLORS[signal.user_status] ?? 'text-slate-400'}`}>
              {signal.user_status.replace('_', ' ')}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <AdvisoryOnlyBadge size="md" />
            <HumanOnlyBadge size="md" />
            <span className="text-xs text-slate-600">HUMAN_REVIEW_REQUIRED</span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-xs text-slate-500">Observed</div>
          <div className="text-sm text-slate-300">{formatTs(signal.observed_at)}</div>
        </div>
      </div>

      {/* Safety note */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-xs text-slate-400">
        This view is <span className="text-amber-400 font-semibold">ADVISORY_ONLY</span>. Viewing this signal does not constitute a recommendation, trigger, or authorization to execute any trade. AI execution count: <span className="text-emerald-400 font-mono font-bold">0</span>.
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Left column */}
        <div className="space-y-5">
          <SignalScorePanel signal={signal} />

          {/* Source files */}
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Sources</h3>
            <div className="space-y-1">
              {signal.source_file.split(',').map((f) => (
                <div key={f} className="text-xs font-mono text-slate-400">{f.trim()}</div>
              ))}
            </div>
          </div>

          {/* Quick mark (mock only) */}
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Mark Signal</h3>
            <p className="text-xs text-slate-600 mb-3">ADVISORY_ONLY — status change requires human decision.</p>
            <div className="flex flex-wrap gap-2">
              {['pending', 'watchlist', 'human_review', 'rejected'].map((s) => (
                <button
                  key={s}
                  className="px-2.5 py-1.5 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-300 font-medium transition-colors"
                >
                  {s.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right column (2/3) */}
        <div className="lg:col-span-2 space-y-5">
          <EvidenceTimeline signal={signal} reflections={reflections} aiSummaries={ai_summaries} />
          <ReflectionChatPanel eventId={eventId} reflections={reflections} aiSummaries={ai_summaries} />

          {/* Manual trades on this signal */}
          {manual_trades.length > 0 && (
            <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-semibold text-slate-300">Logged Trades</h3>
                <HumanOnlyBadge />
              </div>
              {manual_trades.map((t) => (
                <div key={t.trade_id} className="text-xs font-mono text-slate-400 bg-slate-900/40 rounded p-3 border border-slate-700/40">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="font-bold text-slate-200">{t.ticker}</span>
                    <span className={t.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}>{t.side === 'BUY' ? 'LONG' : 'SHORT'}</span>
                    <span>×{t.quantity}</span>
                    <span>@ ${t.price}</span>
                    <span className="ml-auto text-slate-600">{t.trade_id}</span>
                  </div>
                  <p className="text-slate-500 font-sans">{t.thesis}</p>
                  <div className="flex gap-3 mt-1.5 text-slate-600">
                    <span>Broker API: NOT CALLED</span>
                    <span>AI executions: 0</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          <ManualTradeLogForm defaultEventId={eventId} defaultTicker={signal.ticker} />
        </div>
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
