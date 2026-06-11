/**
 * Vitest specs for the simulator workbench page.
 *
 * Locks: fixture controls render, evaluation flows through apiClient, the
 * scrutineering / crash / driver panels appear, and — critically — no
 * execution language and no fake verdict on backend failure.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SimulatorPage from '@/app/simulator/page';

const mockEvaluate = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  postSimulatorEvaluate: (payload: Record<string, unknown>) =>
    mockEvaluate(payload),
}));

vi.mock('@/components/AdvisoryOnlyBadge', () => ({
  AdvisoryOnlyBadge: () => <span data-testid="advisory-badge">ADVISORY ONLY</span>,
}));

const RESULT = {
  advisory_status: 'ADVISORY_ONLY',
  decision: {
    ticker: 'GRIDCO',
    theme: 'ai_grid_buildout',
    circuit: 'mid_cap',
    final_state: 'watchlist',
    final_candidate_score: 52.6,
    decision_reason: 'Score 52.6/100. ADVISORY_ONLY.',
    signal_compound: 'hard',
    signal_grip: 87,
    crash_risk: 0.32,
    crash_density: 0,
    downforce: 0.78,
    drag: 0.16,
    aero_efficiency: 4.9,
    dirty_air: 0.1,
    driver_permission: 1,
    driver_status: 'clean',
    meal_box_status: { complete: true, missing_items: [] },
    gate_results: { crash_gate: true },
  },
  breakdown: {
    scrutineering: {
      passed: false,
      suspicion_score: 0.72,
      violations: [
        { check: 'uniform_optimism', explanation: 'inputs implausibly smooth' },
      ],
    },
    crash: {
      worst_crash_combination: ['high_valuation', 'rising_rates'],
      safe_to_enter_conditions: ['high_valuation severity must fall below 0.40'],
    },
    driver: { license_level: 'pro_am', status: 'clean', danger_points: 0 },
  },
};

describe('SimulatorPage', () => {
  beforeEach(() => {
    mockEvaluate.mockReset();
  });

  it('renders fixture controls and the advisory framing', () => {
    render(<SimulatorPage />);
    expect(screen.getByTestId('simulator-fixture-select')).toBeTruthy();
    expect(screen.getByTestId('simulator-run-button').textContent).toMatch(
      /advisory/i,
    );
    expect(screen.getByTestId('simulator-calibration-warning').textContent)
      .toMatch(/not yet empirically fitted/i);
    const page = document.body.textContent ?? '';
    expect(page).toMatch(/cannot trade/i);
    expect(page).not.toMatch(/place order|execute trade|trade now/i);
  });

  it('runs an evaluation and shows verdict + panels', async () => {
    mockEvaluate.mockResolvedValue(RESULT);
    render(<SimulatorPage />);
    fireEvent.click(screen.getByTestId('simulator-run-button'));
    await waitFor(() =>
      expect(screen.getByTestId('simulator-final-state')).toBeTruthy(),
    );
    expect(mockEvaluate).toHaveBeenCalledTimes(1);
    expect(
      screen.getByTestId('simulator-scrutineering-panel').textContent,
    ).toMatch(/FAILED/);
    expect(screen.getByTestId('simulator-crash-panel').textContent).toMatch(
      /high_valuation \+ rising_rates/,
    );
    expect(screen.getByTestId('simulator-driver-panel').textContent).toMatch(
      /pro_am/,
    );
  });

  it('shows an honest error and no fake verdict when the backend is down', async () => {
    mockEvaluate.mockRejectedValue(new Error('connection refused'));
    render(<SimulatorPage />);
    fireEvent.click(screen.getByTestId('simulator-run-button'));
    await waitFor(() =>
      expect(screen.getByTestId('simulator-error')).toBeTruthy(),
    );
    expect(screen.getByTestId('simulator-error').textContent).toMatch(
      /never look real/i,
    );
    expect(
      screen.getByTestId('simulator-verdict-card').textContent,
    ).toMatch(/No simulator verdict yet/);
  });
});
