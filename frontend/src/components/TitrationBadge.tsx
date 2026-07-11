'use client';

import type { TitrationState } from '@/types';

/**
 * Compact, advisory-only badge showing the Market Titration state for an
 * inbox card.
 *
 * The Market Titration Engine is a diagnostic layer over evidence
 * accumulation vs decay (see docs/MARKET_TITRATION_ENGINE.md) — it never
 * authorises trades, never places orders, never connects to a broker.
 * Colors stay conservative on purpose: PRIMED reads as "review closely",
 * never as "go".
 */
interface Props {
  state?: TitrationState | string;
  preAlphaGap?: number | null;
  size?: 'sm' | 'md';
}

const STATE_STYLE: Record<string, { fg: string; bg: string; border: string; label: string }> = {
  INERT: {
    fg: 'text-slate-400',
    bg: 'bg-slate-900/40',
    border: 'border-slate-700/40',
    label: 'INERT',
  },
  LOADING: {
    fg: 'text-sky-300',
    bg: 'bg-sky-950/30',
    border: 'border-sky-900/40',
    label: 'LOADING',
  },
  PRE_ALPHA_WATCH: {
    fg: 'text-amber-300',
    bg: 'bg-amber-950/30',
    border: 'border-amber-900/40',
    label: 'PRE_ALPHA_WATCH',
  },
  PRIMED: {
    fg: 'text-emerald-300',
    bg: 'bg-emerald-950/30',
    border: 'border-emerald-900/40',
    label: 'PRIMED',
  },
  CROWDED: {
    fg: 'text-violet-300',
    bg: 'bg-violet-950/30',
    border: 'border-violet-900/40',
    label: 'CROWDED',
  },
  EXHAUSTING: {
    fg: 'text-orange-300',
    bg: 'bg-orange-950/30',
    border: 'border-orange-900/40',
    label: 'EXHAUSTING',
  },
  FALSE_TRANSITION_RISK: {
    fg: 'text-red-300',
    bg: 'bg-red-950/40',
    border: 'border-red-900/60',
    label: 'FALSE_TRANSITION',
  },
  NO_EDGE: {
    fg: 'text-slate-300',
    bg: 'bg-slate-800/40',
    border: 'border-slate-600/40',
    label: 'NO_EDGE',
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

export function TitrationBadge({ state, preAlphaGap, size = 'sm' }: Props) {
  const style = resolveStyle(state);
  const sizeCls = size === 'md' ? 'px-2 py-0.5 text-[11px]' : 'px-1.5 py-0.5 text-[10px]';
  const gap =
    typeof preAlphaGap === 'number' && Number.isFinite(preAlphaGap)
      ? ` ${preAlphaGap >= 0 ? '+' : ''}${preAlphaGap.toFixed(2)}`
      : '';

  return (
    <span
      className={`${sizeCls} ${style.fg} ${style.bg} border ${style.border} rounded font-mono uppercase tracking-wider`}
      title="Market Titration diagnostic (evidence accumulation vs decay; readiness vs recognition) — advisory only, heuristic score, NOT a probability. Does NOT authorise trades."
      data-testid="titration-badge"
      data-titration-state={style.label}
      data-execution-permission="false"
    >
      Titration: {style.label}
      {gap}
    </span>
  );
}
