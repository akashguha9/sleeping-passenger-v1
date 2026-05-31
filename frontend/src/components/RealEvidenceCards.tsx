'use client';

/**
 * Real Evidence Sprint — Phase 6 cockpit cards.
 *
 * Surfaces the live-path proof so an operator / investor / professor cannot
 * misunderstand the system's honesty:
 *   - Source Truth (fixture vs real canary, LIVE / DEGRADED / ZERO_FRESH_ROWS)
 *   - Live Decision Path (advisory class + probability flow)
 *   - Gate Vector (blocked-by reasons)
 *   - Capacity / Correlation Risk (UNKNOWN shown as risk)
 *   - Calibration Evidence (PREDICTIVE_CLAIM_LOCKED when the gate is locked)
 *   - Evidence Bundle (generated_at + status, never real-money)
 *
 * These cards introduce NO execution wording and NO predictive claim.  A MOCK /
 * degraded fallback is always labelled MOCK / DEGRADED and never LIVE.
 */

export type DataMode = 'LIVE' | 'REAL_CANARY' | 'FIXTURE_ONLY' | 'DEGRADED' | 'MOCK';

const SAFETY_BANNER = 'Evidence only. Human execution required. No broker action.';

function fmt(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number' && Number.isNaN(value)) return '—';
  return String(value);
}

function Row({
  label,
  value,
  valueClass,
  testid,
}: {
  label: string;
  value: string;
  valueClass?: string;
  testid?: string;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded bg-slate-900/40 border border-slate-700/30">
      <span className="text-xs text-slate-400">{label}</span>
      <span
        data-testid={testid}
        className={`text-xs font-bold text-white ${valueClass ?? ''}`}
      >
        {value}
      </span>
    </div>
  );
}

function ModeChip({ mode }: { mode: DataMode }) {
  const style: Record<DataMode, string> = {
    LIVE: 'text-emerald-300 border-emerald-800/50 bg-emerald-950/30',
    REAL_CANARY: 'text-emerald-300 border-emerald-800/50 bg-emerald-950/30',
    FIXTURE_ONLY: 'text-sky-300 border-sky-800/50 bg-sky-950/30',
    DEGRADED: 'text-amber-300 border-amber-800/50 bg-amber-950/30',
    MOCK: 'text-orange-300 border-orange-800/50 bg-orange-950/30',
  };
  return (
    <span
      data-testid="evidence-mode-chip"
      className={`text-[10px] font-mono px-2 py-0.5 rounded border ${style[mode]}`}
    >
      {mode}
    </span>
  );
}

function SafetyBanner() {
  return (
    <p data-testid="evidence-safety-banner" className="text-[11px] text-slate-500 mt-3">
      {SAFETY_BANNER}
    </p>
  );
}

function Shell({
  testid,
  title,
  mode,
  children,
}: {
  testid: string;
  title: string;
  mode: DataMode;
  children: React.ReactNode;
}) {
  return (
    <div
      data-testid={testid}
      data-advisory-only="true"
      data-execution-permission="false"
      data-data-mode={mode}
      className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4"
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-300">{title}</h2>
        <ModeChip mode={mode} />
      </div>
      <div className="space-y-2">{children}</div>
      <SafetyBanner />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 1. Source Truth Card
// --------------------------------------------------------------------------- //
export interface SourceTruthRow {
  source_name: string;
  canonical_signal_status: string;
  rows_added?: number | null;
  is_live_canonical?: boolean | null;
  canary_real?: boolean | null;
  mock_flag?: boolean | null;
  source_truth_score?: number | null;
}

export interface SourceTruthCardProps {
  perSource?: SourceTruthRow[];
  realSourceActivationCount?: number | null;
  fixtureSourceActivationCount?: number | null;
  cGlobal?: number | null;
  mode?: DataMode;
}

export function SourceTruthCard({
  perSource = [],
  realSourceActivationCount = 0,
  fixtureSourceActivationCount = 0,
  cGlobal = 0,
  mode = 'FIXTURE_ONLY',
}: SourceTruthCardProps) {
  return (
    <Shell testid="source-truth-card" title="Source Truth" mode={mode}>
      <Row
        label="real canary activation"
        value={fmt(realSourceActivationCount)}
        testid="source-real-count"
        valueClass={(realSourceActivationCount ?? 0) > 0 ? 'text-emerald-400' : 'text-slate-300'}
      />
      <Row
        label="fixture-backed activation"
        value={fmt(fixtureSourceActivationCount)}
        testid="source-fixture-count"
        valueClass="text-sky-300"
      />
      <Row label="C_global" value={fmt(cGlobal)} />
      <div className="mt-2 space-y-1">
        {perSource.map((s) => {
          const live = s.is_live_canonical === true;
          const real = s.canary_real === true;
          const label = s.mock_flag
            ? 'MOCK'
            : real && live
              ? 'REAL_CANARY'
              : live
                ? 'FIXTURE_ONLY'
                : s.canonical_signal_status;
          return (
            <Row
              key={s.source_name}
              label={s.source_name}
              testid={`source-row-${s.source_name}`}
              value={`${label} · rows=${fmt(s.rows_added)}`}
              valueClass={
                s.mock_flag
                  ? 'text-orange-300 font-mono'
                  : real && live
                    ? 'text-emerald-300 font-mono'
                    : live
                      ? 'text-sky-300 font-mono'
                      : 'text-amber-300 font-mono'
              }
            />
          );
        })}
      </div>
    </Shell>
  );
}

// --------------------------------------------------------------------------- //
// 2. Live Decision Path Card
// --------------------------------------------------------------------------- //
export interface LiveDecisionPathCardProps {
  finalAdvisoryClass?: string | null;
  admitted?: boolean | null;
  candidateActionable?: boolean | null;
  pBase?: number | null;
  pAfterMoltbook?: number | null;
  modelProbability?: number | null;
  sourceTruthScore?: number | null;
  mode?: DataMode;
}

export function LiveDecisionPathCard({
  finalAdvisoryClass = 'WAIT',
  admitted = false,
  candidateActionable = false,
  pBase = null,
  pAfterMoltbook = null,
  modelProbability = null,
  sourceTruthScore = null,
  mode = 'DEGRADED',
}: LiveDecisionPathCardProps) {
  return (
    <Shell testid="live-decision-path-card" title="Live Decision Path" mode={mode}>
      <Row
        label="final advisory class"
        value={fmt(finalAdvisoryClass)}
        testid="ldp-advisory-class"
        valueClass="font-mono text-slate-200"
      />
      <Row label="admitted" value={admitted ? 'true' : 'false'} />
      <Row
        label="actionable for human review"
        value={candidateActionable ? 'true' : 'false'}
        valueClass={`font-mono ${candidateActionable ? 'text-emerald-400' : 'text-slate-400'}`}
      />
      <Row label="p_base" value={fmt(pBase)} />
      <Row label="p_after_moltbook" value={fmt(pAfterMoltbook)} />
      <Row label="model_probability" value={fmt(modelProbability)} />
      <Row label="source_truth_score" value={fmt(sourceTruthScore)} />
    </Shell>
  );
}

// --------------------------------------------------------------------------- //
// 3. Gate Vector Card
// --------------------------------------------------------------------------- //
export interface GateVectorCardProps {
  gatePassed?: boolean | null;
  advisoryClass?: string | null;
  blockedBy?: string[];
  gateVector?: Record<string, boolean>;
  mode?: DataMode;
}

export function GateVectorCard({
  gatePassed = false,
  advisoryClass = 'WAIT',
  blockedBy = [],
  gateVector = {},
  mode = 'LIVE',
}: GateVectorCardProps) {
  return (
    <Shell testid="gate-vector-card" title="Gate Vector" mode={mode}>
      <Row
        label="gate passed"
        value={gatePassed ? 'true' : 'false'}
        valueClass={`font-mono ${gatePassed ? 'text-emerald-400' : 'text-red-400'}`}
      />
      <Row label="advisory class" value={fmt(advisoryClass)} valueClass="font-mono" />
      {blockedBy.length > 0 ? (
        <div
          data-testid="gate-blocked-by"
          className="text-xs text-red-300 px-3 py-2 rounded bg-red-950/30 border border-red-900/40"
        >
          <div className="text-slate-400 mb-1">blocked by:</div>
          <ul className="list-disc list-inside space-y-0.5">
            {blockedBy.map((r, i) => (
              <li key={i} className="font-mono text-[11px]">
                {r}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p data-testid="gate-no-blocks" className="text-xs text-slate-500">
          No blocking reasons recorded.
        </p>
      )}
      <div className="mt-1 grid grid-cols-2 gap-1">
        {Object.entries(gateVector).map(([k, v]) => (
          <Row key={k} label={k} value={v ? 'ok' : 'fail'}
               valueClass={`font-mono ${v ? 'text-emerald-400' : 'text-red-400'}`} />
        ))}
      </div>
    </Shell>
  );
}

// --------------------------------------------------------------------------- //
// 4. Capacity / Correlation Risk Card
// --------------------------------------------------------------------------- //
export interface CapacityCorrelationCardProps {
  capacityStatus?: string | null;
  portfolioCapacityOk?: boolean | null;
  correlationStatus?: string | null;
  maxPairwiseCorrelation?: number | null;
  sectorExposureAfter?: number | null;
  countryExposureAfter?: number | null;
  singleNameExposureAfter?: number | null;
  correlationBlockReason?: string | null;
  mode?: DataMode;
}

export function CapacityCorrelationCard({
  capacityStatus = 'CAPACITY_UNKNOWN',
  portfolioCapacityOk = false,
  correlationStatus = 'UNKNOWN',
  maxPairwiseCorrelation = null,
  sectorExposureAfter = null,
  countryExposureAfter = null,
  singleNameExposureAfter = null,
  correlationBlockReason = null,
  mode = 'DEGRADED',
}: CapacityCorrelationCardProps) {
  const corr = (correlationStatus ?? 'UNKNOWN').toUpperCase();
  const corrIsRisk = corr === 'UNKNOWN' || corr === 'BLOCKED';
  return (
    <Shell testid="capacity-correlation-card" title="Capacity / Correlation Risk" mode={mode}>
      <Row label="capacity status" value={fmt(capacityStatus)} valueClass="font-mono" />
      <Row
        label="portfolio capacity ok"
        value={portfolioCapacityOk ? 'true' : 'false'}
        valueClass={`font-mono ${portfolioCapacityOk ? 'text-emerald-400' : 'text-red-400'}`}
      />
      <Row
        label="correlation status"
        value={corr}
        testid="capacity-correlation-status"
        valueClass={`font-mono ${corrIsRisk ? 'text-amber-400' : 'text-emerald-400'}`}
      />
      <Row label="max |pairwise ρ|" value={fmt(maxPairwiseCorrelation)} />
      <Row label="sector exposure after" value={fmt(sectorExposureAfter)} />
      <Row label="country exposure after" value={fmt(countryExposureAfter)} />
      <Row label="single-name exposure after" value={fmt(singleNameExposureAfter)} />
      {corrIsRisk ? (
        <p data-testid="capacity-correlation-risk" className="text-xs text-amber-400 mt-1">
          Correlation risk is {corr}. {correlationBlockReason ?? 'Risk not cleared.'} A
          candidate is not promoted while portfolio risk is unresolved.
        </p>
      ) : null}
    </Shell>
  );
}

// --------------------------------------------------------------------------- //
// 5. Calibration Evidence Card
// --------------------------------------------------------------------------- //
export interface CalibrationEvidenceCardProps {
  nRealForward?: number | null;
  nHistoricalProxy?: number | null;
  brier?: number | null;
  ece?: number | null;
  logloss?: number | null;
  calibrationStatus?: string | null;
  predictiveClaimAllowed?: boolean | null;
  nMin?: number;
  mode?: DataMode;
}

export function CalibrationEvidenceCard({
  nRealForward = 0,
  nHistoricalProxy = 0,
  brier = null,
  ece = null,
  logloss = null,
  calibrationStatus = 'INSUFFICIENT_EVIDENCE',
  predictiveClaimAllowed = false,
  nMin = 200,
  mode = 'LIVE',
}: CalibrationEvidenceCardProps) {
  const status = (calibrationStatus ?? 'INSUFFICIENT_EVIDENCE').toUpperCase();
  const allowed = predictiveClaimAllowed === true;
  return (
    <Shell testid="calibration-evidence-card" title="Calibration Evidence" mode={mode}>
      <Row label="N_real_forward" value={fmt(nRealForward)} testid="cal-n-real-forward" />
      <Row label="N_historical_proxy (research only)" value={fmt(nHistoricalProxy)} />
      <Row label="Brier" value={fmt(brier)} />
      <Row label="ECE" value={fmt(ece)} />
      <Row label="LogLoss" value={fmt(logloss)} />
      <Row label="calibration_status" value={status} valueClass="font-mono text-amber-400" />
      <p data-testid="calibration-gate-formula" className="text-[11px] text-slate-500 mt-1 font-mono">
        CalibrationAllowed = I(N ≥ {nMin}) · I(Brier ≤ 0.25) · I(ECE ≤ 0.10)
      </p>
      {allowed ? (
        <Row
          label="predictive_claim_allowed"
          value="true"
          valueClass="font-mono text-emerald-400"
        />
      ) : (
        <p data-testid="predictive-claim-locked" className="text-xs text-amber-400 mt-1">
          PREDICTIVE_CLAIM_LOCKED — evidence is not sufficient. Scores are
          advisory-only and uncalibrated.
        </p>
      )}
    </Shell>
  );
}

// --------------------------------------------------------------------------- //
// 6. Evidence Bundle Card
// --------------------------------------------------------------------------- //
export interface EvidenceBundleCardProps {
  generatedAtUtc?: string | null;
  repoCommit?: string | null;
  calibrationStatus?: string | null;
  predictiveClaimAllowed?: boolean | null;
  realMoneyReady?: boolean | null;
  sEvidence?: number | null;
  mode?: DataMode;
}

export function EvidenceBundleCard({
  generatedAtUtc = null,
  repoCommit = null,
  calibrationStatus = 'INSUFFICIENT_EVIDENCE',
  predictiveClaimAllowed = false,
  realMoneyReady = false,
  sEvidence = null,
  mode = 'LIVE',
}: EvidenceBundleCardProps) {
  const allowed = predictiveClaimAllowed === true;
  return (
    <Shell testid="evidence-bundle-card" title="Evidence Bundle" mode={mode}>
      <Row
        label="generated (UTC)"
        value={fmt(generatedAtUtc)}
        testid="bundle-generated-at"
      />
      <Row label="repo commit" value={fmt(repoCommit)} valueClass="font-mono text-[11px]" />
      <Row
        label="status"
        value={(calibrationStatus ?? 'INSUFFICIENT_EVIDENCE').toUpperCase()}
        testid="bundle-status"
        valueClass="font-mono text-amber-400"
      />
      <Row label="S_evidence" value={fmt(sEvidence)} />
      <Row
        label="predictive_claim_allowed"
        value={allowed ? 'true' : 'false'}
        valueClass={`font-mono ${allowed ? 'text-emerald-400' : 'text-red-400'}`}
      />
      <Row
        label="real-money ready"
        value={realMoneyReady ? 'true' : 'false'}
        testid="bundle-real-money"
        valueClass={`font-mono ${realMoneyReady ? 'text-red-400' : 'text-emerald-400'}`}
      />
      {!realMoneyReady ? (
        <p data-testid="bundle-not-real-money" className="text-[11px] text-slate-500 mt-1">
          NOT real-money ready. No trading edge is claimed.
        </p>
      ) : null}
    </Shell>
  );
}

// --------------------------------------------------------------------------- //
// 7. Scoring Coverage Card
// --------------------------------------------------------------------------- //
export interface ScoringCoverageCardProps {
  nRealCanonicalRows?: number | null;
  nScoredRealRows?: number | null;
  scoringCoverage?: number | null;
  nCompleteScoreVectors?: number | null;
  scoreQualityCoverage?: number | null;
  nValidP?: number | null;
  sourcesScored?: string[] | null;
  scoreUnavailableReasons?: Record<string, number> | null;
  calibrationStatus?: string | null;
  predictiveClaimAllowed?: boolean | null;
  edgeClaimed?: boolean | null;
  realMoneyReady?: boolean | null;
  mode?: DataMode;
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(2)}%`;
}

export function ScoringCoverageCard({
  nRealCanonicalRows = 0,
  nScoredRealRows = 0,
  scoringCoverage = 0,
  nCompleteScoreVectors = 0,
  scoreQualityCoverage = 0,
  nValidP = 0,
  sourcesScored = [],
  scoreUnavailableReasons = {},
  calibrationStatus = 'INSUFFICIENT_EVIDENCE',
  predictiveClaimAllowed = false,
  edgeClaimed = false,
  realMoneyReady = false,
  mode = 'LIVE',
}: ScoringCoverageCardProps) {
  const allowed = predictiveClaimAllowed === true;
  const reasons = scoreUnavailableReasons ?? {};
  const missing = reasons['SCORE_VECTOR_MISSING'] ?? 0;
  const incomplete = reasons['SCORE_VECTOR_INCOMPLETE'] ?? 0;
  const status = (calibrationStatus ?? 'INSUFFICIENT_EVIDENCE').toUpperCase();
  return (
    <Shell testid="scoring-coverage-card" title="Real-Row Scoring Coverage" mode={mode}>
      <Row
        label="SCORED_REAL_ROWS"
        value={`${fmt(nScoredRealRows)} / ${fmt(nRealCanonicalRows)}`}
        testid="scoring-scored-real-rows"
        valueClass={(nScoredRealRows ?? 0) > 0 ? 'text-emerald-300 font-mono' : 'text-slate-300'}
      />
      <Row
        label="scoring_coverage"
        value={pct(scoringCoverage)}
        testid="scoring-coverage"
      />
      <Row
        label="complete vectors"
        value={fmt(nCompleteScoreVectors)}
        testid="scoring-complete-vectors"
      />
      <Row
        label="score_quality_coverage"
        value={pct(scoreQualityCoverage)}
        testid="scoring-quality-coverage"
      />
      <Row
        label="N_VALID_P"
        value={fmt(nValidP)}
        testid="scoring-n-valid-p"
        valueClass={(nValidP ?? 0) > 0 ? 'text-emerald-300 font-mono' : 'text-slate-300'}
      />
      <Row
        label="sources scored"
        value={(sourcesScored ?? []).length ? (sourcesScored ?? []).join(', ') : '—'}
        valueClass="font-mono text-[11px]"
      />
      <Row
        label="calibration_status"
        value={status}
        testid="scoring-calibration-status"
        valueClass="font-mono text-amber-400"
      />
      {incomplete > 0 ? (
        <p data-testid="scoring-vector-incomplete" className="text-xs text-amber-400 mt-1">
          SCORE_VECTOR_INCOMPLETE — {fmt(incomplete)} real rows lack a complete
          six-axis vector and record no probability.
        </p>
      ) : null}
      {missing > 0 ? (
        <p data-testid="scoring-vector-missing" className="text-xs text-amber-400 mt-1">
          SCORE_VECTOR_MISSING — {fmt(missing)} rows have no score vector yet.
        </p>
      ) : null}
      {allowed ? (
        <Row
          label="predictive_claim_allowed"
          value="true"
          valueClass="font-mono text-emerald-400"
        />
      ) : (
        <p data-testid="scoring-predictive-locked" className="text-xs text-amber-400 mt-1">
          PREDICTIVE_CLAIM_LOCKED · INSUFFICIENT_EVIDENCE — real rows are scored
          but the probabilities are advisory-only and uncalibrated.
        </p>
      )}
      <Row
        label="edge claimed"
        value={edgeClaimed ? 'true' : 'false'}
        testid="scoring-edge-claimed"
        valueClass={`font-mono ${edgeClaimed ? 'text-red-400' : 'text-emerald-400'}`}
      />
      <Row
        label="real-money ready"
        value={realMoneyReady ? 'true' : 'false'}
        testid="scoring-real-money"
        valueClass={`font-mono ${realMoneyReady ? 'text-red-400' : 'text-emerald-400'}`}
      />
    </Shell>
  );
}

export default SourceTruthCard;
