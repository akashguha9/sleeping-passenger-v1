/**
 * Vitest spec for the Reconciliation tab action buttons + modal flow
 * (Sprint H — Reconciliation productisation).
 *
 * Locks down the user-visible contract:
 *
 *   * Each Awaiting card renders the five action buttons —
 *       Reconcile / Update Outcome, Log Partial TP, Close Trade,
 *       Stop Hit, Cancel Log.
 *   * Clicking Reconcile / Update Outcome opens the modal with the core
 *     form fields visible.
 *   * Log Partial TP defaults the partial-tp / runner quantities to
 *     70 % / 30 % of the logged quantity.
 *   * Submitting the modal calls reconcileTrade with the right payload
 *     and the page refreshes its data afterwards.
 *   * Stop Hit submits stop_loss_hit=true.
 *   * The modal copy is record-keeping only — no broker language.
 *   * Cancel Log uses the existing CancelManualLogButton confirmation
 *     copy ("only cancels the local record … does not call a broker").
 *   * Safety stamps remain visible on the page.
 */
// @ts-ignore
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
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
  reconcileTrade: vi.fn().mockResolvedValue({ status: 'logged' }),
  cancelManualTradeLog: vi.fn().mockResolvedValue({ status: 'cancelled' }),
}));

import {
  getReconciliationQueue,
  getManualTrades,
  getLearningCompleteness,
  reconcileTrade,
  cancelManualTradeLog,
} from '@/lib/apiClient';
import ReconciliationPage from '@/app/reconciliation/page';

const mockQueue = getReconciliationQueue as unknown as ReturnType<typeof vi.fn>;
const mockTrades = getManualTrades as unknown as ReturnType<typeof vi.fn>;
const mockLearning = getLearningCompleteness as unknown as ReturnType<typeof vi.fn>;
const mockReconcile = reconcileTrade as unknown as ReturnType<typeof vi.fn>;
const mockCancel = cancelManualTradeLog as unknown as ReturnType<typeof vi.fn>;

function emptyQueue(unreconciled = 1) {
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
    trade_id: 'MT_icici_001',
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
  };
}

function setupHappyPath(trade = humanTrade()) {
  // Sprint I: the page uses the queue's items as the source of truth
  // for which trade_ids are awaiting.  Make the queue list the same
  // trade_id the /manual-trades mock returns so the card renders.
  const queue = emptyQueue(1);
  queue.items = [{ trade_id: (trade as { trade_id: string }).trade_id }] as unknown as never[];
  mockQueue.mockResolvedValue(queue);
  mockTrades.mockResolvedValue({
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    trades: [trade],
    truth_source: 'sqlite',
  });
  mockLearning.mockResolvedValue(emptyLearning());
}

beforeEach(() => {
  mockReconcile.mockClear();
  mockReconcile.mockResolvedValue({ status: 'logged' });
  mockCancel.mockClear();
  mockCancel.mockResolvedValue({ status: 'cancelled' });
});

async function renderPage() {
  render(<ReconciliationPage />);
  await waitFor(() =>
    expect(screen.getByTestId('reconciliation-action-buttons')).toBeTruthy(),
  );
}

describe('Reconciliation action buttons + modal', () => {
  it('B1.1 — each Awaiting card renders the five action buttons + cancel + record-keeping note', async () => {
    setupHappyPath();
    await renderPage();
    expect(screen.getByTestId('action-reconcile')).toBeTruthy();
    expect(screen.getByTestId('action-partial-tp')).toBeTruthy();
    expect(screen.getByTestId('action-close-trade')).toBeTruthy();
    expect(screen.getByTestId('action-stop-hit')).toBeTruthy();
    expect(screen.getByTestId('cancel-log-btn')).toBeTruthy();
    const note = screen.getByTestId('recon-record-keeping-note');
    expect(note.textContent).toMatch(/no broker call/i);
  });

  it('B1.2 — clicking Reconcile / Update Outcome opens the modal with core fields', async () => {
    setupHappyPath();
    await renderPage();
    fireEvent.click(screen.getByTestId('action-reconcile'));
    const modal = await waitFor(() =>
      screen.getByTestId('reconciliation-action-modal'),
    );
    const within_ = within(modal);
    expect(within_.getByTestId('modal-exit-price')).toBeTruthy();
    expect(within_.getByTestId('modal-exit-qty')).toBeTruthy();
    expect(within_.getByTestId('modal-post-trade-outcome')).toBeTruthy();
    expect(within_.getByTestId('modal-outcome-quality')).toBeTruthy();
    expect(within_.getByTestId('modal-mistake-tags')).toBeTruthy();
    expect(within_.getByTestId('modal-lesson')).toBeTruthy();
    // Record-keeping safety note is present.
    expect(
      within_.getByTestId('reconciliation-record-keeping-note').textContent,
    ).toMatch(/no broker call/i);
  });

  it('B2 — Log Partial TP defaults to 70 / 30 split and posts PARTIAL_TP', async () => {
    setupHappyPath();
    await renderPage();
    fireEvent.click(screen.getByTestId('action-partial-tp'));
    const modal = await waitFor(() =>
      screen.getByTestId('reconciliation-action-modal'),
    );
    const w = within(modal);
    const tpQtyInput = w.getByTestId('modal-partial-tp-qty') as HTMLInputElement;
    const runnerInput = w.getByTestId('modal-runner-qty') as HTMLInputElement;
    // ICICIBANK.NS qty 3.8908 → 2.7236 / 1.1672 (Sprint H fixture).
    expect(tpQtyInput.value).toBe('2.7236');
    expect(runnerInput.value).toBe('1.1672');
    // Operator enters the partial fill price and submits.
    fireEvent.change(w.getByTestId('modal-partial-tp-price'), {
      target: { value: '42.0' },
    });
    fireEvent.click(w.getByTestId('modal-submit'));
    await waitFor(() => expect(mockReconcile).toHaveBeenCalledTimes(1));
    const [tradeId, payload] = mockReconcile.mock.calls[0];
    expect(tradeId).toBe('MT_icici_001');
    expect(payload.post_trade_outcome).toBe('PARTIAL_TP');
    expect(payload.partial_take_profit_price).toBe(42.0);
    expect(payload.partial_take_profit_quantity).toBe(2.7236);
    expect(payload.runner_quantity).toBe(1.1672);
    expect(payload.take_profit_plan).toBe('70% TP / 30% runner');
  });

  it('B3 — Close Trade sends actual_fill_price + exit_quantity + CLOSED_WIN', async () => {
    setupHappyPath();
    await renderPage();
    fireEvent.click(screen.getByTestId('action-close-trade'));
    const modal = await waitFor(() =>
      screen.getByTestId('reconciliation-action-modal'),
    );
    const w = within(modal);
    const exitQty = w.getByTestId('modal-exit-qty') as HTMLInputElement;
    expect(exitQty.value).toBe('3.8908');
    fireEvent.change(w.getByTestId('modal-exit-price'), {
      target: { value: '44.0' },
    });
    fireEvent.click(w.getByTestId('modal-submit'));
    await waitFor(() => expect(mockReconcile).toHaveBeenCalledTimes(1));
    const [, payload] = mockReconcile.mock.calls[0];
    expect(payload.actual_fill_price).toBe(44.0);
    expect(payload.actual_quantity).toBe(3.8908);
    expect(payload.post_trade_outcome).toBe('CLOSED_WIN');
  });

  it('B4 — Stop Hit submits stop_loss_hit=true and STOPPED_OUT', async () => {
    setupHappyPath();
    await renderPage();
    fireEvent.click(screen.getByTestId('action-stop-hit'));
    const modal = await waitFor(() =>
      screen.getByTestId('reconciliation-action-modal'),
    );
    const w = within(modal);
    fireEvent.change(w.getByTestId('modal-exit-price'), {
      target: { value: '38.0' },
    });
    fireEvent.change(w.getByTestId('modal-stop-loss-price'), {
      target: { value: '38.0' },
    });
    fireEvent.click(w.getByTestId('modal-submit'));
    await waitFor(() => expect(mockReconcile).toHaveBeenCalledTimes(1));
    const [, payload] = mockReconcile.mock.calls[0];
    expect(payload.post_trade_outcome).toBe('STOPPED_OUT');
    expect(payload.stop_loss_hit).toBe(true);
    expect(payload.stop_loss_price).toBe(38.0);
  });

  it('B5 — Cancel Log uses the spec confirmation copy and calls cancelManualTradeLog', async () => {
    setupHappyPath();
    await renderPage();
    fireEvent.click(screen.getByTestId('cancel-log-btn'));
    const confirm = await waitFor(() =>
      screen.getByTestId('cancel-log-confirm'),
    );
    expect(confirm.textContent).toMatch(/only cancels the local record/i);
    expect(confirm.textContent).toMatch(/does not call a broker/i);
    expect(confirm.textContent).toMatch(
      /does not cancel any broker order/i,
    );
    fireEvent.click(within(confirm).getByTestId('cancel-log-confirm-btn'));
    await waitFor(() => expect(mockCancel).toHaveBeenCalledTimes(1));
    const [tradeId, body] = mockCancel.mock.calls[0];
    expect(tradeId).toBe('MT_icici_001');
    expect(body.reason).toMatch(/duplicate manual log/i);
    expect(body.reason).toMatch(/broker API not called/i);
  });

  it('B7 — modal copy never implies broker / order placement / cancellation', async () => {
    setupHappyPath();
    await renderPage();
    fireEvent.click(screen.getByTestId('action-close-trade'));
    const modal = await waitFor(() =>
      screen.getByTestId('reconciliation-action-modal'),
    );
    const text = (modal.textContent || '').toLowerCase();
    for (const banned of [
      'place order',
      'place an order',
      'submit order',
      'broker submit',
      'cancel broker order',
      'auto trade',
      'auto-trade',
      'execute trade',
    ]) {
      expect(text.includes(banned)).toBe(false);
    }
  });

  it('B8 — page-level safety stamps remain visible while the modal is open', async () => {
    setupHappyPath();
    await renderPage();
    fireEvent.click(screen.getByTestId('action-reconcile'));
    await waitFor(() =>
      expect(screen.getByTestId('reconciliation-action-modal')).toBeTruthy(),
    );
    expect(screen.getAllByText(/Broker API:/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/AI executions:/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/ADVISORY_ONLY/i).length).toBeGreaterThan(0);
  });
});
