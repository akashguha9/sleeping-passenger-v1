/**
 * Operator interpretation of /api/calibration-map (OOS-validated recalibration).
 *
 * Advisory-only. A recalibrated probability never enables sizing on its own.
 */
export interface CalibrationMap {
  method?: 'isotonic' | 'platt' | 'identity' | string;
  improved_out_of_sample?: boolean;
  raw_test_ece?: number;
  cal_test_ece?: number;
  raw_test_brier?: number;
  cal_test_brier?: number;
  ece_improvement?: number;
  train_n?: number;
  test_n?: number;
}

export interface RecalibrationView {
  improved: boolean;
  method: string;
  plain: string;
  eceImprovementPct: number | null;
  tone: 'ok' | 'info';
}

export function interpretCalibrationMap(
  m: CalibrationMap | null | undefined,
): RecalibrationView {
  const improved = m?.improved_out_of_sample === true;
  const method = (m?.method ?? 'identity').toString();
  let eceImprovementPct: number | null = null;
  if (
    typeof m?.raw_test_ece === 'number' &&
    typeof m?.cal_test_ece === 'number' &&
    m.raw_test_ece > 0
  ) {
    eceImprovementPct = ((m.raw_test_ece - m.cal_test_ece) / m.raw_test_ece) * 100;
  }
  const plain = improved
    ? `Scores can be recalibrated (${method}); out-of-sample ECE improves. Recalibrated probabilities are advisory — they do not enable sizing.`
    : 'No out-of-sample recalibration improvement yet (need more reconciled/backtest outcomes). Raw scores shown.';
  return {
    improved,
    method,
    plain,
    eceImprovementPct,
    tone: improved ? 'ok' : 'info',
  };
}
