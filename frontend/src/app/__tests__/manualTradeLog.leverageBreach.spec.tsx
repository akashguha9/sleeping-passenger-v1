/**
 * Vitest spec: the Manual Trade Log surfaces a leverage POLICY BREACH on a
 * recorded trade that exceeded its jurisdiction ceiling. The row is still
 * shown (journal, not an execution blocker) but the breach is visible and
 * uses advisory wording only — no execution / buy / sell language.
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
  getManualTrades: vi.fn(),
  getReconciliationQueue: vi.fn(),
  getSourceHealthSummary: vi.fn().mockResolvedValue(null),
  getSourceHealth: vi.fn().mockResolvedValue(null),
  getLiveSourcesStatus: vi.fn().mockResolvedValue(null),
  getDbStatus: vi.fn().mockResolvedValue(null),
  checkHealth: vi.fn().mockResolvedValue(null),
  postManualTrade: vi.fn().mockResolvedValue({ trade_id: 'MT_X' }),
  hasStoredApiToken: vi.fn().mockReturnValue(false),
  setStoredApiToken: vi.fn(),
  clearStoredApiToken: vi.fn(),
  getStoredApiToken: vi.fn().mockReturnValue(null),
  ApiHttpError: class ApiHttpError extends Error {},
  ApiTokenRequiredError: class ApiTokenRequiredError extends Error {},
}));

import { getManualTrades, getReconciliationQueue } from '@/lib/apiClient';
import ManualTradeLogPage from '@/app/manual-trade-log/page';

const mockTrades = getManualTrades as unknown as ReturnType<typeof vi.fn>;
const mockQueue = getReconciliationQueue as unknown as ReturnType<typeof vi.fn>;

function emptyQueue() {
  return {
    report: 'reconciliation_queue',
    db_path: '',
    db_available: true,
    items: [],
    summary: {
      unreconciled_count: 0,
      oldest_unreconciled_age_days: null,
      average_journal_completeness: 0,
      average_learning_readiness: 0,
      learning_ready_count: 0,
      missing_field_distribution: {},
      by_ticker: {},
      by_emotional_state: {},
      by_expected_horizon: {},
    },
    warnings: [],
    operator_action: '',
    advisory_disclaimer: '',
    generated_at: '',
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    execution_permission: false,
    can_execute: false,
  };
}

function breachRow() {
  return {
    trade_id: 'MT_breach',
    event_id: 'EV',
    ticker: 'AAPL',
    side: 'BUY',
    quantity: 10,
    price: 200,
    leverage: 2.0,
    leverage_ceiling: 1.0,
    leverage_breach: true,
    leverage_policy_severity: 'POLICY_BREACH',
    leverage_policy_reason: '2x exceeds the 1x ceiling for REST_OF_WORLD.',
    jurisdiction_group: 'REST_OF_WORLD',
    executed_at: '2026-05-18T21:00:37Z',
    thesis: 'US equity at 2x leverage',
    notes: '',
    logged_by: 'human',
    execution_mode: 'HUMAN_ONLY',
    ai_execution_count: 0,
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    broker_order_id: 'NONE',
    broker_api_called: false,
    created_via: 'manual_trade_log',
  };
}

describe('ManualTradeLogPage — leverage breach surfacing', () => {
  beforeEach(() => {
    mockTrades.mockReset();
    mockQueue.mockReset();
    mockQueue.mockResolvedValue(emptyQueue());
  });

  it('renders a policy-breach warning for a breaching recorded trade', async () => {
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 1,
      trades: [breachRow()],
    });
    render(<ManualTradeLogPage />);
    await waitFor(() => {
      expect(screen.getByTestId('leverage-breach-warning')).toBeTruthy();
    });
    expect(screen.getByTestId('leverage-breach-chip')).toBeTruthy();
    const warn = screen.getByTestId('leverage-breach-warning');
    expect(/REST_OF_WORLD/.test(warn.textContent ?? '')).toBe(true);
    expect(/manual review required/i.test(warn.textContent ?? '')).toBe(true);
    // advisory wording only — no execution language
    expect(/\b(buy|sell|execute|broker|order)\b/i.test(warn.textContent ?? '')).toBe(false);
  });

  it('does not render a breach warning for a compliant trade', async () => {
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 1,
      trades: [{ ...breachRow(), leverage: 1.0, leverage_breach: false, leverage_policy_severity: 'NONE' }],
    });
    render(<ManualTradeLogPage />);
    await waitFor(() => {
      expect(screen.getByText('AAPL')).toBeTruthy();
    });
    expect(screen.queryByTestId('leverage-breach-warning')).toBeNull();
  });
});
