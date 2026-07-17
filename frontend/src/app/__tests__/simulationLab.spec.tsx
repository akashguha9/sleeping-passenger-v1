/**
 * Vitest spec for the Simulation Lab page.
 *
 * Covers the loading lifecycle (must resolve to a finite state), the
 * advisory / no-execution language contract, and rendering a council result
 * with the SIMULATED_ONLY honesty markers. Record-keeping surface only — no
 * broker/execution path exists on this page.
 */
// @ts-ignore
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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
  getSimulationHealth: vi.fn(),
  getSimulationEngines: vi.fn(),
  getSimulationScenarios: vi.fn(),
  getSimulationRuns: vi.fn(),
  postSimulationRun: vi.fn(),
  postSimulationRatings: vi.fn(),
}));

import {
  getSimulationHealth,
  getSimulationEngines,
  getSimulationScenarios,
  getSimulationRuns,
  postSimulationRatings,
} from '@/lib/apiClient';
import SimulationLabPage from '@/app/simulation-lab/page';

const mockHealth = getSimulationHealth as unknown as ReturnType<typeof vi.fn>;
const mockEngines = getSimulationEngines as unknown as ReturnType<typeof vi.fn>;
const mockScenarios = getSimulationScenarios as unknown as ReturnType<typeof vi.fn>;
const mockRuns = getSimulationRuns as unknown as ReturnType<typeof vi.fn>;
const mockRatings = postSimulationRatings as unknown as ReturnType<typeof vi.fn>;

const HEALTH = {
  advisory_status: 'ADVISORY_ONLY',
  execution_gate: 'LOCKED',
  ai_execution_count: 0,
  broker_api_called: false,
  human_review_required: true,
  sil_enabled: true,
  feature_flags: {},
  engine_count: 18,
  engines_available_now: [],
  engines_available_count: 0,
  manifest_version: 'v',
  note: 'ok',
};

const ENGINES = {
  ...HEALTH,
  manifest_version: 'v',
  summary: { engine_count: 18, by_mode: {}, honesty_note: 'No proprietary engine is embedded.' },
  engines: [
    { engine: 'MuJoCo', domain: 'PHYSICS', integration_mode: 'CONCEPT_TRANSPLANT',
      final_decision: 'CONCEPT_TRANSPLANT', license: 'Apache-2.0', python313: 'yes',
      windows: 'yes', transplanted_into: 'physics', reason: 'x' },
  ],
  availability: { available_now: [], available_count: 0 },
};

const SCENARIOS = { ...HEALTH, count: 32, default_scenario_ids: [], scenarios: [] };
const RUNS = { ...HEALTH, count: 0, runs: [] };

const RATINGS = {
  ...HEALTH,
  ok: true,
  run_id: 'SIM_x',
  ticker: 'RELIANCE.NS',
  five_scores: {
    role_adjusted_performance: 7.7,
    engineering_quality: 8.8,
    decision_utility: 5.3,
    empirical_validation: 1.0,
    whole_mvp_maturity: 5.8,
    empirical_sample_size: 0,
    components_scored: 18,
    components_runtime_reached: 18,
    note: 'Five scores are separate by design.',
    whole_mvp_detail: {},
  },
  ratings: [
    { component_id: 'council', component_name: 'Council', role_template: 'COUNCIL',
      role_adjusted_performance: 8.2, engineering_quality: 8.5, decision_utility: 8.0,
      empirical_validation: 1.0, rating_confidence: 0.6, support: 'SUPPORTED',
      evidence_grade: 'MEASURED', honest_ceiling: 9.3, runtime_reached: true,
      empirically_validated: false, severe_events: 0, caps_applied: [], reasons: [],
      dimension_scores: [] },
  ],
  contribution_events: [
    { event_id: 'EV_1', component_id: 'council', event_type: 'risk_block_overrode_aggregate',
      direction: 'POSITIVE', severity: 'MAJOR', event_class: 'PREVENTION',
      target_dimension: 'risk_interception', counterfactual_impact: 'x', evidence: 'risk_block',
      affected_final_result: true },
  ],
  context_difficulty: { score: 0.33, band: 'EASY', dominant_factor: 'volatility' },
  ablation: { most_valuable_lens: 'RACING', quietest_valuable_lens: 'RACING',
    shapley_exact: true, lens_contributions: [] },
  council_vote: 'AVOID',
  evidence_label: 'SIMULATED_ONLY',
  simulation_only: false,
};

describe('SimulationLabPage', () => {
  beforeEach(() => {
    mockHealth.mockReset();
    mockEngines.mockReset();
    mockScenarios.mockReset();
    mockRuns.mockReset();
    mockRatings.mockReset();
  });

  it('resolves out of the loading state when the backend responds', async () => {
    mockHealth.mockResolvedValue(HEALTH);
    mockEngines.mockResolvedValue(ENGINES);
    mockScenarios.mockResolvedValue(SCENARIOS);
    mockRuns.mockResolvedValue(RUNS);

    render(<SimulationLabPage />);
    await waitFor(() => {
      expect(screen.queryByTestId('sim-loading')).toBeNull();
    });
    expect(screen.getByTestId('simulation-lab')).toBeTruthy();
  });

  it('shows the SIMULATED_ONLY / no-execution honesty markers', async () => {
    mockHealth.mockResolvedValue(HEALTH);
    mockEngines.mockResolvedValue(ENGINES);
    mockScenarios.mockResolvedValue(SCENARIOS);
    mockRuns.mockResolvedValue(RUNS);

    const { container } = render(<SimulationLabPage />);
    await waitFor(() => expect(screen.queryByTestId('sim-loading')).toBeNull());
    // A what-if / simulated-only marker element is present.
    expect(container.querySelector('[data-simulated-only="true"]')).toBeTruthy();
    // No forbidden execution language anywhere in the rendered page.
    const text = container.textContent || '';
    expect(/trade now|place order|execute order|auto-buy|auto-sell|broker trade/i.test(text)).toBe(false);
  });

  it('falls back to a finite (offline) state when the backend is null', async () => {
    mockHealth.mockResolvedValue(null);
    mockEngines.mockResolvedValue(null);
    mockScenarios.mockResolvedValue(null);
    mockRuns.mockResolvedValue(null);

    render(<SimulationLabPage />);
    await waitFor(() => expect(screen.queryByTestId('sim-loading')).toBeNull());
    expect(screen.getByText(/BACKEND OFFLINE/i)).toBeTruthy();
  });

  it('renders the five SEPARATE role-aware scores and keeps empirical low', async () => {
    mockHealth.mockResolvedValue(HEALTH);
    mockEngines.mockResolvedValue(ENGINES);
    mockScenarios.mockResolvedValue(SCENARIOS);
    mockRuns.mockResolvedValue(RUNS);
    mockRatings.mockResolvedValue(RATINGS);

    const { container } = render(<SimulationLabPage />);
    await waitFor(() => expect(screen.queryByTestId('sim-loading')).toBeNull());
    fireEvent.click(screen.getByTestId('run-ratings'));
    await waitFor(() => expect(screen.getByTestId('role-ratings')).toBeTruthy());

    // Five scores are shown as separate values (never one averaged number).
    const fiveScores = screen.getByTestId('five-scores');
    const text = fiveScores.textContent || '';
    expect(text).toContain('7.7');   // role-adjusted
    expect(text).toContain('1');     // empirical stays low
    // The role-ratings surface never grants execution.
    expect(container.querySelector('[data-execution-permission="false"]')).toBeTruthy();
    // Contribution-event audit trail is present.
    expect(screen.getByTestId('contribution-events')).toBeTruthy();
  });
});
