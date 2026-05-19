/**
 * Vitest spec for the Reconciliation page empty-state differentiation.
 *
 * The page must distinguish the three real "empty" cases so the operator
 * knows whether to start the backend, ignore the cancellation history,
 * or log a fresh trade.  Record-keeping only — no broker call.
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

function emptyQueue(ids: string[] = []) {
  return {
    report: 'reconciliation_queue',
    db_path: '',
    db_available: true,
    items: ids.map((trade_id) => ({ trade_id })),
    summary: {
      unreconciled_count: ids.length,
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

describe('ReconciliationPage — empty-state variants', () => {
  beforeEach(() => {
    mockQueue.mockReset();
    mockTrades.mockReset();
    mockLearning.mockReset();
    mockLearning.mockResolvedValue(emptyLearning());
  });

  it('renders backend_offline variant when /manual-trades fails', async () => {
    mockQueue.mockResolvedValue(emptyQueue());
    mockTrades.mockResolvedValue(null); // apiClient returns null on failure
    render(<ReconciliationPage />);
    const empty = await screen.findByTestId('awaiting-reconciliation-empty');
    expect(empty.getAttribute('data-empty-variant')).toBe('backend_offline');
    expect((empty.textContent ?? '').toLowerCase()).toMatch(/unreachable/);
    expect((empty.textContent ?? '').toLowerCase()).toMatch(/start the fastapi server/);
  });

  it('renders all_cancelled variant when every canonical row is cancelled', async () => {
    mockQueue.mockResolvedValue(emptyQueue([])); // queue empty
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 1,
      trades: [
        {
          trade_id: 'MT_asdc',
          event_id: 'EV',
          ticker: 'ASDC',
          side: 'BUY',
          quantity: 11,
          price: 12321,
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
          reconciliation_status: 'CANCELLED_DUPLICATE',
        },
      ],
    });
    render(<ReconciliationPage />);
    const empty = await screen.findByTestId('awaiting-reconciliation-empty');
    expect(empty.getAttribute('data-empty-variant')).toBe('all_cancelled');
    expect((empty.textContent ?? '').toLowerCase()).toMatch(/cancelled/);
  });

  it('renders no_canonical_rows variant when the manual_trades list is empty', async () => {
    mockQueue.mockResolvedValue(emptyQueue());
    mockTrades.mockResolvedValue({
      operation: 'list_manual_trades',
      trade_count: 0,
      trades: [],
    });
    render(<ReconciliationPage />);
    const empty = await screen.findByTestId('awaiting-reconciliation-empty');
    expect(empty.getAttribute('data-empty-variant')).toBe('no_canonical_rows');
    expect((empty.textContent ?? '').toLowerCase()).toMatch(
      /log a trade from manual trade log/,
    );
  });
});
