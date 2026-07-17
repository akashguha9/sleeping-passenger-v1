/**
 * Vitest spec for the Simulation Lab page.
 *
 * Covers the loading lifecycle (must resolve to a finite state), the
 * advisory / no-execution language contract, and rendering a council result
 * with the SIMULATED_ONLY honesty markers. Record-keeping surface only — no
 * broker/execution path exists on this page.
 */
// @ts-ignore
import { render, screen, waitFor } from '@testing-library/react';
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
}));

import {
  getSimulationHealth,
  getSimulationEngines,
  getSimulationScenarios,
  getSimulationRuns,
} from '@/lib/apiClient';
import SimulationLabPage from '@/app/simulation-lab/page';

const mockHealth = getSimulationHealth as unknown as ReturnType<typeof vi.fn>;
const mockEngines = getSimulationEngines as unknown as ReturnType<typeof vi.fn>;
const mockScenarios = getSimulationScenarios as unknown as ReturnType<typeof vi.fn>;
const mockRuns = getSimulationRuns as unknown as ReturnType<typeof vi.fn>;

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

describe('SimulationLabPage', () => {
  beforeEach(() => {
    mockHealth.mockReset();
    mockEngines.mockReset();
    mockScenarios.mockReset();
    mockRuns.mockReset();
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
});
