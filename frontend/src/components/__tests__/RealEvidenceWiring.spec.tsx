// @ts-ignore
import { render, screen } from '@testing-library/react';
import {
  sourceTruthMode,
  mapSourceTruthProps,
  mapCalibrationProps,
  mapBundleProps,
  mapCapacityRiskProps,
} from '@/lib/realEvidenceWiring';
import {
  SourceTruthCard,
  CalibrationEvidenceCard,
  EvidenceBundleCard,
} from '@/components/RealEvidenceCards';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const FORBIDDEN = [
  /place order/,
  /execute trade/,
  /auto[- ]trade/,
  /broker (api|order|connected)/,
  /buy now/,
  /sell now/,
  /ai executes/,
  /real-money ready: true/,
];

describe('RealEvidence wiring (Phase 3)', () => {
  // --- fetch -> source-truth shape --------------------------------------- //
  it('maps the source-truth endpoint payload into card props', () => {
    const props = mapSourceTruthProps({
      status: 'OK',
      real_source_activation_count: 3,
      fixture_source_activation_count: 0,
      C_global: 0.75,
      sources: [
        {
          source_name: 'sec_edgar',
          canonical_signal_status: 'LIVE_CANONICAL',
          rows_added: 25,
          is_live_canonical: true,
          canary_real: true,
        },
      ],
    });
    expect(props.realSourceActivationCount).toBe(3);
    expect(props.perSource?.length).toBe(1);
    expect(props.mode).toBe('REAL_CANARY');
  });

  // --- real canary when backend reports real ----------------------------- //
  it('shows REAL_CANARY when the backend reports real activation', () => {
    expect(
      sourceTruthMode({ status: 'OK', real_source_activation_count: 2 }),
    ).toBe('REAL_CANARY');
  });

  // --- degraded when endpoint missing ------------------------------------ //
  it('shows DEGRADED when the endpoint is unavailable (null)', () => {
    expect(sourceTruthMode(null)).toBe('DEGRADED');
    const props = mapSourceTruthProps(null);
    expect(props.mode).toBe('DEGRADED');
    expect(props.realSourceActivationCount).toBe(0);
    render(<SourceTruthCard {...props} />);
    const card = screen.getByTestId('source-truth-card');
    expect(card.getAttribute('data-data-mode')).toBe('DEGRADED');
  });

  // --- predictive claim locked from backend ------------------------------ //
  it('renders PREDICTIVE_CLAIM_LOCKED from the backend gate', () => {
    const props = mapCalibrationProps({
      status: 'OK',
      n_real_forward: 12,
      calibration_status: 'INSUFFICIENT_EVIDENCE',
      predictive_claim_allowed: false,
    });
    expect(props.predictiveClaimAllowed).toBe(false);
    render(<CalibrationEvidenceCard {...props} />);
    expect(screen.getByTestId('predictive-claim-locked')).toBeTruthy();
  });

  it('never optimistically unlocks the predictive claim when the field is missing', () => {
    const props = mapCalibrationProps({ status: 'OK', n_real_forward: 5 });
    expect(props.predictiveClaimAllowed).toBe(false);
  });

  // --- no real-money ready ----------------------------------------------- //
  it('never shows real-money ready as true', () => {
    const props = mapBundleProps({
      status: 'OK',
      generated_at_utc: '2026-05-31T00:00:00Z',
      real_money_ready: false,
      predictive_claim_allowed: false,
      evidence_score: 0.3,
    });
    expect(props.realMoneyReady).toBe(false);
    render(<EvidenceBundleCard {...props} />);
    expect(screen.getByTestId('bundle-not-real-money')).toBeTruthy();
    const val = screen.getByTestId('bundle-real-money');
    expect(val.textContent).toBe('false');
  });

  // --- mock fallback never shown as live --------------------------------- //
  it('never upgrades a mock source to live', () => {
    const props = mapSourceTruthProps({
      status: 'OK',
      real_source_activation_count: 0,
      fixture_source_activation_count: 0,
      sources: [
        {
          source_name: 'polymarket',
          canonical_signal_status: 'MOCK_NON_CANONICAL',
          rows_added: 0,
          is_live_canonical: false,
          canary_real: false,
          mock_flag: true,
        },
      ],
    });
    expect(props.perSource?.[0].mock_flag).toBe(true);
    expect(props.perSource?.[0].is_live_canonical).toBe(false);
    // zero activation + healthy status still resolves to DEGRADED, never live.
    expect(props.mode).toBe('DEGRADED');
  });

  // --- capacity unknown is risk ------------------------------------------ //
  it('treats missing capacity as risk, never green', () => {
    const props = mapCapacityRiskProps(null);
    expect(props.capacityStatus).toBe('CAPACITY_UNKNOWN');
    expect(props.portfolioCapacityOk).toBe(false);
  });

  // --- no execution language --------------------------------------------- //
  it('produces no execution language in any wired card', () => {
    const blobs = [
      JSON.stringify(mapSourceTruthProps(null)),
      JSON.stringify(mapCalibrationProps(null)),
      JSON.stringify(mapBundleProps(null)),
      JSON.stringify(mapCapacityRiskProps(null)),
    ].join(' ').toLowerCase();
    for (const re of FORBIDDEN) {
      expect(re.test(blobs)).toBe(false);
    }
  });
});
