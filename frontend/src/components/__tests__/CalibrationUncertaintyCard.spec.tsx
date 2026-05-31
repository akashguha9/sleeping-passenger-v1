/**
 * Objective 4 — Vitest spec for CalibrationUncertaintyCard.
 *
 * The card must make uncertainty unavoidable:
 *   * render calibration_status (default INSUFFICIENT_EVIDENCE)
 *   * render predictive_claim_allowed=false
 *   * render the insufficient-evidence warning
 *   * render N_real / n_valid_p
 *   * never emit execution / broker / auto-trade copy
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { CalibrationUncertaintyCard } from '@/components/CalibrationUncertaintyCard';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

describe('CalibrationUncertaintyCard', () => {
  it('renders insufficient-evidence defaults with no predictive claim', () => {
    render(<CalibrationUncertaintyCard />);
    expect(screen.getByTestId('calibration-uncertainty-card')).toBeTruthy();
    expect(screen.getByText('INSUFFICIENT_EVIDENCE')).toBeTruthy();
    // predictive_claim_allowed shows false.
    expect(screen.getByText('false')).toBeTruthy();
    // The warning is present.
    expect(screen.getByTestId('calibration-warning')).toBeTruthy();
  });

  it('renders N_real and n_valid_p values', () => {
    render(<CalibrationUncertaintyCard nReal={0} nValidP={0} />);
    const card = screen.getByTestId('calibration-uncertainty-card');
    expect(card.textContent).toContain('N_real');
    expect(card.textContent).toContain('n_valid_p');
  });

  it('hides the warning only when a predictive claim is genuinely allowed', () => {
    render(
      <CalibrationUncertaintyCard
        calibrationStatus="MEASURED"
        predictiveClaimAllowed={true}
      />,
    );
    expect(screen.queryByTestId('calibration-warning')).toBeNull();
  });

  it('never emits execution / broker / auto-trade copy', () => {
    render(<CalibrationUncertaintyCard />);
    const text = screen.getByTestId('calibration-uncertainty-card').textContent ?? '';
    const lowered = text.toLowerCase();
    for (const forbidden of [
      'place order',
      'execute trade',
      'auto-trade',
      'auto trade',
      'buy now',
      'sell now',
      'broker connected',
    ]) {
      expect(lowered.includes(forbidden)).toBe(false);
    }
  });
});
