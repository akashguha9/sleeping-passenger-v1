'use client';

/**
 * External Evidence Reliability card — advisory-only, read-only.
 *
 * STATUS: NOT MOUNTED YET. This component is implemented and unit-tested but
 * is intentionally NOT imported by any page/route. The daily external-evidence
 * calibration bundle is not yet surfaced through the frontend API (external
 * adapters are disabled by default, so a mounted card would render the disabled
 * state). It will be wired into the advisory/signal page once the daily payload
 * exposes `external_evidence` + `external_evidence_calibration`. Until then it
 * has no runtime/user-facing effect.
 *
 * Shows the operator HOW MUCH historical evidence sits behind each external
 * source, and the paper-only calibrated weight learned from closed outcomes.
 * Calibrated weight is a PAPER-ONLY prior: it nudges the advisory score-delta
 * for analysis only. It never sizes real money, never places an order, and can
 * never override a DIABLO / CHAOS / safety veto. Safe vocabulary only.
 */

export interface SourceReliabilityView {
  source_name: string;
  evidence_type?: string | null;
  route_decision?: string | null;
  calibration_confidence_band?: string | null;
  calibration_sample_count?: number | null;
  calibration_help_rate?: number | null;
  calibration_harm_rate?: number | null;
  calibration_false_confidence_rate?: number | null;
  calibration_advisory_weight?: number | null;
  calibration_effective_weight?: number | null;
  calibration_reliability_label?: string | null;
  calibration_operator_message?: string | null;
}

export interface ExternalEvidenceCalibrationView {
  enabled?: boolean | null;
  applied_to_score_delta?: boolean | null;
  mode?: string | null;
  calibrated_items_count?: number | null;
  cold_start_items_count?: number | null;
  mature_items_count?: number | null;
  real_money_sizing_impact?: string | null;
}

export interface PaperOutcomeReadinessView {
  readiness_label?: string | null;
  closed_paper_outcomes_count?: number | null;
  target_minimum?: number | null;
  target_preferred?: number | null;
  calibration_readiness_score?: number | null;
  next_required_action?: string | null;
  // Kanté Closed-Outcome Corpus sprint — 50/100 progress + named stage.
  closed_outcome_progress_50?: number | null;
  closed_outcome_progress_100?: number | null;
  calibration_stage?: string | null;
}

export interface CalibrationCorpusQualityView {
  corpus_quality_score?: number | null;
  corpus_label?: string | null;
  top_blocker?: string | null;
  operator_next_action?: string | null;
  n_closed?: number | null;
}

export interface ExternalEvidenceReliabilityView {
  external_evidence_status?: string | null;
  external_evidence_enabled?: boolean | null;
  external_evidence_decision_impact?: string | null;
  external_evidence_accepted_count?: number | null;
  external_evidence_score_delta_raw_uncalibrated?: number | null;
  external_evidence_score_delta_paper_calibrated?: number | null;
  external_evidence_calibration?: ExternalEvidenceCalibrationView | null;
  external_evidence_items?: SourceReliabilityView[] | null;
  // Kanté Ceiling Push II — paper-outcome readiness + corpus quality clarity.
  paper_outcome_readiness?: PaperOutcomeReadinessView | null;
  calibration_corpus_quality?: CalibrationCorpusQualityView | null;
  live_verified_blockers?: string[] | null;
  real_money_readiness_ceiling?: number | string | null;
  // Kanté Closed-Outcome Corpus sprint — top missing fields + next actions.
  top_missing_fields?: string[] | null;
  next_operator_actions?: string[] | null;
  // Kanté Outcome Corpus Hardening sprint — staging / review-queue counts.
  staged_outcomes_count?: number | null;
  calibration_ready_count?: number | null;
  review_required_count?: number | null;
  rejected_outcomes_count?: number | null;
  duplicate_skipped_count?: number | null;
  auto_link_count?: number | null;
  review_link_count?: number | null;
  no_link_count?: number | null;
  top_outcome_blockers?: string[] | null;
}

interface Props {
  /** The advisory external-evidence bundle, or null/undefined when none. */
  bundle?: ExternalEvidenceReliabilityView | null;
}

const LABEL_STYLE: Record<string, { fg: string; bg: string; border: string; label: string }> = {
  COLD_START: { fg: 'text-slate-300', bg: 'bg-slate-900/40', border: 'border-slate-700/40', label: 'Cold start' },
  EARLY_SAMPLE: { fg: 'text-amber-300', bg: 'bg-amber-950/30', border: 'border-amber-900/40', label: 'Early sample' },
  PROVISIONAL: { fg: 'text-sky-300', bg: 'bg-sky-950/30', border: 'border-sky-900/40', label: 'Provisional' },
  MATURE_PAPER_ONLY: { fg: 'text-emerald-300', bg: 'bg-emerald-950/30', border: 'border-emerald-900/40', label: 'Mature (paper-only)' },
};
const FALLBACK_LABEL = LABEL_STYLE.COLD_START;

const DISABLED_STATES = new Set(['DISABLED', 'CONFIG_MISSING', 'NO_ENABLED_ADAPTERS', '']);

function fmtRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(0)}%`;
}

function fmtWeight(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(3);
}

function fmtDelta(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`;
}

function statusLabel(status: string, calApplied: boolean): string {
  if (DISABLED_STATES.has(status)) return 'Disabled';
  if (status === 'ERROR_SAFE') return 'Error-safe';
  if (calApplied) return 'Paper-calibrated';
  return 'Evidence-only';
}

function fmtScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(3);
}

/**
 * Paper-outcome readiness + corpus-quality clarity block.
 *
 * Rendered in BOTH the disabled and active card states because calibration
 * readiness is meaningful even while external adapters are disabled. It states
 * the hard truth: real-money readiness is LOW BY DESIGN, and calibration cannot
 * leave cold-start until enough closed paper outcomes exist. Read-only; no CTA.
 */
function PaperOutcomeReadinessSection({
  bundle,
}: {
  bundle?: ExternalEvidenceReliabilityView | null;
}) {
  const readiness = bundle?.paper_outcome_readiness ?? null;
  const corpus = bundle?.calibration_corpus_quality ?? null;
  const blockers = bundle?.live_verified_blockers ?? null;
  const topMissingFields = bundle?.top_missing_fields ?? null;
  const nextActions = bundle?.next_operator_actions ?? null;

  const closed = readiness?.closed_paper_outcomes_count ?? null;
  const targetMin = readiness?.target_minimum ?? 50;
  const targetPref = readiness?.target_preferred ?? 100;
  const stage = readiness?.calibration_stage ?? readiness?.readiness_label ?? 'COLD_START';
  const realMoneyCeiling = bundle?.real_money_readiness_ceiling ?? 'LOW BY DESIGN';

  const stagedCount = bundle?.staged_outcomes_count ?? 0;
  const calibrationReady = bundle?.calibration_ready_count ?? 0;
  const reviewRequired = bundle?.review_required_count ?? 0;
  const rejectedCount = bundle?.rejected_outcomes_count ?? 0;
  const duplicateSkipped = bundle?.duplicate_skipped_count ?? 0;
  const autoLink = bundle?.auto_link_count ?? 0;
  const reviewLink = bundle?.review_link_count ?? 0;
  const noLink = bundle?.no_link_count ?? 0;
  const outcomeBlockers = bundle?.top_outcome_blockers ?? null;

  return (
    <div
      className="mt-3 border-t border-slate-700/40 pt-2"
      data-testid="reliability-paper-outcome-readiness"
    >
      <div className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
        Paper-Outcome Readiness
      </div>
      <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-300">
        <dt className="text-slate-500">Calibration stage</dt>
        <dd className="text-right font-mono" data-testid="reliability-paper-outcome-label">
          {stage}
        </dd>

        <dt className="text-slate-500">Closed outcomes</dt>
        <dd className="text-right font-mono" data-testid="reliability-paper-outcome-progress">
          {closed ?? 0} / {targetMin} · {closed ?? 0} / {targetPref}
        </dd>

        <dt className="text-slate-500">Minimum / preferred</dt>
        <dd className="text-right font-mono" data-testid="reliability-paper-outcome-targets">
          {closed ?? 0} / {targetMin} minimum · {closed ?? 0} / {targetPref} preferred
        </dd>

        <dt className="text-slate-500">Corpus quality</dt>
        <dd className="text-right font-mono" data-testid="reliability-corpus-quality">
          {fmtScore(corpus?.corpus_quality_score)} · {corpus?.corpus_label ?? 'EMPTY'}
        </dd>

        <dt className="text-slate-500">Top blocker</dt>
        <dd className="text-right font-mono" data-testid="reliability-top-blocker">
          {corpus?.top_blocker ?? '—'}
        </dd>

        <dt className="text-slate-500">Real-money readiness</dt>
        <dd
          className="text-right font-mono text-rose-200"
          data-testid="reliability-real-money-readiness"
        >
          {typeof realMoneyCeiling === 'number'
            ? `${realMoneyCeiling} / 10 (low by design)`
            : realMoneyCeiling}
        </dd>
      </dl>

      <p
        className="mt-1 text-[10px] leading-snug text-rose-200/80"
        data-testid="reliability-real-money-low-by-design"
      >
        Real-money readiness remains low by design.
      </p>

      <div
        className="mt-2 border-t border-slate-800/60 pt-2"
        data-testid="reliability-review-queue"
      >
        <div className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
          Outcome Review Queue
        </div>
        <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-300">
          <dt className="text-slate-500">Staged outcomes</dt>
          <dd className="text-right font-mono" data-testid="reliability-staged-count">
            {stagedCount}
          </dd>

          <dt className="text-slate-500">Calibration-ready</dt>
          <dd className="text-right font-mono" data-testid="reliability-calibration-ready-count">
            {calibrationReady}
          </dd>

          <dt className="text-slate-500">Review required</dt>
          <dd className="text-right font-mono" data-testid="reliability-review-required-count">
            {reviewRequired}
          </dd>

          <dt className="text-slate-500">Rejected</dt>
          <dd className="text-right font-mono" data-testid="reliability-rejected-count">
            {rejectedCount}
          </dd>

          <dt className="text-slate-500">Duplicate skipped</dt>
          <dd className="text-right font-mono" data-testid="reliability-duplicate-skipped-count">
            {duplicateSkipped}
          </dd>

          <dt className="text-slate-500">Auto / Review / No-link</dt>
          <dd className="text-right font-mono" data-testid="reliability-link-counts">
            {autoLink} / {reviewLink} / {noLink}
          </dd>
        </dl>

        {outcomeBlockers && outcomeBlockers.length > 0 ? (
          <p
            className="mt-1 text-[10px] leading-snug text-slate-400"
            data-testid="reliability-top-outcome-blockers"
          >
            Top blockers: {outcomeBlockers.slice(0, 5).join(', ')}
          </p>
        ) : null}
      </div>

      {topMissingFields && topMissingFields.length > 0 ? (
        <p
          className="mt-1 text-[10px] leading-snug text-slate-400"
          data-testid="reliability-top-missing-fields"
        >
          Top missing fields: {topMissingFields.join(', ')}
        </p>
      ) : null}

      {nextActions && nextActions.length > 0 ? (
        <ol
          className="mt-1 list-decimal pl-4 text-[10px] leading-snug text-slate-400"
          data-testid="reliability-next-operator-actions"
        >
          {nextActions.slice(0, 5).map((action, idx) => (
            <li key={idx} data-testid="reliability-next-operator-action">
              {action}
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-1 text-[10px] leading-snug text-slate-400" data-testid="reliability-next-action">
          Next: {readiness?.next_required_action || corpus?.operator_next_action || 'Collect closed paper outcomes.'}
        </p>
      )}

      {blockers && blockers.length > 0 ? (
        <p
          className="mt-1 text-[10px] leading-snug text-slate-500"
          data-testid="reliability-live-verified-blockers"
        >
          LIVE_VERIFIED blockers: {blockers.join(', ')}
        </p>
      ) : null}

      <p className="mt-1 text-[10px] leading-snug text-amber-200/80" data-testid="reliability-cold-start-message">
        Calibration cannot leave cold-start until enough closed paper outcomes exist.
      </p>
    </div>
  );
}

export function ExternalEvidenceReliabilityCard({ bundle }: Props) {
  const status = String(bundle?.external_evidence_status || '').toUpperCase();
  const calibration = bundle?.external_evidence_calibration ?? null;
  const calApplied = Boolean(calibration?.enabled && calibration?.applied_to_score_delta);

  // No bundle, or disabled / unavailable → explicit no-decision-impact state.
  if (!bundle || DISABLED_STATES.has(status)) {
    return (
      <div
        className="rounded border border-slate-700/40 bg-slate-900/40 p-3 text-xs"
        data-testid="external-evidence-reliability-card"
        data-reliability-state="disabled"
        data-advisory-only="true"
        data-execution-permission="false"
        data-real-money-sizing="PROHIBITED"
      >
        <div className="font-mono text-[11px] uppercase tracking-wider text-slate-300">
          External Evidence Reliability
        </div>
        <div className="mt-2 text-slate-400" data-testid="reliability-disabled">
          External evidence disabled or unavailable. No decision impact.
        </div>
        <PaperOutcomeReadinessSection bundle={bundle} />
      </div>
    );
  }

  const items = bundle.external_evidence_items ?? [];
  const realMoney = calibration?.real_money_sizing_impact || 'PROHIBITED';

  return (
    <div
      className="rounded border border-slate-700/50 bg-slate-900/50 p-3 text-xs"
      data-testid="external-evidence-reliability-card"
      data-reliability-state={calApplied ? 'paper-calibrated' : 'evidence-only'}
      data-advisory-only="true"
      data-human-execution-required="true"
      data-execution-gate="LOCKED"
      data-broker-api-called="false"
      data-execution-permission="false"
      data-real-money-sizing={realMoney}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] uppercase tracking-wider text-slate-300">
          External Evidence Reliability
        </span>
        <span
          className="px-1.5 py-0.5 text-[10px] text-slate-300 bg-slate-800/60 border border-slate-700/50 rounded font-mono uppercase tracking-wider"
          data-testid="reliability-status-chip"
        >
          {statusLabel(status, calApplied)}
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-300">
        <dt className="text-slate-500">Decision impact</dt>
        <dd className="text-right font-mono" data-testid="reliability-decision-impact">
          {bundle.external_evidence_decision_impact || 'NONE'}
        </dd>

        <dt className="text-slate-500">Real-money sizing</dt>
        <dd className="text-right font-mono text-rose-200" data-testid="reliability-real-money">
          {realMoney}
        </dd>

        <dt className="text-slate-500">Evidence items</dt>
        <dd className="text-right font-mono" data-testid="reliability-evidence-count">
          {bundle.external_evidence_accepted_count ?? 0}
        </dd>

        <dt className="text-slate-500">Calibrated items</dt>
        <dd className="text-right font-mono" data-testid="reliability-calibrated-count">
          {calibration?.calibrated_items_count ?? 0}
        </dd>

        <dt className="text-slate-500">Cold-start items</dt>
        <dd className="text-right font-mono" data-testid="reliability-cold-start-count">
          {calibration?.cold_start_items_count ?? 0}
        </dd>

        <dt className="text-slate-500">Mature paper-only items</dt>
        <dd className="text-right font-mono" data-testid="reliability-mature-count">
          {calibration?.mature_items_count ?? 0}
        </dd>

        <dt className="text-slate-500">Score delta raw</dt>
        <dd className="text-right font-mono" data-testid="reliability-delta-raw">
          {fmtDelta(bundle.external_evidence_score_delta_raw_uncalibrated)}
        </dd>

        <dt className="text-slate-500">Score delta paper-calibrated</dt>
        <dd className="text-right font-mono" data-testid="reliability-delta-calibrated">
          {fmtDelta(bundle.external_evidence_score_delta_paper_calibrated)}
        </dd>

        <dt className="text-slate-500">Max boost</dt>
        <dd className="text-right font-mono">+0.50</dd>

        <dt className="text-slate-500">Max penalty</dt>
        <dd className="text-right font-mono">-1.00</dd>
      </dl>

      {!calApplied ? (
        <p className="mt-2 text-[10px] text-slate-400" data-testid="reliability-calibration-unavailable">
          Calibration unavailable. Conservative paper-only default applied.
        </p>
      ) : null}

      <ul className="mt-3 space-y-2" data-testid="reliability-source-list">
        {items.map((src, idx) => {
          const labelKey = String(src.calibration_reliability_label || '').toUpperCase();
          const style = LABEL_STYLE[labelKey] ?? FALLBACK_LABEL;
          return (
            <li
              key={`${src.source_name}-${idx}`}
              className="rounded border border-slate-800/60 bg-slate-950/30 p-2"
              data-testid="reliability-source"
              data-reliability-label={labelKey}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-slate-200">
                  {src.source_name}
                </span>
                <span
                  className={`px-1.5 py-0.5 text-[10px] ${style.fg} ${style.bg} border ${style.border} rounded font-mono uppercase tracking-wider`}
                  data-testid="reliability-source-label"
                >
                  {style.label}
                </span>
              </div>
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] text-slate-400">
                <dt>Evidence type</dt>
                <dd className="text-right font-mono">{src.evidence_type || '—'}</dd>
                <dt>Route decision</dt>
                <dd className="text-right font-mono">{src.route_decision || '—'}</dd>
                <dt>Confidence band</dt>
                <dd className="text-right font-mono">{src.calibration_confidence_band || '—'}</dd>
                <dt>Sample count</dt>
                <dd className="text-right font-mono" data-testid="reliability-source-samples">
                  {src.calibration_sample_count ?? 0}
                </dd>
                <dt>Help rate</dt>
                <dd className="text-right font-mono">{fmtRate(src.calibration_help_rate)}</dd>
                <dt>Harm rate</dt>
                <dd className="text-right font-mono">{fmtRate(src.calibration_harm_rate)}</dd>
                <dt>False-confidence rate</dt>
                <dd className="text-right font-mono">{fmtRate(src.calibration_false_confidence_rate)}</dd>
                <dt>Advisory weight</dt>
                <dd className="text-right font-mono">{fmtWeight(src.calibration_advisory_weight)}</dd>
                <dt>Effective paper weight</dt>
                <dd className="text-right font-mono" data-testid="reliability-source-effective-weight">
                  {fmtWeight(src.calibration_effective_weight)}
                </dd>
              </dl>
              {src.calibration_operator_message ? (
                <p className="mt-1 text-[10px] leading-snug text-slate-500" data-testid="reliability-source-message">
                  {src.calibration_operator_message}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>

      <PaperOutcomeReadinessSection bundle={bundle} />

      <p
        className="mt-2 border-t border-slate-700/40 pt-2 text-[10px] text-slate-500"
        data-testid="reliability-safety-banner"
      >
        Paper-only reliability. Human review required. Real-money sizing prohibited. No broker action.
      </p>
    </div>
  );
}

export default ExternalEvidenceReliabilityCard;
