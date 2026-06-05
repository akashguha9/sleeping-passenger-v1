'use client';

import { useEffect, useState } from 'react';
import {
  getReconciliationQueue,
  getManualTrades,
  reconcileTrade,
  getLearningCompleteness,
} from '@/lib/apiClient';
import { MOCK_MANUAL_TRADES, MOCK_RECONCILIATIONS } from '@/lib/mockData';
import { ReconciliationCard } from '@/components/ReconciliationCard';
import { CancelManualLogButton } from '@/components/CancelManualLogButton';
import {
  ReconciliationActionModal,
  type ReconciliationActionMode,
} from '@/components/ReconciliationActionModal';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { BacklogReadinessBadge } from '@/components/BacklogReadinessBadge';
import { LearningCompletenessCard } from '@/components/LearningCompletenessCard';
import type {
  ManualTradeListResponse,
  ManualTradeLog,
  ReconciliationQueueResponse,
  LearningCompletenessResponse,
} from '@/types';

type OutcomeStatus = 'WIN' | 'LOSS' | 'BREAKEVEN' | 'UNKNOWN';

export default function ReconciliationPage() {
  const [form, setForm] = useState({
    trade_id: '',
    actual_fill_price: '',
    actual_quantity: '',
    outcome_notes: '',
    pnl_estimate: '',
    outcome_status: 'UNKNOWN' as OutcomeStatus,
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');
  const [queue, setQueue] = useState<ReconciliationQueueResponse | null>(null);
  const [queueLoading, setQueueLoading] = useState(true);
  const [manualTrades, setManualTrades] = useState<ManualTradeListResponse | null>(null);
  const [learning, setLearning] = useState<LearningCompletenessResponse | null>(null);
  // Trades the operator just cancelled via "Cancel Log".  Used to hide
  // them immediately even before the next /manual-trades round-trip lands.
  // Cancellation is record-keeping only — no broker call, no execution.
  const [locallyCancelled, setLocallyCancelled] = useState<Set<string>>(
    () => new Set(),
  );
  const [refreshTick, setRefreshTick] = useState(0);
  const [activeAction, setActiveAction] = useState<{
    trade: ManualTradeLog;
    mode: ReconciliationActionMode;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Reconciliation tab is a human-manual-log surface only.  We pin the
      // /manual-trades query to origin=manual_trade_log so seed/demo/import
      // rows (e.g. SPY/QQQ smoke rows) never appear in either the
      // Awaiting Reconciliation list or the Reconciled column.  The
      // Manual Trade Log page still calls getManualTrades() with no
      // filter for full-history audit.
      try {
        const [queueData, tradesData, learningData] = await Promise.all([
          getReconciliationQueue(50),
          getManualTrades({ origin: 'manual_trade_log' }),
          getLearningCompleteness(20),
        ]);
        if (!cancelled) {
          setQueue(queueData);
          setManualTrades(tradesData);
          setLearning(learningData);
        }
      } finally {
        // Always leave the loading state. The API helpers already swallow
        // network/timeout errors and return null (rendered as the offline /
        // empty state); the finally guards against any unexpected throw so the
        // queue never stays stuck on "Loading awaiting reconciliation list…".
        if (!cancelled) {
          setQueueLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [submitted, refreshTick]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.trade_id.trim()) { setError('Trade ID is required.'); return; }
    const fillPrice = parseFloat(form.actual_fill_price);
    const qty = parseFloat(form.actual_quantity);
    if (isNaN(fillPrice) || fillPrice <= 0) { setError('Actual fill price must be a positive number.'); return; }
    if (isNaN(qty) || qty <= 0) { setError('Actual quantity must be a positive number.'); return; }

    setSubmitting(true);
    setError('');
    try {
      await reconcileTrade(form.trade_id.trim(), {
        actual_fill_price: fillPrice,
        actual_quantity: qty,
        outcome_notes: form.outcome_notes,
        pnl_estimate: parseFloat(form.pnl_estimate) || 0,
        outcome_status: form.outcome_status,
      });
      setSubmitted(true);
      setTimeout(() => setSubmitted(false), 4000);
    } catch {
      setError('Failed to log reconciliation — backend may be offline. Start the FastAPI server and try again.');
    } finally {
      setSubmitting(false);
    }
  }

  // Reconciled panel: prefer real backend manual_trades + their attached
  // recon results.  Fall back to MOCK_RECONCILIATIONS only when the API
  // is unreachable so the UI still has something to render in offline mode.
  const usingMockReconciled = manualTrades === null;
  const reconciledMockIds = new Set(MOCK_RECONCILIATIONS.map((r) => r.trade_id));
  const isCancelledLog = (t: { reconciliation_status?: string; trade_id: string }) => {
    const status = (t.reconciliation_status ?? '').toUpperCase();
    return (
      status === 'CANCELLED_DUPLICATE' ||
      status === 'CANCELLED_LOG' ||
      locallyCancelled.has(t.trade_id)
    );
  };
  // The queue endpoint already filters to user-manual rows that have no
  // reconciliation_results row yet (the truly-awaiting set).  Use it as
  // the source of truth for which trade_ids belong on the Awaiting
  // Reconciliation list so the page does not include
  // reconciled-but-journal-incomplete rows here — those belong in
  // Learning Completeness, not the action queue.  Falling back to a
  // /manual-trades filter when the queue is unavailable keeps offline
  // mode rendering something rather than nothing.
  const queueAwaitingIds = new Set<string>(
    (queue?.items ?? []).map((it) => it.trade_id).filter(Boolean),
  );
  const unreconciledTrades = usingMockReconciled
    ? MOCK_MANUAL_TRADES.filter(
        (t) => !reconciledMockIds.has(t.trade_id) && !isCancelledLog(t),
      )
    : (manualTrades?.trades ?? []).filter((t) => {
        if (isCancelledLog(t)) return false;
        // If we have a queue, trust it: only show cards the backend
        // queue considers awaiting reconciliation.  This is the same
        // predicate the Cancel Log guard uses on the server, so the UI
        // can never offer Cancel Log on a reconciled row and trigger
        // the 400 the user complained about.
        if (queue !== null) {
          return queueAwaitingIds.has(t.trade_id);
        }
        // Queue unavailable — degrade gracefully to "no reconciliation
        // result yet" using the learning_ready flag as a proxy.
        return !(t.learning_ready ?? false);
      });
  const realReconciledTrades = (manualTrades?.trades ?? []).filter(
    (t) => t.learning_ready === true,
  );
  // Reconciled-but-journal-incomplete: counted by Learning Completeness,
  // not by the live queue.  Surfaced as a separate count so the landing
  // panel never claims "backlog clear" while also implying unresolved
  // action cards.
  const reconciledButLearningIncomplete = (manualTrades?.trades ?? []).filter(
    (t) =>
      !isCancelledLog(t) &&
      !queueAwaitingIds.has(t.trade_id) &&
      t.learning_ready !== true,
  );

  function handleLogCancelled(tradeId: string) {
    setLocallyCancelled((prev) => {
      const next = new Set(prev);
      next.add(tradeId);
      return next;
    });
    // Re-fetch the queue + trades so the unreconciled counter, journal
    // gaps row, and learning completeness card all reflect the cancel.
    setRefreshTick((n) => n + 1);
  }

  function openAction(trade: ManualTradeLog, mode: ReconciliationActionMode) {
    setActiveAction({ trade, mode });
  }
  function closeAction() {
    setActiveAction(null);
  }
  function handleReconciliationSubmitted() {
    // Re-fetch queue + trades so partial/close/stop outcomes feed back into
    // the awaiting list and learning-readiness card.
    setRefreshTick((n) => n + 1);
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Reconciliation</h1>
          <p className="text-sm text-slate-500 mt-0.5">Match logged trades to actual outcomes</p>
        </div>
        <div className="flex items-center gap-2">
          <HumanOnlyBadge size="md" />
          <AdvisoryOnlyBadge size="md" />
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-xs text-slate-400">
        Reconciliation is for record-keeping only. Broker API:{' '}
        <span className="text-emerald-400 font-mono font-semibold">NOT CONNECTED</span>. AI executions:{' '}
        <span className="text-emerald-400 font-mono font-bold">0</span>. All data is ADVISORY_ONLY.
      </div>

      <div
        className="text-[11px] text-slate-400 bg-slate-900/40 border border-slate-800 rounded px-3 py-2"
        data-testid="reconciliation-provenance-note"
      >
        Reconciliation shows only trades entered via Manual Trade Log.
        Seed/demo/system rows are excluded.
      </div>

      <LearningCompletenessCard data={learning} />

      <div className="bg-slate-900 border border-slate-700 rounded-lg p-4">
        <div className="flex items-baseline justify-between mb-2 flex-wrap gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-sm font-semibold text-slate-200">Live Reconciliation Queue</h2>
            <BacklogReadinessBadge
              input={{
                unreconciled_count: queue?.summary?.unreconciled_count,
                average_journal_completeness:
                  queue?.summary?.average_journal_completeness,
                oldest_unreconciled_age_days:
                  queue?.summary?.oldest_unreconciled_age_days,
              }}
            />
          </div>
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            Source: backend /self-test/reconciliation-queue
          </span>
        </div>
        <p className="text-[11px] text-slate-500 mb-3 leading-snug">
          Backlog block is the primary preflight gate. Reactor diagnostics
          cannot override a BLOCKED backlog. Reconciliation is record-keeping
          only — it does not place, modify, or cancel broker orders.
        </p>
        {queueLoading ? (
          <div className="text-xs text-slate-500">Loading queue…</div>
        ) : queue === null ? (
          <div className="text-xs text-amber-400">
            Backend unreachable — showing mock trades below for visual context only. Start the FastAPI server to see your real queue.
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div>
              <div className="text-slate-500">Unreconciled</div>
              <div className="text-lg font-mono text-white">{queue.summary.unreconciled_count}</div>
            </div>
            <div>
              <div className="text-slate-500">Oldest age (days)</div>
              <div className="text-lg font-mono text-white">
                {queue.summary.oldest_unreconciled_age_days === null
                  ? '–'
                  : queue.summary.oldest_unreconciled_age_days.toFixed(1)}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Avg journal completeness</div>
              <div className="text-lg font-mono text-white">
                {(queue.summary.average_journal_completeness * 100).toFixed(0)}%
              </div>
            </div>
            <div>
              <div className="text-slate-500">Learning-ready</div>
              <div className="text-lg font-mono text-white">
                {queue.summary.learning_ready_count}
              </div>
            </div>
            <div className="col-span-2 md:col-span-4 text-[11px] text-slate-400 mt-1">
              {queue.operator_action}
            </div>
            {Object.keys(queue.summary.missing_field_distribution || {}).length > 0 && (
              <div className="col-span-2 md:col-span-4 text-[11px] text-slate-500">
                <span className="text-slate-400">Most-missing fields: </span>
                {Object.entries(queue.summary.missing_field_distribution)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 5)
                  .map(([k, v]) => `${k}(${v})`)
                  .join(', ')}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Reconciled trades */}
        <div>
          <h2 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
            Reconciled (
            {usingMockReconciled ? MOCK_RECONCILIATIONS.length : realReconciledTrades.length}
            )
            {usingMockReconciled && (
              <span
                className="text-[10px] font-mono uppercase tracking-widest text-amber-400 bg-amber-950/30 border border-amber-900/40 rounded px-1.5 py-0.5"
                data-testid="reconciled-mock-fallback"
              >
                MOCK_FALLBACK
              </span>
            )}
          </h2>
          {usingMockReconciled ? (
            MOCK_RECONCILIATIONS.length === 0 ? (
              <div className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40">
                No reconciled trades yet.
              </div>
            ) : (
              <div className="space-y-3">
                {MOCK_RECONCILIATIONS.map((rec) => {
                  const trade = MOCK_MANUAL_TRADES.find((t) => t.trade_id === rec.trade_id);
                  if (!trade) return null;
                  return (
                    <ReconciliationCard
                      key={rec.reconciliation_id}
                      trade={trade}
                      reconciliation={rec}
                    />
                  );
                })}
              </div>
            )
          ) : realReconciledTrades.length === 0 ? (
            <div className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40">
              No learning-ready trades yet. A trade becomes learning-ready when
              its journal fields are complete and it has been reconciled.
            </div>
          ) : (
            <div className="space-y-3">
              {realReconciledTrades.map((t) => (
                <ReconciliationCard key={t.trade_id} trade={t} />
              ))}
            </div>
          )}
        </div>

        {/* Reconcile form */}
        <div>
          <h2 className="text-sm font-semibold text-slate-300 mb-3">
            Awaiting Reconciliation ({unreconciledTrades.length})
          </h2>

          {queueLoading ? (
            <div
              className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40"
              data-testid="awaiting-reconciliation-loading"
            >
              Loading awaiting reconciliation list…
            </div>
          ) : unreconciledTrades.length === 0 ? (
            <AwaitingEmptyState
              offline={manualTrades === null}
              cancelledCount={
                (manualTrades?.trades ?? []).filter((t) => isCancelledLog(t)).length
              }
              reconciledIncompleteCount={reconciledButLearningIncomplete.length}
            />
          ) : (
            <div className="space-y-3 mb-5" data-testid="awaiting-reconciliation-list">
              {unreconciledTrades.map((t) => (
                <div key={t.trade_id} className="space-y-1">
                  <ReconciliationCard trade={t} />
                  {!usingMockReconciled && (
                    <OriginAndDuplicateChips
                      originLabel={
                        (t as { origin_label?: string }).origin_label ?? 'USER_MANUAL'
                      }
                      tradeId={t.trade_id}
                      possibleDuplicate={Boolean(
                        (t as { possible_duplicate?: boolean }).possible_duplicate,
                      )}
                      duplicateCount={
                        (t as { duplicate_count?: number }).duplicate_count ?? 1
                      }
                    />
                  )}
                  {!usingMockReconciled && (
                    <JournalGapsRow
                      tradeId={t.trade_id}
                      completeness={
                        (t as { journal_completeness_score?: number })
                          .journal_completeness_score
                      }
                      missingFields={
                        (t as { missing_journal_fields?: string[] }).missing_journal_fields
                      }
                      lesson={(t as { lesson?: string }).lesson}
                      mistakeTags={(t as { mistake_tags?: string }).mistake_tags}
                    />
                  )}
                  {!usingMockReconciled && (
                    <ReconciliationActionButtons
                      trade={t}
                      onAction={(mode) => openAction(t, mode)}
                    />
                  )}
                  {!usingMockReconciled &&
                    (t as { created_via?: string }).created_via ===
                      'manual_trade_log' &&
                    queueAwaitingIds.has(t.trade_id) && (
                      <CancelManualLogButton
                        tradeId={t.trade_id}
                        ticker={t.ticker}
                        onCancelled={handleLogCancelled}
                      />
                    )}
                </div>
              ))}
            </div>
          )}

          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
            <div className="flex items-center gap-2 mb-4">
              <h3 className="text-sm font-semibold text-slate-300">Log Reconciliation</h3>
              <HumanOnlyBadge />
            </div>

            {submitted ? (
              <div className="text-center py-4">
                <div className="text-emerald-400 text-xl mb-1">✓</div>
                <p className="text-sm text-white font-semibold">Reconciliation Logged</p>
                <p className="text-xs text-slate-400 mt-1">
                  AI executions: <span className="text-emerald-400 font-mono font-bold">0</span>
                </p>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Trade ID</label>
                  <input
                    type="text"
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500 font-mono"
                    placeholder="MT_..."
                    value={form.trade_id}
                    onChange={(e) => setForm((f) => ({ ...f, trade_id: e.target.value }))}
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Actual Fill Price</label>
                    <input
                      type="number" step="any" min="0"
                      className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
                      placeholder="183.20"
                      value={form.actual_fill_price}
                      onChange={(e) => setForm((f) => ({ ...f, actual_fill_price: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Actual Quantity</label>
                    <input
                      type="number" step="any" min="0"
                      className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
                      placeholder="10"
                      value={form.actual_quantity}
                      onChange={(e) => setForm((f) => ({ ...f, actual_quantity: e.target.value }))}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Outcome</label>
                  <select
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-slate-500"
                    value={form.outcome_status}
                    onChange={(e) => setForm((f) => ({ ...f, outcome_status: e.target.value as OutcomeStatus }))}
                  >
                    <option value="WIN">WIN</option>
                    <option value="LOSS">LOSS</option>
                    <option value="BREAKEVEN">BREAKEVEN</option>
                    <option value="UNKNOWN">UNKNOWN</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">P&amp;L Estimate</label>
                  <input
                    type="number" step="any"
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
                    placeholder="69.00"
                    value={form.pnl_estimate}
                    onChange={(e) => setForm((f) => ({ ...f, pnl_estimate: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Outcome Notes</label>
                  <textarea
                    rows={2}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-slate-500"
                    placeholder="What actually happened?"
                    value={form.outcome_notes}
                    onChange={(e) => setForm((f) => ({ ...f, outcome_notes: e.target.value }))}
                  />
                </div>

                {error && (
                  <div className="text-xs text-red-400 bg-red-950/30 border border-red-900/40 rounded px-3 py-2">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full py-2.5 rounded bg-sky-700 hover:bg-sky-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors"
                >
                  {submitting ? 'Logging…' : 'Log Reconciliation'}
                </button>
              </form>
            )}
          </div>
        </div>
      </div>

      <ReconciliationActionModal
        open={activeAction !== null}
        trade={activeAction?.trade ?? null}
        mode={activeAction?.mode ?? 'UPDATE_OUTCOME'}
        onClose={closeAction}
        onSubmitted={handleReconciliationSubmitted}
      />
    </div>
  );
}

interface OriginAndDuplicateChipsProps {
  originLabel: string;
  tradeId: string;
  possibleDuplicate: boolean;
  duplicateCount: number;
}

/**
 * Small chip row showing the row's origin classification and any
 * duplicate-group warning.  USER_MANUAL is the only label that should
 * ever render on a card in the Awaiting list — the page filters
 * everything else out — but we display the label anyway so the QA
 * snapshot in tests can prove no EXCLUDED_* leaked through.  Possible
 * duplicate chip points the operator at Cancel Log when the same
 * ticker/side/qty/price was logged within the same UTC minute.
 */
function OriginAndDuplicateChips({
  originLabel,
  tradeId,
  possibleDuplicate,
  duplicateCount,
}: OriginAndDuplicateChipsProps) {
  return (
    <div
      className="flex flex-wrap items-center gap-2 text-[10px] font-mono"
      data-testid="origin-duplicate-chips"
      data-trade-id={tradeId}
      data-origin-label={originLabel}
    >
      <span
        className={
          originLabel === 'USER_MANUAL'
            ? 'px-1.5 py-0.5 rounded border border-emerald-900/60 bg-emerald-950/30 text-emerald-300 uppercase tracking-widest'
            : 'px-1.5 py-0.5 rounded border border-amber-900/60 bg-amber-950/30 text-amber-300 uppercase tracking-widest'
        }
        data-testid="origin-label-chip"
      >
        origin: {originLabel.toLowerCase().replace(/_/g, ' ')}
      </span>
      {possibleDuplicate && duplicateCount > 1 && (
        <span
          className="px-1.5 py-0.5 rounded border border-amber-900/60 bg-amber-950/30 text-amber-300 uppercase tracking-widest"
          data-testid="possible-duplicate-chip"
          title="Same ticker/side/qty/price logged in the same UTC minute. Cancel the extra copy with Cancel Log; broker API not called."
        >
          possible duplicate · {duplicateCount}
        </span>
      )}
    </div>
  );
}

interface ActionButtonsProps {
  trade: ManualTradeLog;
  onAction: (mode: ReconciliationActionMode) => void;
}

/**
 * Action row rendered under each Awaiting Reconciliation card.  Opens
 * the local-only ReconciliationActionModal — these buttons NEVER call a
 * broker, NEVER place/cancel an order, NEVER increment ai_execution_count.
 * The "Cancel Log" affordance lives in CancelManualLogButton (separate
 * component) so its confirmation dialog can stay specialised.
 */
function ReconciliationActionButtons({ trade, onAction }: ActionButtonsProps) {
  const baseCls =
    'text-[11px] font-mono uppercase tracking-widest px-2.5 py-1 rounded border border-slate-700 hover:bg-slate-800/60 text-slate-300';
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      data-testid="reconciliation-action-buttons"
      data-trade-id={trade.trade_id}
    >
      <button
        type="button"
        className={baseCls}
        onClick={() => onAction('UPDATE_OUTCOME')}
        data-testid="action-reconcile"
      >
        Reconcile / Update Outcome
      </button>
      <button
        type="button"
        className={baseCls}
        onClick={() => onAction('PARTIAL_TP')}
        data-testid="action-partial-tp"
      >
        Log Partial TP
      </button>
      <button
        type="button"
        className={baseCls}
        onClick={() => onAction('CLOSE_TRADE')}
        data-testid="action-close-trade"
      >
        Close Trade
      </button>
      <button
        type="button"
        className={baseCls}
        onClick={() => onAction('STOP_HIT')}
        data-testid="action-stop-hit"
      >
        Stop Hit
      </button>
      <span
        className="text-[10px] text-slate-500"
        data-testid="recon-record-keeping-note"
      >
        Record-keeping only. No broker call.
      </span>
    </div>
  );
}

/**
 * Empty state for the Awaiting Reconciliation column.  Differentiates
 * the three real cases the operator needs to distinguish so the tab
 * stops feeling "silently empty":
 *   - backend offline / unreachable
 *   - no user-manual rows at all (all DB rows are quarantined or
 *     never reached the canonical 'manual_trade_log' provenance)
 *   - all canonical rows were soft-cancelled from this tab
 *   - 0 awaiting but reconciled-incomplete rows need journal fields
 * Record-keeping only — no broker call.
 */
function AwaitingEmptyState({
  offline,
  cancelledCount,
  reconciledIncompleteCount,
}: {
  offline: boolean;
  cancelledCount: number;
  reconciledIncompleteCount: number;
}) {
  let primary = 'No user-created manual logs awaiting reconciliation.';
  let secondary: string | null = null;
  let variant = 'no_canonical_rows';
  if (offline) {
    primary = 'Backend unreachable — cannot load reconciliation queue.';
    secondary =
      'Start the FastAPI server (python scripts/api_server.py) on 127.0.0.1:8000 and refresh.';
    variant = 'backend_offline';
  } else if (cancelledCount > 0) {
    primary = `No awaiting trades — ${cancelledCount} canonical row(s) were soft-cancelled.`;
    secondary =
      'Cancelled rows stay in the audit trail. Log a new manual trade to populate this list.';
    variant = 'all_cancelled';
  } else if (reconciledIncompleteCount > 0) {
    primary = 'No awaiting trades — all canonical rows are reconciled.';
    secondary = `${reconciledIncompleteCount} reconciled trade(s) still need journal fields — see Learning Completeness.`;
    variant = 'all_reconciled_journal_gap';
  } else {
    primary =
      'No user-created manual logs awaiting reconciliation. Log a trade from Manual Trade Log to begin.';
    variant = 'no_canonical_rows';
  }
  return (
    <div
      className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40"
      data-testid="awaiting-reconciliation-empty"
      data-empty-variant={variant}
    >
      {primary}
      {secondary && (
        <div
          className="text-[11px] text-slate-500 mt-2"
          data-testid="awaiting-empty-secondary"
        >
          {secondary}
        </div>
      )}
      {!offline && reconciledIncompleteCount > 0 && variant !== 'all_reconciled_journal_gap' && (
        <div
          className="text-[11px] text-slate-500 mt-2"
          data-testid="awaiting-empty-journal-hint"
        >
          {reconciledIncompleteCount} reconciled trade(s) still need journal fields — see Learning Completeness.
        </div>
      )}
    </div>
  );
}

interface JournalGapsRowProps {
  tradeId: string;
  completeness?: number;
  missingFields?: string[];
  lesson?: string;
  mistakeTags?: string;
}

/**
 * Per-trade chip row that surfaces what the operator still has to fill
 * in before this trade is learning-ready.  Advisory display only — it
 * does not call any reconcile endpoint or mutate state.
 */
function JournalGapsRow({
  tradeId,
  completeness,
  missingFields,
  lesson,
  mistakeTags,
}: JournalGapsRowProps) {
  const missing = missingFields ?? [];
  const pct =
    typeof completeness === 'number' && !Number.isNaN(completeness)
      ? Math.round(completeness * 100)
      : null;
  return (
    <div
      className="text-[10px] font-mono text-slate-500 px-3 py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 border border-slate-800 rounded bg-slate-900/40"
      data-testid="journal-gaps-row"
      data-trade-id={tradeId}
    >
      {pct !== null && (
        <span
          className={
            pct < 40 ? 'text-red-300' : pct < 70 ? 'text-amber-300' : 'text-emerald-300'
          }
          data-testid="journal-completeness-pct"
        >
          journal {pct}%
        </span>
      )}
      {missing.length > 0 && (
        <span data-testid="missing-fields-chip">
          missing: {missing.slice(0, 4).join(', ')}
          {missing.length > 4 ? '…' : ''}
        </span>
      )}
      {!lesson && (
        <span
          className="text-amber-400"
          data-testid="lesson-missing-chip"
          title="Lesson empty — capture one before this trade can teach the loop."
        >
          lesson: not captured
        </span>
      )}
      {!mistakeTags && (
        <span
          className="text-slate-500"
          data-testid="mistake-tags-missing-chip"
          title="mistake_tags empty — add one at reconciliation time."
        >
          mistake_tags: none
        </span>
      )}
    </div>
  );
}
