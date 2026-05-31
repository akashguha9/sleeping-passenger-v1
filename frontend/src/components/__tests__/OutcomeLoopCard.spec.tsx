// @ts-ignore
import { render, screen } from '@testing-library/react';
import { OutcomeLoopCard } from '@/components/RealEvidenceCards';
import { mapOutcomeLoopProps } from '@/lib/realEvidenceWiring';

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

describe('OutcomeLoopCard', () => {
  // --- 1. renders N_real_forward -----------------------------------------
  it('test_outcome_card_renders_n_real_forward', () => {
    render(<OutcomeLoopCard nRealForwardPairs={7} />);
    expect(screen.getByTestId('outcome-n-real-forward').textContent).toBe('7');
  });

  // --- 2. renders pending and excluded -----------------------------------
  it('test_outcome_card_renders_pending_and_excluded', () => {
    render(<OutcomeLoopCard nPendingHorizon={42} nExcluded={5} />);
    expect(screen.getByTestId('outcome-pending-horizon').textContent).toBe('42');
    expect(screen.getByTestId('outcome-excluded').textContent).toBe('5');
  });

  // --- 3. renders Brier/ECE/LogLoss when available -----------------------
  it('test_outcome_card_renders_brier_ece_when_available', () => {
    render(<OutcomeLoopCard brier={0.21} ece={0.08} logloss={0.55} />);
    expect(screen.getByTestId('outcome-brier').textContent).toBe('0.21');
    expect(screen.getByTestId('outcome-ece').textContent).toBe('0.08');
    expect(screen.getByTestId('outcome-logloss').textContent).toBe('0.55');
  });

  // --- 4. shows needed-for-gate ------------------------------------------
  it('test_outcome_card_shows_needed_for_gate', () => {
    render(<OutcomeLoopCard nRealForwardPairs={1} neededForGate={199} />);
    expect(screen.getByTestId('outcome-needed-for-gate').textContent).toBe('199');
  });

  // --- 5. predictive claim locked below 200 ------------------------------
  it('test_outcome_card_predictive_claim_locked_below_200', () => {
    render(<OutcomeLoopCard nRealForwardPairs={5} predictiveClaimAllowed={false} />);
    expect(screen.getByTestId('outcome-calibration-locked')).toBeTruthy();
    expect(screen.queryByTestId('outcome-predictive-allowed')).toBeNull();
  });

  // --- 6. no execution language ------------------------------------------
  it('test_outcome_card_no_execution_language', () => {
    const { container } = render(
      <OutcomeLoopCard
        nRealForwardPairs={3}
        nPendingHorizon={10}
        nExcluded={2}
        brier={0.3}
        ece={0.2}
        neededForGate={197}
      />,
    );
    const text = (container.textContent ?? '').toLowerCase();
    for (const rx of FORBIDDEN) {
      expect(rx.test(text)).toBe(false);
    }
    // Card asserts advisory-only / no execution permission.
    const root = screen.getByTestId('outcome-loop-card');
    expect(root.getAttribute('data-advisory-only')).toBe('true');
    expect(root.getAttribute('data-execution-permission')).toBe('false');
  });

  // --- 7. renders forward-eligible and due-forward -----------------------
  it('test_frontend_renders_forward_eligible_and_pending', () => {
    render(
      <OutcomeLoopCard nForwardEligible={12} nDueForward={3} nPendingHorizon={9} />,
    );
    expect(screen.getByTestId('outcome-forward-eligible').textContent).toBe('12');
    expect(screen.getByTestId('outcome-due-forward').textContent).toBe('3');
    expect(screen.getByTestId('outcome-pending-horizon').textContent).toBe('9');
  });

  // --- 8. renders needed-to-200 ------------------------------------------
  it('test_frontend_renders_needed_to_200', () => {
    render(<OutcomeLoopCard nRealForwardPairs={1} neededForGate={199} />);
    expect(screen.getByTestId('outcome-needed-for-gate').textContent).toBe('199');
  });

  // --- 9. no green calibration below 200 ---------------------------------
  it('test_no_green_calibration_below_200', () => {
    render(<OutcomeLoopCard nForwardEligible={10} nRealForwardPairs={4} predictiveClaimAllowed={false} />);
    expect(screen.getByTestId('outcome-calibration-locked')).toBeTruthy();
    expect(screen.queryByTestId('outcome-predictive-allowed')).toBeNull();
  });

  // --- wiring: forward-eligibility fields mapped -------------------------
  it('maps forward-eligibility fields from the backend payload', () => {
    const props = mapOutcomeLoopProps({
      status: 'OK',
      n_real_forward_pairs: 0,
      n_forward_outcome_eligible: 12,
      n_due_forward: 0,
      forward_unavailable_reasons: { MISSING_ENTRY_PRICE: 5 },
      n_pending_horizon: 12,
      predictive_claim_allowed: false,
      n_needed_to_200: 200,
    });
    expect(props.nForwardEligible).toBe(12);
    expect(props.nDueForward).toBe(0);
    expect(props.forwardUnavailableReasons).toEqual({ MISSING_ENTRY_PRICE: 5 });
    expect(props.predictiveClaimAllowed).toBe(false);
  });

  // --- wiring: locked when backend omits the gate gap --------------------
  it('maps null payload to a degraded, locked card', () => {
    const props = mapOutcomeLoopProps(null);
    expect(props.mode).toBe('DEGRADED');
    expect(props.predictiveClaimAllowed).toBe(false);
    expect(props.neededForGate).toBe(200);
  });

  // --- forward-eligible throughput visibility (this sprint) --------------
  it('test_frontend_renders_forward_eligibility_rate', () => {
    render(
      <OutcomeLoopCard
        forwardEligibleBefore={4}
        forwardEligibleAfter={49}
        eligibilityRateAfter={0.29}
      />,
    );
    expect(screen.getByTestId('outcome-forward-eligible-growth').textContent).toBe('4 → 49');
    expect(screen.getByTestId('outcome-forward-eligibility-rate').textContent).toBe('0.29');
  });

  it('test_frontend_renders_reason_reductions', () => {
    render(
      <OutcomeLoopCard
        forwardEligibleBefore={4}
        forwardEligibleAfter={49}
        missingTickerBefore={119}
        missingTickerAfter={119}
        missingEntryPriceBefore={25}
        missingEntryPriceAfter={0}
        missingProbabilityBefore={2}
        missingProbabilityAfter={2}
        topMissingEntryPriceTickers={[{ key: 'NVDA', count: 6 }]}
      />,
    );
    expect(screen.getByTestId('outcome-missing-entry-price-reduction').textContent).toContain('25 → 0');
    expect(screen.getByTestId('outcome-missing-ticker-reduction').textContent).toContain('119 → 119');
    expect(screen.getByTestId('outcome-top-missing-ohlcv-tickers').textContent).toContain('NVDA:6');
  });

  it('test_frontend_keeps_calibration_locked_with_throughput', () => {
    render(
      <OutcomeLoopCard
        forwardEligibleBefore={4}
        forwardEligibleAfter={49}
        predictiveClaimAllowed={false}
      />,
    );
    expect(screen.getByTestId('outcome-calibration-locked')).toBeTruthy();
    expect(screen.queryByTestId('outcome-predictive-allowed')).toBeNull();
  });

  it('maps forward-throughput fields from the backend payload', () => {
    const props = mapOutcomeLoopProps({
      status: 'OK',
      n_forward_outcome_eligible: 49,
      predictive_claim_allowed: false,
      forward_throughput: {
        forward_eligible_before: 4,
        forward_eligible_after: 49,
        eligibility_rate_after: 0.29,
        missing_entry_price_before: 25,
        missing_entry_price_after: 0,
        top_missing_entry_price_tickers: [{ key: 'NVDA', count: 6 }],
      },
    });
    expect(props.forwardEligibleBefore).toBe(4);
    expect(props.forwardEligibleAfter).toBe(49);
    expect(props.missingEntryPriceAfter).toBe(0);
    expect(props.topMissingEntryPriceTickers).toEqual([{ key: 'NVDA', count: 6 }]);
  });

  it('maps a backend payload and never optimistically unlocks', () => {
    const props = mapOutcomeLoopProps({
      status: 'OK',
      n_real_forward_pairs: 1,
      n_pending_horizon: 56,
      n_excluded: 153,
      brier_real_forward: null,
      predictive_claim_allowed: false,
      needed_for_gate: 199,
      n_outcome_gate: 200,
    });
    expect(props.mode).toBe('LIVE');
    expect(props.nRealForwardPairs).toBe(1);
    expect(props.neededForGate).toBe(199);
    expect(props.predictiveClaimAllowed).toBe(false);
  });
});
