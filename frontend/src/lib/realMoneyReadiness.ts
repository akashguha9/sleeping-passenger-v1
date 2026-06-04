/**
 * Operator-facing interpretation of /api/readiness/real-money.
 *
 * Plain-language, advisory-only. Nothing here authorises execution or sizing.
 */
export type AllowedMode =
  | 'SCALE_BLOCKED'
  | 'PAPER_ONLY'
  | 'TINY_MANUAL_PROBE_ONLY'
  | 'MANUAL_REAL_MONEY_READY_SMALL_ONLY'
  | 'MANUAL_REAL_MONEY_READY_CALIBRATED'
  // legacy alias kept for back-compat with older API payloads
  | 'MANUAL_REAL_MONEY_READY';

export interface RealMoneyReadiness {
  readiness_score?: number;
  readiness_max?: number;
  allowed_mode?: AllowedMode | string;
  blockers?: string[];
  warnings?: string[];
  reason?: string;
  calibration_status?: string;
  real_n?: number;
  paper_n?: number;
}

export interface ReadinessView {
  mode: AllowedMode;
  label: string;
  plain: string;
  tone: 'danger' | 'caution' | 'info' | 'ok';
  score: number | null;
  max: number;
}

const MODE_LABEL: Record<AllowedMode, string> = {
  SCALE_BLOCKED: 'Scale blocked',
  PAPER_ONLY: 'Paper only',
  TINY_MANUAL_PROBE_ONLY: 'Tiny manual probe only',
  MANUAL_REAL_MONEY_READY_SMALL_ONLY: 'Manual real-money — small only',
  MANUAL_REAL_MONEY_READY_CALIBRATED: 'Manual real-money — calibrated',
  MANUAL_REAL_MONEY_READY: 'Manual real-money ready',
};

const MODE_PLAIN: Record<AllowedMode, string> = {
  SCALE_BLOCKED:
    'Real-money use is blocked. Resolve the blockers before any live trade. Human execution required.',
  PAPER_ONLY:
    'Paper trading only until blockers are resolved. Journal record only — human execution required.',
  TINY_MANUAL_PROBE_ONLY:
    'Scores are not calibrated enough to size from. Tiny manual probes only; manual review only; human execution required.',
  MANUAL_REAL_MONEY_READY_SMALL_ONLY:
    'Manual real-money permitted at SMALL size only (calibration not yet real-grade). Position sizing human-controlled; human execution required. Not scaling-ready.',
  MANUAL_REAL_MONEY_READY_CALIBRATED:
    'Real-calibrated on real outcomes. Manual real-money permitted with discipline. Human execution required. Not scaling-ready.',
  MANUAL_REAL_MONEY_READY:
    'Manual real-money trades permitted with discipline. Not scaling-ready. Human execution required.',
};

const MODE_TONE: Record<AllowedMode, ReadinessView['tone']> = {
  SCALE_BLOCKED: 'danger',
  PAPER_ONLY: 'caution',
  TINY_MANUAL_PROBE_ONLY: 'info',
  MANUAL_REAL_MONEY_READY_SMALL_ONLY: 'ok',
  MANUAL_REAL_MONEY_READY_CALIBRATED: 'ok',
  MANUAL_REAL_MONEY_READY: 'ok',
};

function normalizeMode(value: string | undefined): AllowedMode {
  switch ((value ?? '').toUpperCase()) {
    case 'PAPER_ONLY':
      return 'PAPER_ONLY';
    case 'TINY_MANUAL_PROBE_ONLY':
      return 'TINY_MANUAL_PROBE_ONLY';
    case 'MANUAL_REAL_MONEY_READY_SMALL_ONLY':
      return 'MANUAL_REAL_MONEY_READY_SMALL_ONLY';
    case 'MANUAL_REAL_MONEY_READY_CALIBRATED':
      return 'MANUAL_REAL_MONEY_READY_CALIBRATED';
    case 'MANUAL_REAL_MONEY_READY':
      return 'MANUAL_REAL_MONEY_READY';
    default:
      return 'SCALE_BLOCKED';
  }
}

export function interpretReadiness(
  r: RealMoneyReadiness | null | undefined,
): ReadinessView {
  const mode = normalizeMode(r?.allowed_mode as string | undefined);
  const score = typeof r?.readiness_score === 'number' ? r.readiness_score : null;
  const max = typeof r?.readiness_max === 'number' ? r.readiness_max : 8;
  return {
    mode,
    label: MODE_LABEL[mode],
    plain: r?.reason?.trim() || MODE_PLAIN[mode],
    tone: MODE_TONE[mode],
    score,
    max,
  };
}
