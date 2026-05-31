// @ts-ignore
import { render, screen } from '@testing-library/react';
import {
  SourceTruthCard,
  LiveDecisionPathCard,
  GateVectorCard,
  CapacityCorrelationCard,
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
  /guaranteed return/,
  /real-money ready: true/,
];

describe('RealEvidenceCards', () => {
  // --- 1. source truth: fixture vs real canary ---------------------------
  it('source truth card shows fixture vs real canary', () => {
    render(
      <SourceTruthCard
        realSourceActivationCount={1}
        fixtureSourceActivationCount={2}
        cGlobal={0.33}
        perSource={[
          { source_name: 'polymarket', canonical_signal_status: 'LIVE_CANONICAL', rows_added: 5, is_live_canonical: true, canary_real: true },
          { source_name: 'gdelt', canonical_signal_status: 'LIVE_CANONICAL', rows_added: 4, is_live_canonical: true, canary_real: false },
        ]}
      />,
    );
    expect(screen.getByTestId('source-real-count').textContent).toBe('1');
    expect(screen.getByTestId('source-fixture-count').textContent).toBe('2');
    expect(screen.getByTestId('source-row-polymarket').textContent).toMatch(/REAL_CANARY/);
    expect(screen.getByTestId('source-row-gdelt').textContent).toMatch(/FIXTURE_ONLY/);
  });

  // --- 2. calibration card: predictive claim locked ----------------------
  it('calibration card shows predictive claim locked', () => {
    render(<CalibrationEvidenceCard nRealForward={0} predictiveClaimAllowed={false} />);
    expect(screen.getByTestId('predictive-claim-locked')).toBeTruthy();
    expect(screen.getByTestId('predictive-claim-locked').textContent).toMatch(
      /PREDICTIVE_CLAIM_LOCKED/,
    );
  });

  // --- 3. gate vector: blocked-by reasons --------------------------------
  it('gate vector card shows blocked-by reasons', () => {
    render(
      <GateVectorCard
        gatePassed={false}
        advisoryClass="BLOCKED_BY_PORTFOLIO_CAPACITY"
        blockedBy={['portfolio capacity blocked', 'correlation unknown']}
        gateVector={{ safety: true, freshness: false }}
      />,
    );
    const blocked = screen.getByTestId('gate-blocked-by');
    expect(blocked.textContent).toMatch(/portfolio capacity blocked/);
    expect(blocked.textContent).toMatch(/correlation unknown/);
  });

  // --- 4. capacity card: correlation UNKNOWN as risk ---------------------
  it('capacity card shows correlation unknown as risk', () => {
    render(
      <CapacityCorrelationCard
        capacityStatus="CAPACITY_BLOCKED"
        portfolioCapacityOk={false}
        correlationStatus="UNKNOWN"
        correlationBlockReason="covariance data missing"
      />,
    );
    expect(screen.getByTestId('capacity-correlation-status').textContent).toBe('UNKNOWN');
    expect(screen.getByTestId('capacity-correlation-risk')).toBeTruthy();
    expect(screen.getByTestId('capacity-correlation-risk').textContent).toMatch(/UNKNOWN/);
  });

  // --- 5. evidence bundle: generated_at + status -------------------------
  it('evidence bundle card shows generated_at and status', () => {
    render(
      <EvidenceBundleCard
        generatedAtUtc="2026-05-31T05:47:30Z"
        repoCommit="702da7c"
        calibrationStatus="INSUFFICIENT_EVIDENCE"
        predictiveClaimAllowed={false}
        realMoneyReady={false}
        sEvidence={0.1}
      />,
    );
    expect(screen.getByTestId('bundle-generated-at').textContent).toBe('2026-05-31T05:47:30Z');
    expect(screen.getByTestId('bundle-status').textContent).toBe('INSUFFICIENT_EVIDENCE');
    expect(screen.getByTestId('bundle-real-money').textContent).toBe('false');
    expect(screen.getByTestId('bundle-not-real-money')).toBeTruthy();
  });

  // --- 6. no execution language across all cards -------------------------
  it('never emits execution / broker / real-money language', () => {
    const { container } = render(
      <div>
        <SourceTruthCard perSource={[{ source_name: 'x', canonical_signal_status: 'ZERO_FRESH_ROWS', rows_added: 0, is_live_canonical: false }]} />
        <LiveDecisionPathCard finalAdvisoryClass="WAIT" />
        <GateVectorCard blockedBy={['x']} />
        <CapacityCorrelationCard />
        <CalibrationEvidenceCard />
        <EvidenceBundleCard realMoneyReady={false} />
      </div>,
    );
    const blob = (container.textContent ?? '').toLowerCase();
    for (const pattern of FORBIDDEN) {
      expect(blob).not.toMatch(pattern);
    }
    // every card carries the advisory data attributes + safety banner
    for (const testid of [
      'source-truth-card',
      'live-decision-path-card',
      'gate-vector-card',
      'capacity-correlation-card',
      'calibration-evidence-card',
      'evidence-bundle-card',
    ]) {
      const el = screen.getByTestId(testid);
      expect(el.getAttribute('data-advisory-only')).toBe('true');
      expect(el.getAttribute('data-execution-permission')).toBe('false');
    }
  });

  // --- 7. mock fallback labelled MOCK, not LIVE --------------------------
  it('mock fallback is labelled MOCK and never LIVE', () => {
    render(
      <SourceTruthCard
        mode="MOCK"
        perSource={[
          { source_name: 'polymarket', canonical_signal_status: 'MOCK_NON_CANONICAL', rows_added: 9, is_live_canonical: false, mock_flag: true },
        ]}
      />,
    );
    const card = screen.getByTestId('source-truth-card');
    expect(card.getAttribute('data-data-mode')).toBe('MOCK');
    const chip = screen.getByTestId('evidence-mode-chip');
    expect(chip.textContent).toBe('MOCK');
    expect(chip.textContent).not.toBe('LIVE');
    expect(screen.getByTestId('source-row-polymarket').textContent).toMatch(/MOCK/);
    expect(screen.getByTestId('source-row-polymarket').textContent).not.toMatch(/LIVE/);
  });
});
