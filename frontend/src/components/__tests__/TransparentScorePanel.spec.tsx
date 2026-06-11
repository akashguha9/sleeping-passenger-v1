/**
 * Vitest specs for `TransparentScorePanel` — glass-structure decomposition,
 * hard-rule visibility, missing-data state, and no-execution language.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import TransparentScorePanel, {
  type StrategyDecision,
} from '@/components/TransparentScorePanel';

const DECISION: StrategyDecision = {
  ticker: 'SOLID',
  decision_class: 'WATCHLIST',
  final_opportunity_score: 5.81,
  band: 'monitor_only',
  hard_rules_triggered: ['threshold_not_crossed'],
  positive_contributors: {
    node_payoff_matrix: 0.097,
    backhand_defence: 0.092,
    base_quality: 0.07,
  },
  penalties: { hype_penalty: 0.5, fake_outlier_penalty: 0 },
  decision_reason:
    'WATCHLIST: score 5.81/10; capped by hard rules. ADVISORY_ONLY.',
};

describe('TransparentScorePanel', () => {
  it('decomposes the verdict into contributors and penalties', () => {
    render(<TransparentScorePanel decision={DECISION} />);
    const panel = screen.getByTestId('transparent-score-panel');
    expect(panel.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getByTestId('strategy-class').textContent).toMatch(
      /WATCHLIST \(research class\)/,
    );
    expect(panel.textContent).toMatch(/node payoff matrix/);
    expect(panel.textContent).toMatch(/hype penalty/);
    expect(screen.getByTestId('strategy-hard-rules').textContent).toMatch(
      /threshold_not_crossed/,
    );
    expect(panel.textContent).toMatch(/not an instruction/i);
    expect(panel.textContent).not.toMatch(/place order|execute|trade now/i);
  });

  it('renders an honest empty state', () => {
    render(<TransparentScorePanel decision={null} />);
    expect(
      screen.getByTestId('transparent-score-panel').textContent,
    ).toMatch(/never a naked score/i);
  });

  it('shows none when no penalties apply', () => {
    render(
      <TransparentScorePanel
        decision={{ ...DECISION, penalties: {}, hard_rules_triggered: [] }}
      />,
    );
    expect(
      screen.getByTestId('transparent-score-panel').textContent,
    ).toMatch(/none/);
  });
});
