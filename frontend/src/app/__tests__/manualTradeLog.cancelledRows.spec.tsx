/**
 * Vitest spec for the Manual Trade Log "Previously Logged" panel
 * cancelled-row filter.
 *
 * Background — the operator reported an ASDC duplicate card that kept
 * appearing in the Previously Logged column after they cancelled it
 * from the Reconciliation tab.  The cancellation set
 * reconciliation_status=CANCELLED_DUPLICATE in the DB, but the page
 * only filtered fake-marker rows; cancelled-but-otherwise-canonical
 * rows still rendered.
 *
 * This spec pins the new contract: cancelled rows are hidden from the
 * active card list and a separate count exposes the audit history.
 * Record-keeping only — no broker call paths are touched.
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
  // Surfaces consumed by ManualTradeLogPage + its child panels.
  // SourceHealthWarnings calls getSourceHealthSummary, LocalApiTokenPanel
  // calls checkHealth, ManualTradeLogForm calls postManualTrade.  All
  // mocked to safe no-ops so the page renders without async errors.
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
  ApiHttpError: class ApiHttpError extends Error {
    status: number;
    reason?: string;
    constructor(status: number, message: string, reason?: string) {
      super(message);
      this.status = status;
      this.reason = reason;
    }
  },
  ApiTokenRequiredError: class ApiTokenRequiredError extends Error {
    status: number;
    constructor(status = 401) {
      super('token');
      this.status = status;
    }
  },
}));

import {
  getManualTrades,
  getReconciliationQueue,
} from '@/lib/apiClient';
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

function asdcRow(extras: Record<string, unknown> = {}) {
  return {
    trade_id: 'MT_asdc',
    event_id: 'EV',
    ticker: 'ASDC',
    side: 'BUY',
    quantity: 11,
    price: 12321,
    leverage: 1.0,
    executed_at: '2026-05-18T21:00:37Z',
    thesis: 'gibberish',
    notes: '',
    logged_by: 'human',
    execution_mode: 'HUMAN_ONLY',
    ai_execution_count: 0,
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    broker_order_id: 'NONE',
    broker_api_called: false,
    created_via: 'manual_trade_log',
    ai_model_used: 'GPT-5.5',
    ...extras,
  };
}

describe('ManualTradeLogPage — cancelled rows are hidden but counted', () => {
  beforeEach(() => {
    mockTrades.mockReset();
    mockQueue.mockReset();
    mockQueue.mockResolvedValue(emptyQueue());
  });

  it('hides CANCELLED_DUPLICATE rows from Previously Logged cards', async () => {
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 1,
      trades: [asdcRow({ reconciliation_status: 'CANCELLED_DUPLICATE' })],
    });
    render(<ManualTradeLogPage />);
    await waitFor(() =>
      expect(screen.queryByText(/Loading…/)).not.toBeInTheDocument(),
    );
    // The ticker should NOT render as an active card.
    expect(screen.queryByText('ASDC')).not.toBeInTheDocument();
    // The count chip should report 0 active + 1 cancelled (audit-only).
    const count = screen.getByTestId('manual-trade-count');
    expect(count.textContent ?? '').toMatch(/0 active/);
    expect(count.textContent ?? '').toMatch(/1 cancelled/);
  });

  it('still renders active (non-cancelled) rows alongside the cancelled audit count', async () => {
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 2,
      trades: [
        asdcRow({
          trade_id: 'MT_active',
          ticker: 'MSFT',
          reconciliation_status: '',
          thesis: 'real operator reasoning that does not match marker rules',
        }),
        asdcRow({ reconciliation_status: 'CANCELLED_LOG' }),
      ],
    });
    render(<ManualTradeLogPage />);
    await waitFor(() =>
      expect(screen.queryByText(/Loading…/)).not.toBeInTheDocument(),
    );
    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.queryByText('ASDC')).not.toBeInTheDocument();
    const count = screen.getByTestId('manual-trade-count');
    expect(count.textContent ?? '').toMatch(/1 active/);
    expect(count.textContent ?? '').toMatch(/1 cancelled/);
  });

  it('renders a plain numeric count when no cancelled rows exist', async () => {
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 0,
      trades: [],
    });
    render(<ManualTradeLogPage />);
    await waitFor(() =>
      expect(screen.queryByText(/Loading…/)).not.toBeInTheDocument(),
    );
    const count = screen.getByTestId('manual-trade-count');
    expect(count.textContent ?? '').toBe('0');
  });
});
