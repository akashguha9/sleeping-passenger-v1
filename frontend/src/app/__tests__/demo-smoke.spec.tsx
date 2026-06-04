/**
 * Demo readiness smoke test.
 *
 * Lightweight guarantee that the key demo pages import and are renderable
 * React components, and that the shared advisory-only badge renders advisory
 * (never execution) language. This catches import/build breakage in the demo
 * path without per-page API mocking.
 */
// @ts-ignore
import { render } from '@testing-library/react';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

import CockpitPage from '@/app/cockpit/page';
import LiveSignalsPage from '@/app/live-signals/page';
import ReconciliationPage from '@/app/reconciliation/page';
import ManualTradeLogPage from '@/app/manual-trade-log/page';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

describe('Demo readiness smoke', () => {
  it('all key demo pages import as renderable components', () => {
    for (const Page of [CockpitPage, LiveSignalsPage, ReconciliationPage, ManualTradeLogPage]) {
      expect(typeof Page).toBe('function');
    }
  });

  it('advisory-only badge renders advisory language, never execution verbs', () => {
    const { container } = render(<AdvisoryOnlyBadge />);
    const text = (container.textContent || '').toLowerCase();
    expect(text).toMatch(/advisory/);
    for (const forbidden of ['buy', 'sell', 'execute trade', 'place order', 'arbitrage']) {
      expect(text).not.toContain(forbidden);
    }
  });
});
