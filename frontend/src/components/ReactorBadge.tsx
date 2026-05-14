'use client';

import type { ReactorState } from '@/types';

/**
 * Compact, advisory-only badge showing the Signal Reactor state and an
 * optional gallardo-block warning for an inbox card.
 *
 * The Signal Reactor is a diagnostic layer — it never authorises trades,
 * never places orders, never connects to a broker. This badge mirrors
 * that contract in copy: reading it does not constitute permission.
 */
interface Props {
  state?: ReactorState | string;
  gallardoBlock?: boolean;
  reactorAvailable?: boolean;
  size?: 'sm' | 'md';
}

// Style table per canonical reactor state.  Cool / amber / red bands map
// to "observe / watch / warn" — kept conservative on purpose so a high
// decision_grade_energy does not visually shout "go".
const STATE_STYLE: Record<string, { fg: string; bg: string; border: string; label: string }> = {
  COLD_OBSERVE: {
    fg: 'text-slate-300',
    bg: 'bg-slate-800/40',
    border: 'border-slate-600/40',
    label: 'COLD_OBSERVE',
  },
  WARM_WATCH: {
    fg: 'text-amber-300',
    bg: 'bg-amber-950/30',
    border: 'border-amber-900/40',
    label: 'WARM_WATCH',
  },
  FUSION_REVIEW_CANDIDATE: {
    fg: 'text-emerald-300',
    bg: 'bg-emerald-950/30',
    border: 'border-emerald-900/40',
    label: 'FUSION_REVIEW',
  },
  FISSION_MAP_ONLY: {
    fg: 'text-amber-400',
    bg: 'bg-amber-950/40',
    border: 'border-amber-900/50',
    label: 'FISSION_MAP',
  },
  HOT_CONTAINMENT_REQUIRED: {
    fg: 'text-red-300',
    bg: 'bg-red-950/40',
    border: 'border-red-900/60',
    label: 'HOT_CONTAINMENT',
  },
  WASTE_DECAY: {
    fg: 'text-slate-400',
    bg: 'bg-slate-900/40',
    border: 'border-slate-700/40',
    label: 'WASTE_DECAY',
  },
  ECHO_SUPPRESSED: {
    fg: 'text-fuchsia-300',
    bg: 'bg-fuchsia-950/30',
    border: 'border-fuchsia-900/50',
    label: 'ECHO_SUPPRESSED',
  },
  OPERATOR_CONTROL_RODS: {
    fg: 'text-red-200',
    bg: 'bg-red-950/60',
    border: 'border-red-800/70',
    label: 'CONTROL_RODS',
  },
  INSUFFICIENT_DATA: {
    fg: 'text-slate-500',
    bg: 'bg-slate-900/40',
    border: 'border-slate-700/40',
    label: 'UNKNOWN',
  },
};

function resolveStyle(state?: string) {
  if (!state) return STATE_STYLE.INSUFFICIENT_DATA;
  return STATE_STYLE[state] ?? STATE_STYLE.INSUFFICIENT_DATA;
}

export function ReactorBadge({ state, gallardoBlock, reactorAvailable, size = 'sm' }: Props) {
  const style = resolveStyle(state);
  const sizeCls = size === 'md' ? 'px-2 py-0.5 text-[11px]' : 'px-1.5 py-0.5 text-[10px]';
  const unavailable = reactorAvailable === false;

  return (
    <span className="inline-flex items-center gap-1">
      <span
        className={`${sizeCls} ${style.fg} ${style.bg} border ${style.border} rounded font-mono uppercase tracking-wider`}
        title="Signal Reactor diagnostic — advisory only. Does NOT authorise trades."
        data-testid="reactor-badge"
        data-reactor-state={style.label}
        data-execution-permission="false"
      >
        Reactor: {style.label}
      </span>
      {gallardoBlock && (
        <span
          className={`${sizeCls} text-red-100 bg-red-900/70 border border-red-700/80 rounded font-mono uppercase tracking-wider`}
          title="Gallardo block — operator should pause review. Does not close or execute any position."
          data-testid="gallardo-block-badge"
        >
          GALLARDO_BLOCK
        </span>
      )}
      {unavailable && (
        <span
          className={`${sizeCls} text-slate-500 bg-slate-900/40 border border-slate-700/40 rounded font-mono uppercase tracking-wider`}
          title="Reactor module unavailable — diagnostics not evaluated."
          data-testid="reactor-unavailable-badge"
        >
          REACTOR_UNAVAILABLE
        </span>
      )}
    </span>
  );
}
