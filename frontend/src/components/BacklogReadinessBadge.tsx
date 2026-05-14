'use client';

import {
  deriveBacklogReadiness,
  type BacklogReadinessInput,
} from '@/lib/backlogReadiness';

/**
 * Reads a reconciliation-queue summary, derives the local-operating
 * readiness state from the unreconciled-backlog thresholds, and renders
 * an advisory chip plus optional one-sentence detail.
 *
 * Advisory only. A reactor green state cannot unblock a BLOCKED
 * backlog — that's enforced at the backend `run_preflight` level and
 * mirrored visually here for operator clarity.
 */
interface Props {
  input: BacklogReadinessInput;
  detail?: boolean;
  size?: 'sm' | 'md';
}

const STATE_STYLE: Record<string, { fg: string; bg: string; border: string }> = {
  CLEAR: {
    fg: 'text-emerald-300',
    bg: 'bg-emerald-950/30',
    border: 'border-emerald-900/40',
  },
  WARN: {
    fg: 'text-amber-300',
    bg: 'bg-amber-950/30',
    border: 'border-amber-900/40',
  },
  BLOCKED: {
    fg: 'text-red-200',
    bg: 'bg-red-950/60',
    border: 'border-red-800/70',
  },
  FULL_REVIEW_REQUIRED: {
    fg: 'text-red-100',
    bg: 'bg-red-900/70',
    border: 'border-red-700/80',
  },
  UNKNOWN: {
    fg: 'text-slate-500',
    bg: 'bg-slate-900/40',
    border: 'border-slate-700/40',
  },
};

export function BacklogReadinessBadge({ input, detail = false, size = 'sm' }: Props) {
  const r = deriveBacklogReadiness(input);
  const style = STATE_STYLE[r.state];
  const sizeCls = size === 'md' ? 'px-2 py-0.5 text-[11px]' : 'px-1.5 py-0.5 text-[10px]';

  return (
    <div
      className="inline-flex flex-col items-start gap-1"
      data-testid="backlog-readiness-badge"
      data-backlog-state={r.state}
      data-preflight-blocked-by-backlog={String(r.preflight_blocked_by_backlog)}
    >
      <span
        className={`${sizeCls} ${style.fg} ${style.bg} border ${style.border} rounded font-mono uppercase tracking-wider`}
        title={r.detail}
      >
        {r.label}
      </span>
      {detail && (
        <span
          className="text-[10px] text-slate-400 leading-snug max-w-md"
          data-testid="backlog-readiness-detail"
        >
          {r.detail}
        </span>
      )}
    </div>
  );
}
