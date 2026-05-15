'use client';

import type { LiveSourceStatusEntry, SourceHealthLabel } from '@/types';

interface Props {
  entry: Pick<
    LiveSourceStatusEntry,
    'health_label' | 'health_reasons' | 'health_score' | 'operator_message' | 'tier'
  >;
  /** Render top reason inline (default off — most surfaces want only the chip). */
  showReason?: boolean;
}

const LABEL_STYLE: Record<string, { fg: string; bg: string; border: string }> = {
  healthy: {
    fg: 'text-emerald-300',
    bg: 'bg-emerald-950/30',
    border: 'border-emerald-900/40',
  },
  watch: {
    fg: 'text-amber-300',
    bg: 'bg-amber-950/30',
    border: 'border-amber-900/40',
  },
  degraded: {
    fg: 'text-orange-300',
    bg: 'bg-orange-950/40',
    border: 'border-orange-900/50',
  },
  unhealthy: {
    fg: 'text-rose-200',
    bg: 'bg-rose-950/50',
    border: 'border-rose-800/60',
  },
  planned_not_scored: {
    fg: 'text-slate-400',
    bg: 'bg-slate-900/40',
    border: 'border-slate-700/40',
  },
  optional_config_missing: {
    fg: 'text-slate-300',
    bg: 'bg-slate-900/50',
    border: 'border-slate-700/50',
  },
};

const FALLBACK_STYLE = LABEL_STYLE.watch;

export function SourceHealthBadge({ entry, showReason = false }: Props) {
  const label = (entry.health_label ?? 'watch') as SourceHealthLabel;
  const style = LABEL_STYLE[label] ?? FALLBACK_STYLE;
  const score = entry.health_score;
  const reason = entry.health_reasons?.[0] ?? '';
  const message = entry.operator_message ?? '';
  return (
    <div
      className="inline-flex flex-col items-start gap-1"
      data-testid="source-health-badge"
      data-health-label={label}
      data-health-score={score === null || score === undefined ? '' : String(score)}
      data-advisory-only="true"
      data-execution-permission="false"
    >
      <span
        className={`px-1.5 py-0.5 text-[10px] ${style.fg} ${style.bg} border ${style.border} rounded font-mono uppercase tracking-wider`}
        title={message || reason}
      >
        {label}
        {typeof score === 'number' && (
          <span className="ml-1 opacity-70">{score.toFixed(2)}</span>
        )}
      </span>
      {showReason && reason && (
        <span
          className="text-[10px] text-slate-400 leading-snug"
          data-testid="source-health-reason"
        >
          {reason}
        </span>
      )}
    </div>
  );
}
