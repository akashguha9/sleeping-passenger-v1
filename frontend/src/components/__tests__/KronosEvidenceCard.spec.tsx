/**
 * Vitest spec for the Kronos Price-Path Evidence card.
 *
 * The card is advisory-only and must:
 *   * render the evidence-only title + fields,
 *   * carry data-advisory-only=true / data-execution-permission=false,
 *   * never emit execution language (place order / execute trade / auto
 *     trade / broker connected / buy now / sell now),
 *   * show "No decision impact." when there is no Kronos data,
 *   * surface the no-broker safety banner.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { KronosEvidenceCard } from '@/components/KronosEvidenceCard';

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
  /ai decides/,
  /guaranteed return/,
];

describe('KronosEvidenceCard', () => {
  it('renders the supportive evidence read with fields', () => {
    render(
      <KronosEvidenceCard
        evidence={{
          status: 'SUPPORTIVE',
          forecast_return_pct: 5.0,
          forecast_volatility_pct: 1.2,
          downside_path_risk: 0.0,
          directional_agreement: true,
          confidence_calibrated: 0.33,
          final_score_delta: 0.16,
          proof_status: 'OK_ADVISORY_EVIDENCE',
          reason: 'Forecast path agrees with the existing long thesis.',
        }}
      />,
    );
    const card = screen.getByTestId('kronos-evidence-card');
    expect(card.getAttribute('data-kronos-status')).toBe('SUPPORTIVE');
    expect(card.getAttribute('data-advisory-only')).toBe('true');
    expect(card.getAttribute('data-execution-permission')).toBe('false');
    expect(card.getAttribute('data-execution-gate')).toBe('LOCKED');
    expect(card.getAttribute('data-broker-api-called')).toBe('false');
    expect(card.textContent).toMatch(/Kronos Price-Path Evidence/);
    expect(screen.getByTestId('kronos-forecast-return').textContent).toMatch(/\+5\.00%/);
    expect(screen.getByTestId('kronos-score-delta').textContent).toMatch(/\+0\.160/);
    expect(screen.getByTestId('kronos-safety-banner').textContent).toMatch(
      /Evidence only\. Human execution required\. No broker action\./,
    );
  });

  it('shows "No decision impact." when there is no Kronos data', () => {
    render(<KronosEvidenceCard evidence={null} />);
    const card = screen.getByTestId('kronos-evidence-card');
    expect(card.getAttribute('data-kronos-status')).toBe('unavailable');
    expect(screen.getByTestId('kronos-no-data').textContent).toMatch(
      /Kronos evidence unavailable \/ disabled\. No decision impact\./,
    );
  });

  it('renders the disabled status as evidence-only with no decision impact', () => {
    render(
      <KronosEvidenceCard
        evidence={{
          status: 'DISABLED',
          forecast_return_pct: null,
          forecast_volatility_pct: null,
          downside_path_risk: null,
          directional_agreement: null,
          confidence_calibrated: null,
          final_score_delta: 0,
          proof_status: 'DISABLED_NO_DECISION_IMPACT',
          reason: 'Kronos is disabled. Evidence only; no decision impact.',
        }}
      />,
    );
    const card = screen.getByTestId('kronos-evidence-card');
    expect(card.getAttribute('data-kronos-status')).toBe('DISABLED');
    expect(card.textContent?.toLowerCase()).toMatch(/no decision impact/);
  });

  it('never emits forbidden execution language across all statuses', () => {
    const statuses = [
      'SUPPORTIVE',
      'CONTRADICTORY',
      'UNSTABLE',
      'NOISY',
      'INSUFFICIENT_DATA',
      'DISABLED',
      'ERROR_SAFE',
    ] as const;
    for (const status of statuses) {
      const { container, unmount } = render(
        <KronosEvidenceCard
          evidence={{
            status,
            forecast_return_pct: -3.0,
            forecast_volatility_pct: 2.0,
            downside_path_risk: 0.5,
            directional_agreement: false,
            confidence_calibrated: 0.4,
            final_score_delta: -0.2,
            proof_status: 'OK_ADVISORY_EVIDENCE',
            reason: 'Human review required.',
          }}
        />,
      );
      const blob = (container.textContent ?? '').toLowerCase();
      for (const pattern of FORBIDDEN) {
        expect(blob).not.toMatch(pattern);
      }
      unmount();
    }
  });
});
