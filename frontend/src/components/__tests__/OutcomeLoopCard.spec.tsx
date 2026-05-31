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

  // --- wiring: locked when backend omits the gate gap --------------------
  it('maps null payload to a degraded, locked card', () => {
    const props = mapOutcomeLoopProps(null);
    expect(props.mode).toBe('DEGRADED');
    expect(props.predictiveClaimAllowed).toBe(false);
    expect(props.neededForGate).toBe(200);
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
