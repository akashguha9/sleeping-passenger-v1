/**
 * Vitest specs for `SimulatorVerdictCard`.
 *
 * The simulator never emits a naked Buy / No-Buy — this card must always
 * render the breakdown (grip, crash, aero, meal box, driver) and the
 * advisory-only / execution-locked language.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import SimulatorVerdictCard, {
  type SimulatorDecision,
} from '@/components/SimulatorVerdictCard';

const DECISION: SimulatorDecision = {
  ticker: 'GRIDCO',
  theme: 'ai_grid_buildout',
  circuit: 'mid_cap',
  final_state: 'watchlist',
  final_candidate_score: 52.6,
  decision_reason:
    "Score 52.6/100 on circuit 'mid_cap' with all gates passed; state 'watchlist'. ADVISORY_ONLY.",
  signal_compound: 'hard',
  signal_grip: 87,
  crash_risk: 0.32,
  crash_density: 0.0,
  downforce: 0.78,
  drag: 0.16,
  aero_efficiency: 4.88,
  dirty_air: 0.7,
  driver_permission: 1.0,
  driver_status: 'clean',
  meal_box_status: { complete: true, missing_items: [] },
  gate_results: { crash_gate: true, meal_box_gate: true },
};

describe('SimulatorVerdictCard', () => {
  it('renders the full breakdown, never a naked score', () => {
    render(<SimulatorVerdictCard decision={DECISION} />);
    const card = screen.getByTestId('simulator-verdict-card');
    expect(card.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getByTestId('simulator-final-state').textContent).toMatch(
      /WATCHLIST/,
    );
    expect(card.textContent).toMatch(/GRIDCO/);
    expect(card.textContent).toMatch(/Grip:/);
    expect(card.textContent).toMatch(/Crash risk:/);
    expect(card.textContent).toMatch(/Aero eff\./);
    expect(card.textContent).toMatch(/Driver:/);
    expect(card.textContent).toMatch(/Advisory only/i);
    expect(card.textContent).toMatch(/No orders placed/i);
  });

  it('surfaces failed gates and missing meal-box items', () => {
    render(
      <SimulatorVerdictCard
        decision={{
          ...DECISION,
          final_state: 'active_watch',
          meal_box_status: { complete: false, missing_items: ['invalidation'] },
          gate_results: { crash_gate: true, meal_box_gate: false },
        }}
      />,
    );
    expect(screen.getByTestId('simulator-meal-box').textContent).toMatch(
      /missing invalidation/,
    );
    expect(screen.getByTestId('simulator-failed-gates').textContent).toMatch(
      /meal_box_gate/,
    );
  });

  it('renders a quiet empty state without a decision', () => {
    render(<SimulatorVerdictCard decision={null} />);
    expect(
      screen.getByTestId('simulator-verdict-card').textContent,
    ).toMatch(/No simulator verdict yet/);
  });

  it('keeps conservative copy for the strongest state', () => {
    render(
      <SimulatorVerdictCard
        decision={{ ...DECISION, final_state: 'high_conviction_candidate' }}
      />,
    );
    // Even the best state must read as review, never as an instruction.
    expect(screen.getByTestId('simulator-final-state').textContent).toMatch(
      /REVIEW/,
    );
  });
});
