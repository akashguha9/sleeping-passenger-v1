'use client';

import type { ReactorDiagnostics } from '@/types';
import { ReactorBadge } from './ReactorBadge';

/**
 * Expanded diagnostics panel for the signal detail page.
 *
 * Shows all eight reactor advisory fields plus the canonical advisory-only
 * / human-execution-required copy.  Missing fields degrade to "n/a" or
 * "unknown" — the panel never invents positive values, and never claims
 * actionable, executable, or broker-ready status.
 */
interface Props {
  diagnostics: ReactorDiagnostics;
}

function fmtScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'n/a';
  if (typeof value !== 'number' || Number.isNaN(value)) return 'n/a';
  return value.toFixed(3);
}

function fmtString(value: string | undefined): string {
  if (!value) return 'unknown';
  return value;
}

function intensityClass(value: number | null | undefined, invert = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-slate-500';
  if (invert) {
    if (value >= 0.7) return 'text-red-400';
    if (value >= 0.4) return 'text-amber-400';
    return 'text-emerald-400';
  }
  if (value >= 0.7) return 'text-emerald-400';
  if (value >= 0.4) return 'text-amber-400';
  return 'text-slate-400';
}

export function ReactorDiagnosticsPanel({ diagnostics }: Props) {
  const {
    reactor_state,
    decision_grade_energy,
    echo_risk_score,
    meltdown_risk_score,
    fusion_validity,
    fission_branch_clarity,
    operator_heat_score,
    gallardo_block,
    reactor_recommendation,
    reactor_available,
  } = diagnostics;

  return (
    <div
      className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-4 space-y-3"
      data-testid="reactor-diagnostics-panel"
      data-advisory-only="true"
      data-execution-permission="false"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Signal Reactor Diagnostics</h3>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Advisory diagnostic snapshot. Reading this panel is not permission to trade.
          </p>
        </div>
        <ReactorBadge
          state={reactor_state}
          gallardoBlock={gallardo_block}
          reactorAvailable={reactor_available}
          size="md"
        />
      </div>

      {gallardo_block && (
        <div
          className="text-xs rounded px-3 py-2 border border-red-700/70 bg-red-950/40 text-red-200"
          data-testid="gallardo-block-warning"
        >
          <span className="font-semibold">GALLARDO_BLOCK active.</span> Operator should pause
          review of this signal. This does not close, sell, or otherwise execute any position.
          Human action required.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <DiagCell
          label="Reactor state"
          value={fmtString(reactor_state)}
          mono
          testId="diag-reactor-state"
        />
        <DiagCell
          label="Recommendation"
          value={fmtString(reactor_recommendation)}
          mono
          testId="diag-recommendation"
        />
        <DiagCell
          label="Decision-grade energy"
          value={fmtScore(decision_grade_energy)}
          valueClass={intensityClass(decision_grade_energy)}
          testId="diag-decision-grade-energy"
        />
        <DiagCell
          label="Echo risk"
          value={fmtScore(echo_risk_score)}
          valueClass={intensityClass(echo_risk_score, /* invert */ true)}
          testId="diag-echo-risk"
        />
        <DiagCell
          label="Meltdown risk"
          value={fmtScore(meltdown_risk_score)}
          valueClass={intensityClass(meltdown_risk_score, /* invert */ true)}
          testId="diag-meltdown-risk"
        />
        <DiagCell
          label="Operator heat"
          value={fmtScore(operator_heat_score)}
          valueClass={intensityClass(operator_heat_score, /* invert */ true)}
          testId="diag-operator-heat"
        />
        <DiagCell
          label="Fusion validity"
          value={fmtString(fusion_validity)}
          mono
          testId="diag-fusion-validity"
        />
        <DiagCell
          label="Fission branch clarity"
          value={fmtScore(fission_branch_clarity)}
          valueClass={intensityClass(fission_branch_clarity)}
          testId="diag-fission-clarity"
        />
      </div>

      <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500 flex flex-wrap gap-x-3 gap-y-1">
        <span data-testid="copy-advisory-only">ADVISORY_ONLY</span>
        <span data-testid="copy-human-execution-required">HUMAN_EXECUTION_REQUIRED</span>
        <span>BROKER_API: not connected</span>
        <span>AI_EXECUTIONS: 0</span>
        <span data-testid="copy-no-authorisation">
          Reactor diagnostics do not authorise trades.
        </span>
      </div>
    </div>
  );
}

function DiagCell({
  label,
  value,
  valueClass,
  mono,
  testId,
}: {
  label: string;
  value: string;
  valueClass?: string;
  mono?: boolean;
  testId?: string;
}) {
  return (
    <div data-testid={testId}>
      <div className="text-slate-500 uppercase tracking-wider text-[10px]">{label}</div>
      <div
        className={`mt-0.5 text-sm ${mono ? 'font-mono' : ''} ${valueClass ?? 'text-slate-200'}`}
      >
        {value}
      </div>
    </div>
  );
}
