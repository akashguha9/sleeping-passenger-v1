import type { MoltbookEntry } from '@/types';
import { AdvisoryOnlyBadge } from './AdvisoryOnlyBadge';

const MISTAKE_LABEL: Record<string, string> = {
  good_signal_bad_timing: 'Good Signal, Bad Timing',
  bad_signal_lucky_profit: 'Bad Signal, Lucky Profit',
  good_signal_good_execution: 'Good Signal, Good Execution',
  bad_signal_correct_rejection: 'Bad Signal, Correct Rejection',
  missed_signal: 'Missed Signal',
  overtraded_signal: 'Overtraded Signal',
  chaos_ignored: 'Chaos Ignored',
  false_confirmation: 'False Confirmation',
  late_entry: 'Late Entry',
  early_exit: 'Early Exit',
  no_trade_correct: 'No Trade (Correct)',
  no_trade_missed_opportunity: 'No Trade (Missed Opportunity)',
};

const MISTAKE_COLOR: Record<string, string> = {
  good_signal_bad_timing: 'text-yellow-400 bg-yellow-950/30 border-yellow-900/40',
  bad_signal_lucky_profit: 'text-orange-400 bg-orange-950/30 border-orange-900/40',
  good_signal_good_execution: 'text-emerald-400 bg-emerald-950/30 border-emerald-900/40',
  bad_signal_correct_rejection: 'text-teal-400 bg-teal-950/30 border-teal-900/40',
  missed_signal: 'text-red-400 bg-red-950/30 border-red-900/40',
  overtraded_signal: 'text-orange-400 bg-orange-950/30 border-orange-900/40',
  chaos_ignored: 'text-purple-400 bg-purple-950/30 border-purple-900/40',
  false_confirmation: 'text-red-400 bg-red-950/30 border-red-900/40',
  late_entry: 'text-yellow-400 bg-yellow-950/30 border-yellow-900/40',
  early_exit: 'text-yellow-400 bg-yellow-950/30 border-yellow-900/40',
  no_trade_correct: 'text-emerald-400 bg-emerald-950/30 border-emerald-900/40',
  no_trade_missed_opportunity: 'text-red-400 bg-red-950/30 border-red-900/40',
};

interface Props {
  entry: MoltbookEntry;
}

export function MoltbookEntryCard({ entry }: Props) {
  const mistakeCls = MISTAKE_COLOR[entry.mistake_type] ?? 'text-slate-400 bg-slate-800 border-slate-700';

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-bold text-white font-mono">{entry.ticker}</span>
            <span className={`text-xs px-2 py-0.5 rounded border font-medium ${mistakeCls}`}>
              {MISTAKE_LABEL[entry.mistake_type] ?? entry.mistake_type}
            </span>
          </div>
          <div className="text-xs text-slate-500">{entry.entry_id} · {formatTs(entry.logged_at)}</div>
        </div>
        <AdvisoryOnlyBadge />
      </div>

      {/* Content */}
      <FieldRow label="Original Signal Thesis" content={entry.original_signal_thesis} />
      <FieldRow label="AI Interpretation" content={entry.ai_interpretation} advisory />
      <FieldRow label="Human Reflection" content={entry.user_reflection} />
      <FieldRow label="Final Human Decision" content={entry.final_human_decision} highlight />
      {entry.outcome && <FieldRow label="Outcome" content={entry.outcome} />}

      <div className="grid grid-cols-1 gap-3 pt-1 border-t border-slate-700/40">
        {entry.bias_detected && (
          <div>
            <span className="text-xs text-slate-500">Bias Detected</span>
            <p className="text-xs text-orange-400 font-mono mt-0.5">{entry.bias_detected}</p>
          </div>
        )}
        <FieldRow label="Lesson Learned" content={entry.lesson_learned} />
        {entry.recalibration_note && <FieldRow label="Recalibration Note" content={entry.recalibration_note} />}
        {entry.future_rule_update && (
          <div>
            <span className="text-xs text-slate-500">Suggested Rule Update</span>
            <p className="text-xs text-amber-300 font-mono mt-0.5 leading-relaxed">{entry.future_rule_update}</p>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 text-xs text-slate-600">
        <span>AI executions: <span className="text-emerald-400 font-mono">0</span></span>
        <span>·</span>
        <span>{entry.execution_mode}</span>
      </div>
    </div>
  );
}

function FieldRow({ label, content, advisory, highlight }: {
  label: string;
  content: string;
  advisory?: boolean;
  highlight?: boolean;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-xs text-slate-500">{label}</span>
        {advisory && <span className="text-xs text-sky-500 font-mono">[ADVISORY]</span>}
      </div>
      <p className={`text-sm leading-relaxed ${highlight ? 'text-white font-medium' : 'text-slate-300'}`}>
        {content}
      </p>
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
