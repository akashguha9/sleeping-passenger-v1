/**
 * Vitest specs for `ConsentPanel` — present data, missing data, and the
 * no-execution language contract.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ConsentPanel, { type ConsentLedger } from '@/components/ConsentPanel';

const LEDGER: ConsentLedger = {
  evidence_reliability_score: 8.5,
  reliability_band: 'high',
  layer_scores: {
    consent_quality: 0.0,
    subscription_extraction: 9.5,
    claims_non_payment: 0.0,
    friction_tax: 6.2,
    regulatory_fragility: 7.1,
  },
  multipliers_applied: {
    revenue_quality_multiplier: 0.36,
    consent_safety_multiplier: 0.45,
    regulatory_safety_multiplier: 0.41,
    reliability_factor: 0.85,
  },
  penalties_applied: { friction_revenue_penalty: 2.6 },
  risk_caps_applied: [
    'severe[subscription_extraction] × reliability[high] caps state at watchlist',
  ],
  simulator_factors_added: { extractive_revenue: 0.6 },
  dark_pattern_chain: {
    score: 8.4,
    label: 'partial_chain',
    longest_consecutive_run: 5,
    stages_present: 5,
  },
  detected_terms: ['trotz kundigung abgebucht', 'inkasso', 'mahngebuhr'],
  recommendation_before_consent: 'active_watch',
  recommendation_after_consent: 'watchlist',
  score_before_consent: 59.5,
  score_after_consent: 4.2,
  warnings: [],
  rationale: ['consent adjustment: score 59.5 -> 4.2; state active_watch -> watchlist'],
  advisory_only_notice: 'ADVISORY_ONLY',
};

describe('ConsentPanel', () => {
  it('renders the downgrade effect, reliability, chain, and German terms', () => {
    render(<ConsentPanel ledger={LEDGER} revenueQualityLabel="extractive_risk" />);
    const panel = screen.getByTestId('consent-panel');
    expect(panel.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getByTestId('consent-effect').textContent).toMatch(
      /active_watch.*→.*watchlist/,
    );
    expect(screen.getByTestId('consent-reliability').textContent).toMatch(
      /8\.5\/10 \(high\)/,
    );
    expect(screen.getByTestId('consent-chain').textContent).toMatch(
      /longest run 5/,
    );
    expect(screen.getByTestId('consent-caps').textContent).toMatch(/watchlist/);
    expect(panel.textContent).toMatch(/trotz kundigung abgebucht/);
    expect(panel.textContent).toMatch(/not legal guilt/i);
    expect(panel.textContent).not.toMatch(/place order|execute trade|buy now/i);
  });

  it('renders an honest missing-data state', () => {
    render(<ConsentPanel ledger={null} />);
    expect(screen.getByTestId('consent-panel').textContent).toMatch(
      /insufficient data/i,
    );
    expect(screen.getByTestId('consent-panel').textContent).toMatch(
      /not evidence of cleanliness/i,
    );
  });

  it('shows no-material-change when consent had no effect', () => {
    render(
      <ConsentPanel
        ledger={{
          ...LEDGER,
          risk_caps_applied: [],
          recommendation_after_consent: 'active_watch',
          score_after_consent: 59.5,
          warnings: ['insufficient_data: thin evidence'],
        }}
      />,
    );
    expect(screen.getByTestId('consent-effect').textContent).toMatch(
      /no material change/,
    );
    expect(screen.getByTestId('consent-warnings').textContent).toMatch(
      /thin evidence/,
    );
  });
});
