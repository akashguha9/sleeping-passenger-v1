/**
 * Score calibration — operator-facing interpretation of the backend
 * /api/score-calibration status.  The whole point is that a precise-looking
 * score (e.g. 0.91) must never be shown as if it were validated: this maps the
 * calibration status to advisory wording and an explicit
 * "do not size from this score" flag.
 *
 * Advisory-only. Nothing here authorises sizing or execution.
 */
export type CalibrationStatus =
  | 'UNCALIBRATED'
  | 'LOW_SAMPLE'
  | 'CALIBRATING'
  | 'CALIBRATED';

export interface ScoreCalibration {
  calibration_status?: CalibrationStatus | string;
  sample_size?: number;
  score_should_drive_sizing?: boolean;
  win_rate?: number | null;
  false_positive_rate?: number | null;
  message?: string;
}

export interface CalibrationView {
  status: CalibrationStatus;
  label: string;
  shouldDriveSizing: boolean;
  warning: string;
  tone: 'danger' | 'caution' | 'info' | 'ok';
}

const LABEL: Record<CalibrationStatus, string> = {
  UNCALIBRATED: 'Uncalibrated',
  LOW_SAMPLE: 'Low sample',
  CALIBRATING: 'Calibrating',
  CALIBRATED: 'Calibrated',
};

const TONE: Record<CalibrationStatus, CalibrationView['tone']> = {
  UNCALIBRATED: 'danger',
  LOW_SAMPLE: 'caution',
  CALIBRATING: 'info',
  CALIBRATED: 'ok',
};

const DEFAULT_WARNING: Record<CalibrationStatus, string> = {
  UNCALIBRATED:
    'Score is advisory and NOT empirically calibrated — no reconciled outcomes yet. Do not size from this score.',
  LOW_SAMPLE:
    'Score is advisory and low-confidence — too few reconciled outcomes. Do not size from this score.',
  CALIBRATING:
    'Score calibration in progress — not yet proof of edge. Do not size from this score.',
  CALIBRATED:
    'Score has a reviewable calibration sample — process evidence, not a profitability guarantee. Size conservatively.',
};

function normalizeStatus(value: string | undefined): CalibrationStatus {
  switch ((value ?? '').toUpperCase()) {
    case 'LOW_SAMPLE':
      return 'LOW_SAMPLE';
    case 'CALIBRATING':
      return 'CALIBRATING';
    case 'CALIBRATED':
      return 'CALIBRATED';
    default:
      return 'UNCALIBRATED';
  }
}

export function interpretCalibration(
  cal: ScoreCalibration | null | undefined,
): CalibrationView {
  const status = normalizeStatus(cal?.calibration_status as string | undefined);
  // Fail closed: only CALIBRATED may ever drive sizing, and only if the
  // backend explicitly says so.
  const shouldDriveSizing =
    status === 'CALIBRATED' && cal?.score_should_drive_sizing === true;
  return {
    status,
    label: LABEL[status],
    shouldDriveSizing,
    warning: cal?.message?.trim() || DEFAULT_WARNING[status],
    tone: TONE[status],
  };
}
