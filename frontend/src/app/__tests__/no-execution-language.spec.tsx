/**
 * Runnable advisory-language guard (the executable counterpart to the
 * Playwright e2e suite, which needs a browser binary). Renders the key
 * operator pages with a mocked apiClient and asserts no execution
 * call-to-action text appears anywhere in the rendered DOM.
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

const FORBIDDEN = /\b(execute order|place order|auto-buy|auto-sell|broker trade|send order|trade now)\b/i;

vi.mock('@/lib/apiClient', () => ({
  getDiagnosticsCockpit: vi.fn().mockResolvedValue(null),
  getRealMoneyReadiness: vi.fn().mockResolvedValue({
    allowed_mode: 'TINY_MANUAL_PROBE_ONLY', readiness_score: 6.5, readiness_max: 8,
    reason: 'Scores are not calibrated enough to size from. Tiny manual probes only.',
  }),
  getSignals: vi.fn().mockResolvedValue({
    data: {
      operation: 'list_inbox_items', item_count: 0, items: [],
      fabric_bull_state: 'NEUTRAL', fabric_stats: {},
      score_calibration: { calibration_status: 'UNCALIBRATED', sample_size: 0, score_should_drive_sizing: false },
      advisory_status: 'ADVISORY_ONLY', human_review_required: true,
      execution_mode: 'HUMAN_ONLY', ai_execution_count: 0,
    },
    isMock: false,
  }),
  getSignalsDiagnostics: vi.fn().mockResolvedValue({ data: {}, isMock: false }),
  getManualTrades: vi.fn().mockResolvedValue({
    operation: 'list_manual_trades', trade_count: 1, trades: [{
      trade_id: 'MT_1', event_id: 'EV', ticker: 'AAPL', side: 'BUY', quantity: 5, price: 200,
      leverage: 2.0, leverage_ceiling: 1.0, leverage_breach: true,
      leverage_policy_severity: 'POLICY_BREACH', jurisdiction_group: 'REST_OF_WORLD',
      jurisdiction_resolution_source: 'SECURITIES_MASTER',
      leverage_policy_reason: '2x exceeds the 1x ceiling.', executed_at: '2026-01-01T00:00:00Z',
      thesis: 'manual record', notes: '', logged_by: 'human', execution_mode: 'HUMAN_ONLY',
      ai_execution_count: 0, advisory_status: 'ADVISORY_ONLY', human_review_required: true,
      broker_order_id: 'NONE', broker_api_called: false, created_via: 'manual_trade_log',
    }],
  }),
  getReconciliationQueue: vi.fn().mockResolvedValue({ items: [], summary: {}, advisory_status: 'ADVISORY_ONLY' }),
  getSourceHealthSummary: vi.fn().mockResolvedValue(null),
  getSourceHealth: vi.fn().mockResolvedValue(null),
  getLiveSourcesStatus: vi.fn().mockResolvedValue(null),
  getDbStatus: vi.fn().mockResolvedValue(null),
  checkHealth: vi.fn().mockResolvedValue(null),
  postManualTrade: vi.fn(),
  hasStoredApiToken: vi.fn().mockReturnValue(false),
  setStoredApiToken: vi.fn(),
  clearStoredApiToken: vi.fn(),
  getStoredApiToken: vi.fn().mockReturnValue(null),
  ApiHttpError: class extends Error {},
  ApiTokenRequiredError: class extends Error {},
}));

import CockpitPage from '@/app/cockpit/page';
import ManualTradeLogPage from '@/app/manual-trade-log/page';

describe('no execution language on rendered operator pages', () => {
  it('cockpit page has no execution call-to-action', async () => {
    const { container } = render(<CockpitPage />);
    await waitFor(() => expect(screen.getByTestId('advisory-banner')).toBeTruthy());
    expect(FORBIDDEN.test(container.textContent ?? '')).toBe(false);
  });

  it('manual trade log page has no execution call-to-action', async () => {
    const { container } = render(<ManualTradeLogPage />);
    await waitFor(() => expect(screen.getByText('AAPL')).toBeTruthy());
    expect(FORBIDDEN.test(container.textContent ?? '')).toBe(false);
    // breach + jurisdiction source surfaced
    expect(screen.getByTestId('leverage-breach-warning')).toBeTruthy();
    expect(/SECURITIES_MASTER/.test(container.textContent ?? '')).toBe(true);
  });
});
