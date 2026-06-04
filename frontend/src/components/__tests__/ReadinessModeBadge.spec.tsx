/**
 * Vitest spec for ReadinessModeBadge + interpretReadiness.
 *
 * Must render the allowed-mode in plain language, carry advisory data
 * attributes, and never emit execution / buy / sell / order language.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { ReadinessModeBadge } from '@/components/ReadinessModeBadge';
import { interpretReadiness } from '@/lib/realMoneyReadiness';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

describe('interpretReadiness', () => {
  it('defaults unknown/missing to SCALE_BLOCKED', () => {
    expect(interpretReadiness(undefined).mode).toBe('SCALE_BLOCKED');
    expect(interpretReadiness({}).mode).toBe('SCALE_BLOCKED');
  });

  it('maps each mode', () => {
    expect(interpretReadiness({ allowed_mode: 'PAPER_ONLY' }).mode).toBe('PAPER_ONLY');
    expect(interpretReadiness({ allowed_mode: 'TINY_MANUAL_PROBE_ONLY' }).mode).toBe(
      'TINY_MANUAL_PROBE_ONLY',
    );
    expect(interpretReadiness({ allowed_mode: 'MANUAL_REAL_MONEY_READY' }).mode).toBe(
      'MANUAL_REAL_MONEY_READY',
    );
  });
});

describe('ReadinessModeBadge', () => {
  it('renders tiny-probe mode with do-not-size language', () => {
    render(
      <ReadinessModeBadge
        readiness={{
          allowed_mode: 'TINY_MANUAL_PROBE_ONLY',
          readiness_score: 6.5,
          reason: 'Scores are not calibrated enough to size from. Tiny manual probes only.',
        }}
      />,
    );
    const el = screen.getByTestId('readiness-mode-badge');
    expect(el.getAttribute('data-allowed-mode')).toBe('TINY_MANUAL_PROBE_ONLY');
    expect(el.getAttribute('data-advisory-only')).toBe('true');
    expect(el.getAttribute('data-execution-permission')).toBe('false');
    expect(/not calibrated enough to size/i.test(el.textContent ?? '')).toBe(true);
    expect(/6\.5\/7/.test(el.textContent ?? '')).toBe(true);
  });

  it('never emits execution / broker language in any mode', () => {
    for (const mode of [
      'SCALE_BLOCKED',
      'PAPER_ONLY',
      'TINY_MANUAL_PROBE_ONLY',
      'MANUAL_REAL_MONEY_READY',
    ]) {
      const { container, unmount } = render(
        <ReadinessModeBadge readiness={{ allowed_mode: mode }} />,
      );
      const text = container.textContent ?? '';
      expect(/\b(buy|sell|execute order|place order|broker trade|send order|auto-buy|auto-sell)\b/i.test(text)).toBe(false);
      unmount();
    }
  });
});
