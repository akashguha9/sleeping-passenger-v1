'use client';

/**
 * Kronos Price-Path Evidence card — advisory-only, read-only.
 *
 * STATUS: NOT MOUNTED YET. This component is implemented and unit-tested
 * but is intentionally NOT imported by any page/route. Kronos evidence is
 * not yet surfaced through the frontend API, so mounting it would display
 * nothing. It will be wired into the advisory/signal page once the
 * KronosAdapter evidence is exposed by the backend. Until then it has no
 * runtime/user-facing effect.
 *
 * Renders the compact Kronos technical-witness read for a candidate
 * signal.  Kronos is EVIDENCE, never authority: this card only ever
 * surfaces evidence fields + an advisory classification, plus a banner
 * making the no-execution contract explicit.  It uses safe vocabulary
 * only (evidence / advisory / support / contradict / unstable /
 * watchlist / human review / locked) and never renders any
 * execution-instruction wording.
 */

export type KronosStatus =
  | 'SUPPORTIVE'
  | 'CONTRADICTORY'
  | 'UNSTABLE'
  | 'NOISY'
  | 'INSUFFICIENT_DATA'
  | 'DISABLED'
  | 'ERROR_SAFE';

export interface KronosEvidenceView {
  status: KronosStatus | string;
  forecast_return_pct?: number | null;
  forecast_volatility_pct?: number | null;
  downside_path_risk?: number | null;
  directional_agreement?: boolean | null;
  confidence_calibrated?: number | null;
  final_score_delta?: number | null;
  proof_status?: string | null;
  reason?: string | null;
}

interface Props {
  /** The Kronos evidence read, or null/undefined when no Kronos data. */
  evidence?: KronosEvidenceView | null;
}

const STATUS_STYLE: Record<string, { fg: string; bg: string; border: string; label: string }> = {
  SUPPORTIVE: { fg: 'text-emerald-300', bg: 'bg-emerald-950/30', border: 'border-emerald-900/40', label: 'Supportive' },
  CONTRADICTORY: { fg: 'text-rose-200', bg: 'bg-rose-950/40', border: 'border-rose-800/50', label: 'Contradictory' },
  UNSTABLE: { fg: 'text-orange-300', bg: 'bg-orange-950/40', border: 'border-orange-900/50', label: 'Unstable' },
  NOISY: { fg: 'text-amber-300', bg: 'bg-amber-950/30', border: 'border-amber-900/40', label: 'Noisy' },
  INSUFFICIENT_DATA: { fg: 'text-slate-400', bg: 'bg-slate-900/40', border: 'border-slate-700/40', label: 'Insufficient data' },
  DISABLED: { fg: 'text-slate-400', bg: 'bg-slate-900/40', border: 'border-slate-700/40', label: 'Disabled' },
  ERROR_SAFE: { fg: 'text-slate-400', bg: 'bg-slate-900/50', border: 'border-slate-700/50', label: 'Error (safe)' },
};

const FALLBACK_STYLE = STATUS_STYLE.NOISY;

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

function fmtDelta(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`;
}

function fmtAgreement(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value ? 'Agrees with thesis' : 'Does not agree';
}

export function KronosEvidenceCard({ evidence }: Props) {
  // No-data / disabled-with-no-payload state.
  if (!evidence) {
    return (
      <div
        className="rounded border border-slate-700/40 bg-slate-900/40 p-3 text-xs"
        data-testid="kronos-evidence-card"
        data-kronos-status="unavailable"
        data-advisory-only="true"
        data-execution-permission="false"
      >
        <div className="font-mono text-[11px] uppercase tracking-wider text-slate-300">
          Kronos Price-Path Evidence
        </div>
        <div className="mt-2 text-slate-400" data-testid="kronos-no-data">
          Kronos evidence unavailable / disabled. No decision impact.
        </div>
      </div>
    );
  }

  const status = String(evidence.status || '').toUpperCase();
  const style = STATUS_STYLE[status] ?? FALLBACK_STYLE;

  return (
    <div
      className="rounded border border-slate-700/50 bg-slate-900/50 p-3 text-xs"
      data-testid="kronos-evidence-card"
      data-kronos-status={status}
      data-advisory-only="true"
      data-human-execution-required="true"
      data-execution-gate="LOCKED"
      data-broker-api-called="false"
      data-execution-permission="false"
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] uppercase tracking-wider text-slate-300">
          Kronos Price-Path Evidence
        </span>
        <span
          className={`px-1.5 py-0.5 text-[10px] ${style.fg} ${style.bg} border ${style.border} rounded font-mono uppercase tracking-wider`}
          data-testid="kronos-status-chip"
        >
          {style.label}
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-300">
        <dt className="text-slate-500">Forecast return</dt>
        <dd className="text-right font-mono" data-testid="kronos-forecast-return">
          {fmtPct(evidence.forecast_return_pct)}
        </dd>

        <dt className="text-slate-500">Forecast volatility</dt>
        <dd className="text-right font-mono" data-testid="kronos-forecast-volatility">
          {fmtPct(evidence.forecast_volatility_pct)}
        </dd>

        <dt className="text-slate-500">Downside path risk</dt>
        <dd className="text-right font-mono" data-testid="kronos-downside-risk">
          {fmtNum(evidence.downside_path_risk)}
        </dd>

        <dt className="text-slate-500">Directional</dt>
        <dd className="text-right font-mono" data-testid="kronos-directional">
          {fmtAgreement(evidence.directional_agreement)}
        </dd>

        <dt className="text-slate-500">Confidence (calibrated)</dt>
        <dd className="text-right font-mono" data-testid="kronos-confidence">
          {fmtNum(evidence.confidence_calibrated)}
        </dd>

        <dt className="text-slate-500">Score delta</dt>
        <dd className="text-right font-mono" data-testid="kronos-score-delta">
          {fmtDelta(evidence.final_score_delta)}
        </dd>

        <dt className="text-slate-500">Proof</dt>
        <dd className="text-right font-mono text-slate-400" data-testid="kronos-proof">
          {evidence.proof_status || '—'}
        </dd>
      </dl>

      {evidence.reason ? (
        <p className="mt-2 text-[10px] leading-snug text-slate-400" data-testid="kronos-reason">
          {evidence.reason}
        </p>
      ) : null}

      <p
        className="mt-2 border-t border-slate-700/40 pt-2 text-[10px] text-slate-500"
        data-testid="kronos-safety-banner"
      >
        Evidence only. Human execution required. No broker action.
      </p>
    </div>
  );
}

export default KronosEvidenceCard;
