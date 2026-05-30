'use client';

/**
 * Objective 4 — Calibration / Uncertainty card.
 *
 * Makes the system's uncertainty UNAVOIDABLE for the operator: N_real,
 * n_valid_p, calibration_status, predictive_claim_allowed, and an explicit
 * "no predictive edge" warning are always rendered.  Safe defaults reflect the
 * repo's truthful current state (N_real = 0, INSUFFICIENT_EVIDENCE) so a
 * green-looking dashboard can never hide the fact that nothing is calibrated.
 *
 * This card introduces NO execution wording and NO predictive claim.
 */

export interface CalibrationUncertaintyProps {
  nReal?: number | null;
  nValidP?: number | null;
  calibrationStatus?: string | null;
  predictiveClaimAllowed?: boolean | null;
  brier?: number | null;
  ece?: number | null;
  nMin?: number;
  lastUpdatedUtc?: string | null;
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return String(value);
}

export function CalibrationUncertaintyCard({
  nReal = 0,
  nValidP = 0,
  calibrationStatus = 'INSUFFICIENT_EVIDENCE',
  predictiveClaimAllowed = false,
  brier = null,
  ece = null,
  nMin = 200,
  lastUpdatedUtc = null,
}: CalibrationUncertaintyProps) {
  const status = (calibrationStatus ?? 'INSUFFICIENT_EVIDENCE').toUpperCase();
  const claimAllowed = predictiveClaimAllowed === true;
  const statusColor =
    status === 'MEASURED' ? 'text-emerald-400' : 'text-amber-400';

  return (
    <div
      data-testid="calibration-uncertainty-card"
      className="bg-slate-800/60 border border-amber-800/50 rounded-lg p-4"
    >
      <h2 className="text-sm font-semibold text-slate-300 mb-3">
        Calibration &amp; Uncertainty
      </h2>

      <div className="space-y-2">
        <Row label="N_real" value={fmt(nReal)} />
        <Row label="n_valid_p" value={fmt(nValidP)} />
        <Row label="N required" value={fmt(nMin)} />
        <Row
          label="calibration_status"
          value={status}
          valueClass={`font-mono ${statusColor}`}
        />
        <Row
          label="predictive_claim_allowed"
          value={claimAllowed ? 'true' : 'false'}
          valueClass={`font-mono ${claimAllowed ? 'text-emerald-400' : 'text-red-400'}`}
        />
        <Row label="Brier" value={fmt(brier)} />
        <Row label="ECE" value={fmt(ece)} />
        {lastUpdatedUtc ? (
          <Row label="last calibration" value={lastUpdatedUtc} />
        ) : null}
      </div>

      <p
        data-testid="calibration-gate-formula"
        className="text-[11px] text-slate-500 mt-3 font-mono"
      >
        CalibrationAllowed = I(N ≥ {nMin}) · I(Brier ≤ 0.25) · I(ECE ≤ 0.10)
      </p>

      {!claimAllowed ? (
        <p
          data-testid="calibration-warning"
          className="text-xs text-amber-400 mt-2"
        >
          No predictive edge claim is allowed until the calibration gate passes.
          Scores are advisory-only and uncalibrated.
        </p>
      ) : null}
    </div>
  );
}

function Row({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded bg-slate-900/40 border border-slate-700/30">
      <span className="text-xs text-slate-400">{label}</span>
      <span className={`text-xs font-bold text-white ${valueClass ?? ''}`}>
        {value}
      </span>
    </div>
  );
}

export default CalibrationUncertaintyCard;
