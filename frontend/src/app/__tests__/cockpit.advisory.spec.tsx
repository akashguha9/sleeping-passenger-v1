/**
 * Vitest spec for the Operator Cockpit advisory-only contract.
 *
 * The cockpit aggregates closed-loop diagnostics. It must:
 *   * render the advisory-only safety banner ("Advisory diagnostics only",
 *     "Human execution required", "No broker action is performed");
 *   * surface the closed-loop / truth-purity / defensive-alpha panels;
 *   * introduce NO execution affordances — no buy/sell/execute/place-order
 *     buttons or copy.
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
  getDiagnosticsCockpit: vi.fn(),
  // Cockpit also fetches the real-money readiness mode. Mock to a safe no-op.
  getRealMoneyReadiness: vi.fn().mockResolvedValue(null),
  getCalibrationMap: vi.fn().mockResolvedValue(null),
}));

import { getDiagnosticsCockpit } from '@/lib/apiClient';
import CockpitPage from '@/app/cockpit/page';

const mockCockpit = getDiagnosticsCockpit as unknown as ReturnType<typeof vi.fn>;

function payload() {
  return {
    report: 'operator_cockpit',
    advisory_disclaimer: 'Advisory diagnostics only. Human execution required.',
    closed_loop: {
      closed_loop_coverage: 1.0,
      signals_without_outcomes: 3,
      manual_trades_without_reconciliation: 0,
      closed_losses_without_moltbook: 0,
      unresolved_repair_debt: 0,
    },
    learning_efficiency: {
      lesson_conversion_rate: 1.0,
      repeat_error_rate: 0.0,
      learning_efficiency_score: 1.0,
    },
    truth_purity: { truth_purity_score: 1.0, fake_rows_detected: 0, release_gate_passed: true },
    source_independence: { cohort_count: 2, flagged_cohorts: ['NVDA'] },
    broken_windows: {
      repair_debt_score: 0.0,
      release_gate_impact: 'CLEAR',
      recommended_next_repair: 'No repair debt — discipline intact.',
    },
    defensive_alpha: {
      total_defensive_events: 5,
      fake_data_rows_blocked: 0,
      closed_losses_captured_as_lessons: 2,
    },
    invariants: {
      advisory_only_verified: true,
      human_execution_verified: true,
      broker_api_called_false_verified: true,
      ai_execution_count_zero_verified: true,
    },
    advisory_status: 'ADVISORY_ONLY',
    broker_api_called: false,
    ai_execution_count: 0,
  };
}

describe('Operator Cockpit', () => {
  beforeEach(() => {
    mockCockpit.mockReset();
  });

  it('renders the advisory-only safety language', async () => {
    mockCockpit.mockResolvedValue(payload());
    render(<CockpitPage />);
    await waitFor(() => expect(screen.getByTestId('advisory-banner')).toBeTruthy());
    const banner = screen.getByTestId('advisory-banner').textContent ?? '';
    expect(banner).toMatch(/advisory diagnostics only/i);
    expect(banner).toMatch(/human execution required/i);
    expect(banner).toMatch(/no broker action is performed/i);
  });

  it('shows the diagnostic panels', async () => {
    mockCockpit.mockResolvedValue(payload());
    render(<CockpitPage />);
    await waitFor(() => expect(screen.getByText('Closed Loop Health')).toBeTruthy());
    expect(screen.getByText('Truth Purity')).toBeTruthy();
    expect(screen.getByText('Defensive Alpha')).toBeTruthy();
    expect(screen.getByText('Pre-Real-Money Readiness')).toBeTruthy();
  });

  it('introduces no execution affordances', async () => {
    mockCockpit.mockResolvedValue(payload());
    const { container } = render(<CockpitPage />);
    await waitFor(() => expect(screen.getByText('Closed Loop Health')).toBeTruthy());
    // No actionable buttons at all on this read-only diagnostics page.
    expect(container.querySelectorAll('button').length).toBe(0);
    const text = (container.textContent ?? '').toLowerCase();
    for (const forbidden of [
      'place order', 'execute trade', 'trade now', 'buy now', 'sell now',
      'auto-trade', 'broker order', 'broker connected',
    ]) {
      expect(text.includes(forbidden)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// Kanté Task 6 — diagnostics integrity: DEGRADED / partial failures / cache.
// ---------------------------------------------------------------------------

function degradedPayload() {
  return {
    ...payload(),
    status: 'DEGRADED',
    degraded_state: 'DEGRADED',
    cache_status: 'miss_recomputed',
    cache_role: 'derived_non_canonical',
    canonical_truth_source: 'sqlite',
    generated_at_utc: '2026-05-22T00:00:00Z',
    diagnostics_health: 0.6,
    partial_failures: [
      {
        subreport: 'broken_windows',
        status: 'DEGRADED',
        error_type: 'OperationalError',
        safe_recovery_command: 'python scripts/broken_windows_report.py',
      },
    ],
    auth_guard_status: 'PASS',
    mutation_guard_coverage: 1.0,
    mutation_guard_release_impact: 'PASS',
    mutation_scripts_unguarded_count: 0,
  };
}

describe('Operator Cockpit — diagnostics integrity', () => {
  beforeEach(() => {
    mockCockpit.mockReset();
  });

  it('shows the DEGRADED status visibly', async () => {
    mockCockpit.mockResolvedValue(degradedPayload());
    render(<CockpitPage />);
    await waitFor(() => expect(screen.getByTestId('diagnostics-integrity-panel')).toBeTruthy());
    expect(screen.getByTestId('diagnostics-status').textContent).toMatch(/DEGRADED/);
  });

  it('shows partial failures with error type and recovery command', async () => {
    mockCockpit.mockResolvedValue(degradedPayload());
    render(<CockpitPage />);
    await waitFor(() => expect(screen.getByTestId('partial-failures')).toBeTruthy());
    const text = screen.getByTestId('partial-failures').textContent ?? '';
    expect(text).toMatch(/broken_windows/);
    expect(text).toMatch(/OperationalError/);
    expect(screen.getByTestId('recovery-command').textContent).toMatch(
      /python scripts\/broken_windows_report\.py/,
    );
  });

  it('shows cache status, derived_non_canonical role and canonical truth', async () => {
    mockCockpit.mockResolvedValue(degradedPayload());
    const { container } = render(<CockpitPage />);
    await waitFor(() => expect(screen.getByTestId('diagnostics-integrity-panel')).toBeTruthy());
    const text = container.textContent ?? '';
    expect(text).toMatch(/miss_recomputed/);
    expect(text).toMatch(/derived_non_canonical/);
    expect(text).toMatch(/sqlite/);
  });

  it('shows guard coverage and mutation guard impact', async () => {
    mockCockpit.mockResolvedValue(degradedPayload());
    const { container } = render(<CockpitPage />);
    await waitFor(() => expect(screen.getByTestId('diagnostics-integrity-panel')).toBeTruthy());
    const text = container.textContent ?? '';
    expect(text).toMatch(/Guard coverage/);
    expect(text).toMatch(/Mutation guard/);
  });

  it('keeps the advisory banner and adds no execution affordances when degraded', async () => {
    mockCockpit.mockResolvedValue(degradedPayload());
    const { container } = render(<CockpitPage />);
    await waitFor(() => expect(screen.getByTestId('advisory-banner')).toBeTruthy());
    expect(container.querySelectorAll('button').length).toBe(0);
    const text = (container.textContent ?? '').toLowerCase();
    for (const forbidden of ['place order', 'execute trade', 'buy now', 'sell now']) {
      expect(text.includes(forbidden)).toBe(false);
    }
  });
});
