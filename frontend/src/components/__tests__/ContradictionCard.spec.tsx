/**
 * Vitest specs for `ContradictionCard` — hold rendering, citations,
 * missing-data state, and no-execution language.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ContradictionCard, {
  type UnifiedVerdict,
} from '@/components/ContradictionCard';

const VERDICT: UnifiedVerdict = {
  final_state: 'reject',
  state_before_unification: 'active_watch',
  unified_score_10: 0,
  contradiction_hold: true,
  engines_present: ['simulator', 'strategy'],
  engine_states: { simulator: 'active_watch', strategy: 'REJECT' },
  contradictions: [
    {
      kind: 'physics_vs_strategy',
      severity: 0.75,
      left: 'simulator: active_watch (59.5/100)',
      right: 'strategy: REJECT (0.00/10)',
      resolution: 'most conservative engine wins; verdict held for human review',
    },
  ],
  strategy_credibility: 0.06,
  strategy_upgrade_blocked: true,
  rationale: ['conservative-wins: active_watch -> reject'],
};

describe('ContradictionCard', () => {
  it('renders the hold, the demotion, and cited contradictions', () => {
    render(<ContradictionCard verdict={VERDICT} />);
    const card = screen.getByTestId('contradiction-card');
    expect(card.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getByTestId('unified-state').textContent).toMatch(
      /active_watch → reject.*CONTRADICTION HOLD/,
    );
    expect(screen.getByTestId('contradiction-list').textContent).toMatch(
      /physics_vs_strategy/,
    );
    expect(screen.getByTestId('strategy-credibility').textContent).toMatch(
      /0\.06.*upgrade blocked/,
    );
    expect(card.textContent).toMatch(/Most conservative engine wins/i);
    expect(card.textContent).not.toMatch(/place order|execute|trade now/i);
  });

  it('renders agreement without hold styling', () => {
    render(
      <ContradictionCard
        verdict={{
          ...VERDICT,
          final_state: 'active_watch',
          contradiction_hold: false,
          contradictions: [],
          rationale: ['engines agree; no unification adjustment needed'],
        }}
      />,
    );
    expect(screen.getByTestId('unified-state').textContent).toBe(
      'active_watch',
    );
  });

  it('renders an honest missing state', () => {
    render(<ContradictionCard verdict={null} />);
    expect(screen.getByTestId('contradiction-card').textContent).toMatch(
      /No unified verdict yet/,
    );
  });
});
