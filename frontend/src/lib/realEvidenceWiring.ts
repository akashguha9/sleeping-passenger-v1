/**
 * First Real Rows + Kanté Score Push sprint — Phase 3 wiring.
 *
 * Pure mappers that turn the read-only `/evidence/*` backend responses into the
 * presentational `RealEvidenceCards` props.  Kept free of React/fetch so the
 * honesty rules are unit-testable in isolation:
 *
 *   - LIVE / REAL_CANARY only when the backend actually reports real activation.
 *   - DEGRADED whenever the endpoint is unavailable (null) or self-reports
 *     DEGRADED — never a green/LIVE chip on missing data.
 *   - MOCK is preserved per-source; a mock fallback is never upgraded to live.
 *   - PREDICTIVE_CLAIM_LOCKED whenever `predictive_claim_allowed` is not true.
 *   - real-money ready is never asserted true by the frontend.
 *
 * No execution wording is ever produced here.
 */
import type {
  EvidenceSourceTruthResponse,
  EvidenceCalibrationResponse,
  EvidenceBundleResponse,
  EvidenceLiveDecisionResponse,
  EvidenceCapacityRiskResponse,
} from './apiClient';
import type {
  DataMode,
  SourceTruthCardProps,
  CalibrationEvidenceCardProps,
  EvidenceBundleCardProps,
  LiveDecisionPathCardProps,
  CapacityCorrelationCardProps,
} from '@/components/RealEvidenceCards';

/** True only when the backend explicitly reports a non-degraded status. */
function isHealthy(status?: string | null): boolean {
  return typeof status === 'string' && status.toUpperCase() === 'OK';
}

export function sourceTruthMode(resp: EvidenceSourceTruthResponse | null): DataMode {
  if (!resp || !isHealthy(resp.status)) return 'DEGRADED';
  if ((resp.real_source_activation_count ?? 0) > 0) return 'REAL_CANARY';
  if ((resp.fixture_source_activation_count ?? 0) > 0) return 'FIXTURE_ONLY';
  // Healthy artifact but zero activation is still not "live".
  return 'DEGRADED';
}

export function mapSourceTruthProps(
  resp: EvidenceSourceTruthResponse | null,
): SourceTruthCardProps {
  const mode = sourceTruthMode(resp);
  if (!resp) {
    return {
      perSource: [],
      realSourceActivationCount: 0,
      fixtureSourceActivationCount: 0,
      cGlobal: 0,
      mode,
    };
  }
  return {
    perSource: (resp.sources ?? []).map((s) => ({
      source_name: s.source_name ?? 'unknown',
      canonical_signal_status: s.canonical_signal_status ?? 'UNKNOWN',
      rows_added: s.rows_added ?? 0,
      is_live_canonical: s.is_live_canonical ?? false,
      canary_real: s.canary_real ?? false,
      // A mock source is never upgraded to live by the wiring layer.
      mock_flag: s.mock_flag ?? false,
      source_truth_score: s.source_truth_score ?? null,
    })),
    realSourceActivationCount: resp.real_source_activation_count ?? 0,
    fixtureSourceActivationCount: resp.fixture_source_activation_count ?? 0,
    cGlobal: resp.C_global ?? 0,
    mode,
  };
}

export function mapCalibrationProps(
  resp: EvidenceCalibrationResponse | null,
): CalibrationEvidenceCardProps {
  const mode: DataMode = !resp || !isHealthy(resp.status) ? 'DEGRADED' : 'LIVE';
  return {
    nRealForward: resp?.n_real_forward ?? 0,
    nHistoricalProxy: resp?.n_historical_proxy ?? 0,
    brier: resp?.brier_real_forward ?? null,
    ece: resp?.ece_real_forward ?? null,
    logloss: resp?.logloss_real_forward ?? null,
    calibrationStatus: resp?.calibration_status ?? 'INSUFFICIENT_EVIDENCE',
    // Never optimistic: only an explicit `true` unlocks the claim.
    predictiveClaimAllowed: resp?.predictive_claim_allowed === true,
    mode,
  };
}

export function mapBundleProps(
  resp: EvidenceBundleResponse | null,
): EvidenceBundleCardProps {
  const mode: DataMode = !resp || !isHealthy(resp.status) ? 'DEGRADED' : 'LIVE';
  return {
    generatedAtUtc: resp?.generated_at_utc ?? null,
    repoCommit: resp?.repo_commit ?? null,
    calibrationStatus: resp?.predictive_claim_allowed
      ? 'CALIBRATED'
      : 'INSUFFICIENT_EVIDENCE',
    predictiveClaimAllowed: resp?.predictive_claim_allowed === true,
    // The frontend never asserts real-money readiness as true.
    realMoneyReady: resp?.real_money_ready === true ? true : false,
    sEvidence: resp?.evidence_score ?? null,
    mode,
  };
}

export function mapLiveDecisionProps(
  resp: EvidenceLiveDecisionResponse | null,
): LiveDecisionPathCardProps {
  const mode: DataMode = !resp || !isHealthy(resp.status) ? 'DEGRADED' : 'LIVE';
  return {
    finalAdvisoryClass: resp?.final_advisory_class ?? 'WAIT',
    pBase: resp?.p_base ?? null,
    pAfterMoltbook: resp?.p_after_moltbook ?? null,
    modelProbability: resp?.model_probability ?? null,
    mode,
  };
}

export function mapCapacityRiskProps(
  resp: EvidenceCapacityRiskResponse | null,
): CapacityCorrelationCardProps {
  // Missing/unknown capacity is ALWAYS shown as risk, never green.
  return {
    capacityStatus: resp?.capacity_status ?? 'CAPACITY_UNKNOWN',
    portfolioCapacityOk: resp?.capacity_ok === true,
    correlationStatus: resp?.correlation_status ?? 'UNKNOWN',
    maxPairwiseCorrelation: resp?.max_pairwise_correlation ?? null,
    correlationBlockReason: resp?.block_reason ?? null,
    mode: 'DEGRADED',
  };
}
