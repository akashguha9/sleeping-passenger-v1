// @ts-ignore
import { render, screen } from '@testing-library/react';
import { mapScoringProps, scoringMode } from '@/lib/realEvidenceWiring';
import { ScoringCoverageCard } from '@/components/RealEvidenceCards';
import type { EvidenceScoringResponse } from '@/lib/apiClient';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const FORBIDDEN = [
  /place order/i,
  /execute trade/i,
  /auto[- ]trade/i,
  /broker (api|order|connected)/i,
  /buy now/i,
  /sell now/i,
  /ai executes/i,
  /edge proven/i,
  /\bcalibrated\b/i,
  /real-money ready: true/i,
];

const LIVE: EvidenceScoringResponse = {
  status: 'OK',
  mode: 'LIVE',
  n_real_canonical_rows: 10000,
  n_scored_real_rows: 49,
  scoring_coverage: 0.0049,
  n_complete_score_vectors: 49,
  score_quality_coverage: 0.0049,
  sources_scored: ['market_data', 'sec_edgar', 'yfinance'],
  score_unavailable_reasons: {
    MISSING_PREVIOUS_PRICE: 8870,
    SCORE_VECTOR_INCOMPLETE: 9951,
  },
  scoring_version: 'real-row-score-v1',
  model_version: 'advisory-logistic-v1',
  n_valid_p: 29,
  calibration_status: 'INSUFFICIENT_EVIDENCE',
  predictive_claim_allowed: false,
  predictive_claim_label: 'PREDICTIVE_CLAIM_LOCKED',
  edge_claimed: false,
  real_money_ready: false,
};

describe('ScoringCoverageCard (Phase 6B)', () => {
  // 1. fetch -> mapping consumes the /evidence/scoring shape
  it('maps the /evidence/scoring endpoint payload into card props', () => {
    const props = mapScoringProps(LIVE);
    expect(props.nScoredRealRows).toBe(49);
    expect(props.nValidP).toBe(29);
    expect(props.mode).toBe('LIVE');
    expect(props.predictiveClaimAllowed).toBe(false);
  });

  // 2. renders scoring coverage
  it('renders scoring coverage', () => {
    render(<ScoringCoverageCard {...mapScoringProps(LIVE)} />);
    expect(screen.getByTestId('scoring-scored-real-rows').textContent).toContain('49');
    expect(screen.getByTestId('scoring-coverage').textContent).toContain('%');
    expect(screen.getByTestId('scoring-quality-coverage')).toBeTruthy();
  });

  // 3. renders n_valid_p
  it('renders n_valid_p', () => {
    render(<ScoringCoverageCard {...mapScoringProps(LIVE)} />);
    expect(screen.getByTestId('scoring-n-valid-p').textContent).toContain('29');
  });

  // 4. shows score-vector-missing / incomplete warning
  it('shows a score-vector warning when rows lack a complete vector', () => {
    render(<ScoringCoverageCard {...mapScoringProps(LIVE)} />);
    expect(screen.getByTestId('scoring-vector-incomplete')).toBeTruthy();
    const missing = mapScoringProps({
      ...LIVE,
      score_unavailable_reasons: { SCORE_VECTOR_MISSING: 5 },
    });
    render(<ScoringCoverageCard {...missing} />);
    expect(screen.getAllByTestId('scoring-vector-missing').length).toBeGreaterThan(0);
  });

  // 5. shows predictive-claim-locked
  it('shows PREDICTIVE_CLAIM_LOCKED when the gate is locked', () => {
    render(<ScoringCoverageCard {...mapScoringProps(LIVE)} />);
    const el = screen.getByTestId('scoring-predictive-locked');
    expect(el.textContent).toMatch(/PREDICTIVE_CLAIM_LOCKED/);
  });

  // 6. shows insufficient evidence
  it('shows INSUFFICIENT_EVIDENCE calibration status', () => {
    render(<ScoringCoverageCard {...mapScoringProps(LIVE)} />);
    expect(screen.getByTestId('scoring-calibration-status').textContent).toContain(
      'INSUFFICIENT_EVIDENCE',
    );
  });

  // 7. never claims edge or real-money ready
  it('never claims edge or real-money readiness', () => {
    render(<ScoringCoverageCard {...mapScoringProps(LIVE)} />);
    expect(screen.getByTestId('scoring-edge-claimed').textContent).toBe('false');
    expect(screen.getByTestId('scoring-real-money').textContent).toBe('false');
  });

  // 8. no execution language
  it('contains no execution / broker / edge / calibrated language', () => {
    const { container } = render(<ScoringCoverageCard {...mapScoringProps(LIVE)} />);
    const text = (container.textContent ?? '').toLowerCase();
    for (const re of FORBIDDEN) {
      expect(re.test(text)).toBe(false);
    }
  });

  // 9. degraded when endpoint missing
  it('renders DEGRADED when the endpoint is unavailable', () => {
    const props = mapScoringProps(null);
    expect(props.mode).toBe('DEGRADED');
    render(<ScoringCoverageCard {...props} />);
    expect(screen.getByTestId('evidence-mode-chip').textContent).toBe('DEGRADED');
  });

  // 10. mock / empty fallback never shown as live
  it('never shows EMPTY (no scored rows) as LIVE', () => {
    expect(scoringMode({ status: 'OK', mode: 'EMPTY' })).toBe('DEGRADED');
    expect(scoringMode({ status: 'DEGRADED', mode: 'DEGRADED' })).toBe('DEGRADED');
    // Only an explicit healthy LIVE mode is LIVE.
    expect(scoringMode({ status: 'OK', mode: 'LIVE' })).toBe('LIVE');
  });
});
