/**
 * Vitest spec for the operational truth-surface panel (Feed-the-Loop sprint).
 *
 * Pins the honest-copy rules:
 *   N < 50            -> "UNCALIBRATED SCORE — not a calibrated probability"
 *   50 <= N < 200     -> "MEASURED BUT NOT DECISION-GRADE CALIBRATED"
 *   gate passed       -> "CALIBRATION GATE PASSED"
 * plus: BLOCKED state visible, missing stops visible, artifact/velocity
 * numbers visible, latest alerts rendered, offline = UNKNOWN not healthy.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

vi.mock('@/lib/apiClient', () => ({
  getTruthSurface: vi.fn(),
}));

import { getTruthSurface } from '@/lib/apiClient';
import {
  TruthSurfacePanel,
  calibrationCopy,
} from '@/components/TruthSurfacePanel';

const mockGet = getTruthSurface as unknown as ReturnType<typeof vi.fn>;

function surface(over: Record<string, unknown> = {}) {
  return {
    overall_operational_state: 'BLOCKED',
    state_reasons: ['10/10 active holdings have no stop recorded'],
    calibration_status: 'MEASURED_NOT_CALIBRATED',
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
    portfolio_stop_exposure_fraction: null,
    fresh_discovery_status: 'OK',
    provider_canary_status: 'PASS',
    rows_persisted_status: {
      sources: { kalshi: { status: 'DEGRADED_ZERO_PERSISTED' } },
    },
    latest_alerts: [
      { alert_id: 'a1', severity: 'CRITICAL', title: 'System BLOCKED' },
    ],
    next_required_operator_action: 'Confirm stops via the template',
    ...over,
  };
}

describe('calibration copy rules', () => {
  it('says UNCALIBRATED below 50', () => {
    expect(
      calibrationCopy({ matured_real_outcome_count: 2 } as any),
    ).toContain('UNCALIBRATED SCORE');
  });
  it('says MEASURED BUT NOT DECISION-GRADE between 50 and 200', () => {
    expect(
      calibrationCopy({
        matured_real_outcome_count: 56,
        calibration_status: 'MEASURED_NOT_CALIBRATED',
      } as any),
    ).toBe('MEASURED BUT NOT DECISION-GRADE CALIBRATED');
  });
  it('allows CALIBRATION GATE PASSED only when the backend gate passed', () => {
    expect(
      calibrationCopy({
        matured_real_outcome_count: 250,
        calibration_status: 'CALIBRATED',
      } as any),
    ).toBe('CALIBRATION GATE PASSED');
    // large N alone never unlocks the phrase
    expect(
      calibrationCopy({
        matured_real_outcome_count: 250,
        calibration_status: 'MEASURED_NOT_CALIBRATED',
      } as any),
    ).toBe('MEASURED BUT NOT DECISION-GRADE CALIBRATED');
  });
});

describe('TruthSurfacePanel', () => {
  beforeEach(() => mockGet.mockReset());

  it('renders BLOCKED state, missing stops, velocity, and alerts', async () => {
    mockGet.mockResolvedValue(surface());
    render(<TruthSurfacePanel />);
    const state = await screen.findByTestId('truth-overall-state');
    expect(state.textContent).toBe('BLOCKED');
    expect(
      (await screen.findByTestId('truth-calibration-copy')).textContent,
    ).toContain('MEASURED BUT NOT DECISION-GRADE CALIBRATED');
    expect(screen.getByText(/3.571\/day/).textContent).toBeTruthy();
    expect(screen.getByText(/10 \/ 0/)).toBeTruthy(); // stops missing/unconfirmed
    expect(screen.getByText(/SILENT: kalshi/)).toBeTruthy();
    const alerts = screen.getByTestId('truth-latest-alerts');
    expect(alerts.textContent).toContain('System BLOCKED');
    expect(
      screen.getByTestId('truth-next-action').textContent,
    ).toContain('Confirm stops');
  });

  it('shows UNKNOWN exposure instead of pretending', async () => {
    mockGet.mockResolvedValue(surface({ portfolio_stop_exposure_fraction: null }));
    render(<TruthSurfacePanel />);
    await screen.findByTestId('truth-overall-state');
    expect(screen.getByText('UNKNOWN')).toBeTruthy();
  });

  it('offline renders UNREACHABLE, never healthy', async () => {
    mockGet.mockResolvedValue(null);
    render(<TruthSurfacePanel />);
    const panel = await screen.findByTestId('truth-surface-panel');
    expect(panel.textContent).toContain('TRUTH SURFACE UNREACHABLE');
    expect(panel.textContent).toContain('UNKNOWN');
  });
});
