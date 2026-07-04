/**
 * E2E: cockpit truth surface honesty (Open-the-Gate sprint, 2026-07-04).
 *
 * Backend routes are stubbed via page.route (repo e2e convention) with the
 * REAL shape the live BLOCKED system serves.  Verifies the operator sees:
 * BLOCKED state, honest calibration copy, N, evidence velocity, missing
 * stops, latest alerts, next action — and never a false HEALTHY or a
 * "calibrated probability" claim below the gate.
 */
import { expect, test } from '@playwright/test';

const TRUTH_SURFACE = {
  report: 'operational_truth_surface',
  overall_operational_state: 'BLOCKED',
  state_reasons: [
    '10/10 active holdings have no stop recorded (no stop -> no healthy)',
    'CRITICAL: 2 leveraged position(s) without usable stops',
  ],
  calibration_status: 'MEASURED_NOT_CALIBRATED',
  calibration_display_note:
    'uncalibrated model score — do not read model probabilities as calibrated frequencies',
  matured_real_outcome_count: 56,
  brier_real_forward: 0.2794,
  evidence_velocity_7d: 3.571,
  maturation_velocity_7d: 0,
  pending_horizon_count: 25,
  due_unmatured_count: 0,
  canonical_holding_count: 10,
  active_holding_count: 10,
  missing_stop_count: 10,
  unconfirmed_stop_count: 0,
  leveraged_position_count: 2,
  leveraged_without_stop_count: 2,
  holdings_truth_status: 'HOLDINGS_TRUTH_STALE',
  holdings_freshness_age_minutes: 62700,
  portfolio_stop_exposure: null,
  portfolio_stop_exposure_fraction: null,
  fresh_discovery_status: 'OK',
  provider_canary_status: 'PASS',
  rows_persisted_status: {
    sources: { kalshi: { status: 'DEGRADED_ZERO_PERSISTED' } },
  },
  scheduler_status: 'HEALTHY',
  latest_alerts: [
    { alert_id: 'a1', severity: 'CRITICAL', title: 'System BLOCKED' },
  ],
  next_required_operator_action: 'Confirm stops via the template',
  advisory_status: 'ADVISORY_ONLY',
  execution_gate: 'LOCKED',
};

test('cockpit renders the truth surface honestly', async ({ page }) => {
  await page.route('**/truth-surface', (r) =>
    r.fulfill({ json: TRUTH_SURFACE }),
  );
  // remaining cockpit fetches: harmless nulls
  await page.route('**/api/diagnostics/cockpit', (r) => r.fulfill({ json: {} }));
  await page.route('**/api/readiness/real-money', (r) => r.fulfill({ json: {} }));
  await page.route('**/api/calibration-map', (r) => r.fulfill({ json: {} }));

  await page.goto('/cockpit');
  const panel = page.getByTestId('truth-surface-panel');
  await expect(panel).toBeVisible();

  // operational state visible and honest
  await expect(page.getByTestId('truth-overall-state')).toHaveText('BLOCKED');
  // calibration copy: measured, never "calibrated probability"
  const cal = page.getByTestId('truth-calibration-copy');
  await expect(cal).toContainText('MEASURED BUT NOT DECISION-GRADE CALIBRATED');
  await expect(cal).toContainText('N=56');
  // metrics visible
  await expect(panel).toContainText('3.571/day');
  await expect(panel).toContainText('10 / 0'); // missing / unconfirmed stops
  // alerts + next action visible
  await expect(page.getByTestId('truth-latest-alerts')).toContainText(
    'System BLOCKED',
  );
  await expect(page.getByTestId('truth-next-action')).toContainText(
    'Confirm stops',
  );
  // forbidden overclaims
  const text = (await panel.textContent()) ?? '';
  expect(text).not.toContain('CALIBRATION GATE PASSED');
  expect(text.includes('HEALTHY')).toBeFalsy();
});
