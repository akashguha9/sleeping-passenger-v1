/**
 * Vitest specs for `TitrationBadge` — the Market Titration state pill on
 * inbox cards.  Mirrors the ReactorBadge spec conventions: advisory-only
 * copy, safe fallbacks for unknown states, no execution affordances.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TitrationBadge } from '@/components/TitrationBadge';

describe('TitrationBadge', () => {
  it('renders the canonical titration state label', () => {
    render(<TitrationBadge state="PRIMED" />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.textContent).toMatch(/PRIMED/);
    expect(badge.getAttribute('data-execution-permission')).toBe('false');
  });

  it('renders an UNKNOWN label when state is missing', () => {
    render(<TitrationBadge />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.textContent).toMatch(/UNKNOWN/);
  });

  it('renders an UNKNOWN label when state is unrecognised', () => {
    render(<TitrationBadge state="some-future-state" />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.textContent).toMatch(/UNKNOWN/);
  });

  it('shows a signed pre-alpha gap when provided', () => {
    render(<TitrationBadge state="PRE_ALPHA_WATCH" preAlphaGap={0.31} />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.textContent).toMatch(/\+0\.31/);
  });

  it('shows a negative gap without a plus sign', () => {
    render(<TitrationBadge state="CROWDED" preAlphaGap={-0.12} />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.textContent).toMatch(/-0\.12/);
  });

  it('omits the gap for null / non-finite values', () => {
    render(<TitrationBadge state="LOADING" preAlphaGap={null} />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.textContent).toBe('Titration: LOADING');
  });

  it('advisory-only tooltip never implies permission', () => {
    render(<TitrationBadge state="PRIMED" />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.getAttribute('title')).toMatch(/advisory only/i);
    expect(badge.getAttribute('title')).toMatch(/NOT a probability/);
  });

  it('maps FALSE_TRANSITION_RISK to the shortened warning label', () => {
    render(<TitrationBadge state="FALSE_TRANSITION_RISK" />);
    const badge = screen.getByTestId('titration-badge');
    expect(badge.getAttribute('data-titration-state')).toBe('FALSE_TRANSITION');
  });
});
