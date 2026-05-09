import type { InboxItem, UserReflection, AiSummary } from '@/types';
import { AdvisoryOnlyBadge } from './AdvisoryOnlyBadge';

interface Props {
  signal: InboxItem;
  reflections: UserReflection[];
  aiSummaries: AiSummary[];
}

export function EvidenceTimeline({ signal, reflections, aiSummaries }: Props) {
  const events = [
    ...reflections.map((r) => ({ type: 'reflection' as const, ts: r.reflected_at, data: r })),
    ...aiSummaries.map((s) => ({ type: 'ai_summary' as const, ts: s.summarized_at, data: s })),
    { type: 'signal' as const, ts: signal.observed_at, data: signal },
  ].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Evidence Timeline</h3>
      {events.length === 0 ? (
        <p className="text-sm text-slate-500">No evidence recorded yet.</p>
      ) : (
        <div className="space-y-3">
          {events.map((ev, i) => (
            <TimelineEvent key={i} event={ev} />
          ))}
        </div>
      )}

      {signal.rejection_dimensions.length > 0 && (
        <div className="mt-4 p-3 rounded bg-red-950/20 border border-red-900/30">
          <div className="text-xs text-slate-500 mb-2">Rejection Dimensions</div>
          <div className="flex flex-wrap gap-1.5 mb-1.5">
            {signal.rejection_dimensions.map((d) => (
              <span key={d} className="text-xs font-mono px-2 py-0.5 rounded bg-red-950/40 text-red-400 border border-red-900/40">
                {d}
              </span>
            ))}
          </div>
          {signal.rejection_reason && (
            <p className="text-xs text-slate-400 mt-1">{signal.rejection_reason}</p>
          )}
        </div>
      )}
    </div>
  );
}

type TimelineEvent =
  | { type: 'reflection'; ts: string; data: UserReflection }
  | { type: 'ai_summary'; ts: string; data: AiSummary }
  | { type: 'signal'; ts: string; data: InboxItem };

function TimelineEvent({ event }: { event: TimelineEvent }) {
  const ts = formatTs(event.ts);

  if (event.type === 'signal') {
    return (
      <div className="flex gap-3">
        <div className="flex flex-col items-center">
          <div className="w-2 h-2 rounded-full bg-slate-500 mt-1 shrink-0" />
          <div className="w-px flex-1 bg-slate-700 mt-1" />
        </div>
        <div className="pb-3 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-slate-400">Signal observed</span>
            <span className="text-xs text-slate-600">{ts}</span>
          </div>
          <p className="text-xs text-slate-500">
            {event.data.ticker} entered fabric as {event.data.signal_state} — {event.data.entry_type}
          </p>
        </div>
      </div>
    );
  }

  if (event.type === 'reflection') {
    return (
      <div className="flex gap-3">
        <div className="flex flex-col items-center">
          <div className="w-2 h-2 rounded-full bg-purple-500 mt-1 shrink-0" />
          <div className="w-px flex-1 bg-slate-700 mt-1" />
        </div>
        <div className="pb-3 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-purple-400">Human reflection</span>
            <span className="text-xs text-slate-600">{event.data.conviction_level}</span>
            <span className="text-xs text-slate-600">{ts}</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">{event.data.reflection_text}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <div className="w-2 h-2 rounded-full bg-sky-500 mt-1 shrink-0" />
        <div className="w-px flex-1 bg-slate-700 mt-1" />
      </div>
      <div className="pb-3 flex-1">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-semibold text-sky-400">AI context</span>
          <AdvisoryOnlyBadge />
          <span className="text-xs text-slate-600">{ts}</span>
        </div>
        <p className="text-xs text-slate-300 leading-relaxed">{event.data.summary_text}</p>
        <p className="text-xs text-slate-600 mt-1 italic">{event.data.advisory_note}</p>
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
