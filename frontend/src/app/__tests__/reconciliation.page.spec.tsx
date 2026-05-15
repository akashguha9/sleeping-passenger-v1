/**
 * Vitest spec for the Reconciliation page provenance contract.
 *
 * The Reconciliation tab is a human-manual-log-only surface.  These tests
 * pin the contract:
 *
 *   * The page calls getManualTrades with origin=manual_trade_log so the
 *     backend filters seed/demo/import rows out of the response.
 *   * Human manual logs (ICICIBANK.NS/BHARTIARTL.NS/SAP.DE) render in the
 *     awaiting-reconciliation list.
 *   * Empty state copy says "No human manual logs awaiting reconciliation".
 *   * Cancel Log button only renders for rows whose created_via is
 *     manual_trade_log.
 *   * Safety copy (no broker call, record-keeping only, AI executions = 0)
 *     remains visible.
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
  getReconciliationQueue: vi.fn(),
  getManualTrades: vi.fn(),
  getLearningCompleteness: vi.fn(),
  reconcileTrade: vi.fn(),
  cancelManualTradeLog: vi.fn(),
}));

import {
  getReconciliationQueue,
  getManualTrades,
  getLearningCompleteness,
} from '@/lib/apiClient';
import ReconciliationPage from '@/app/reconciliation/page';

const mockQueue = getReconciliationQueue as unknown as ReturnType<typeof vi.fn>;
const mockTrades = getManualTrades as unknown as ReturnType<typeof vi.fn>;
const mockLearning = getLearningCompleteness as unknown as ReturnType<typeof vi.fn>;

function emptyQueue(unreconciled = 0) {
  return {
    report: 'reconciliation_queue',
    db_path: '',
    db_available: true,
    items: [],
    summary: {
      unreconciled_count: unreconciled,
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
    operator_action: 'Reconcile each listed trade.',
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

function humanTrade(overrides: Record<string, unknown> = {}) {
  return {
    trade_id: 'MT_human1',
    event_id: 'EV',
    ticker: 'ICICIBANK.NS',
    side: 'BUY',
    quantity: 3.8908,
    price: 40.72,
    executed_at: '2026-05-14T23:31:00Z',
    thesis: 'India private-bank paper probe',
    notes: '',
    logged_by: 'human',
    execution_mode: 'HUMAN_ONLY',
    ai_execution_count: 0,
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    broker_order_id: 'NONE',
    broker_api_called: false,
    learning_ready: false,
    created_via: 'manual_trade_log',
    ...overrides,
  };
}

function emptyLearning() {
  return {
    report: 'learning_completeness_report',
    db_available: true,
    reconciled_count: 0,
    learning_complete_count: 0,
    learning_incomplete_count: 0,
    complete_count: 0,
    incomplete_count: 0,
    missing_field_distribution: {},
    items: [],
    warnings: [],
    operator_action: '',
    advisory_disclaimer: '',
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    execution_permission: false,
    can_execute: false,
    human_review_required: true,
  };
}

describe('ReconciliationPage — provenance contract', () => {
  beforeEach(() => {
    mockQueue.mockReset();
    mockTrades.mockReset();
    mockLearning.mockReset();
    mockQueue.mockResolvedValue(emptyQueue(0));
    mockLearning.mockResolvedValue(emptyLearning());
  });

  it('calls getManualTrades with origin=manual_trade_log', async () => {
    mockTrades.mockResolvedValue({ operation: 'list_manual_trades', trade_count: 0, trades: [] });
    render(<ReconciliationPage />);
    await waitFor(() => expect(mockTrades).toHaveBeenCalled());
    const [arg] = mockTrades.mock.calls[0];
    expect(arg).toEqual({ origin: 'manual_trade_log' });
  });

  it('renders the provenance note explaining the filter', async () => {
    mockTrades.mockResolvedValue({ operation: 'list_manual_trades', trade_count: 0, trades: [] });
    render(<ReconciliationPage />);
    await waitFor(() => expect(mockTrades).toHaveBeenCalled());
    const note = await screen.findByTestId('reconciliation-provenance-note');
    const text = (note.textContent ?? '').toLowerCase();
    expect(text).toMatch(/only trades entered via manual trade log/);
    expect(text).toMatch(/seed|demo|system/);
  });

  it('shows the human-manual-log empty state when no rows', async () => {
    mockTrades.mockResolvedValue({ operation: 'list_manual_trades', trade_count: 0, trades: [] });
    render(<ReconciliationPage />);
    const empty = await screen.findByTestId('awaiting-reconciliation-empty');
    expect((empty.textContent ?? '').toLowerCase()).toMatch(
      /no human manual logs awaiting reconciliation/,
    );
  });

  it('renders the three human manual logs (ICICIBANK / BHARTIARTL / SAP.DE)', async () => {
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 3,
      trades: [
        humanTrade({ trade_id: 'MT_icici', ticker: 'ICICIBANK.NS' }),
        humanTrade({ trade_id: 'MT_bharti', ticker: 'BHARTIARTL.NS' }),
        humanTrade({ trade_id: 'MT_sap', ticker: 'SAP.DE' }),
      ],
    });
    render(<ReconciliationPage />);
    await waitFor(() => expect(mockTrades).toHaveBeenCalled());
    const list = await screen.findByTestId('awaiting-reconciliation-list');
    const blob = list.textContent ?? '';
    expect(blob).toMatch(/ICICIBANK\.NS/);
    expect(blob).toMatch(/BHARTIARTL\.NS/);
    expect(blob).toMatch(/SAP\.DE/);
  });

  it('renders Cancel Log only for rows whose created_via is manual_trade_log', async () => {
    // If the backend ever lets a non-human row slip through, the UI must
    // still refuse to show the destructive cancel affordance for it.
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 2,
      trades: [
        humanTrade({ trade_id: 'MT_human', ticker: 'ICICIBANK.NS' }),
        humanTrade({
          trade_id: 'MT_seed',
          ticker: 'SPY',
          created_via: '', // unknown provenance
          thesis: 'Strong persistence in recent window',
        }),
      ],
    });
    render(<ReconciliationPage />);
    await waitFor(() => expect(mockTrades).toHaveBeenCalled());
    await screen.findByTestId('awaiting-reconciliation-list');
    const cancelButtons = screen.queryAllByTestId('cancel-log-btn');
    // Only one Cancel Log button — for the human row.
    expect(cancelButtons.length).toBe(1);
  });

  it('keeps the no-broker / record-keeping safety copy visible', async () => {
    mockTrades.mockResolvedValue({ operation: 'list_manual_trades', trade_count: 0, trades: [] });
    render(<ReconciliationPage />);
    await waitFor(() => expect(mockTrades).toHaveBeenCalled());
    const body = document.body.textContent ?? '';
    expect(body).toMatch(/Broker API:/);
    expect(body).toMatch(/NOT CONNECTED/);
    expect(body).toMatch(/AI executions/);
    expect(body).toMatch(/record-keeping only/i);
  });

  it('Learning Completeness card receives only the filtered backend payload', async () => {
    mockTrades.mockResolvedValue({ operation: 'list_manual_trades', trade_count: 0, trades: [] });
    mockLearning.mockResolvedValue({
      ...emptyLearning(),
      reconciled_count: 2,
      learning_complete_count: 1,
      learning_incomplete_count: 1,
    });
    render(<ReconciliationPage />);
    await waitFor(() => expect(mockLearning).toHaveBeenCalled());
    // The card consumes the response; we just confirm the page didn't
    // re-aggregate from the unfiltered /manual-trades response.
    expect(mockLearning).toHaveBeenCalledWith(20);
  });
});
