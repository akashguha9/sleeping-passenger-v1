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
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { BacklogReadinessBadge } from '@/components/BacklogReadinessBadge';
import { LearningCompletenessCard } from '@/components/LearningCompletenessCard';
import type {
  ManualTradeListResponse,
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [queueData, tradesData, learningData] = await Promise.all([
        getReconciliationQueue(50),
        getManualTrades(),
        getLearningCompleteness(20),
      ]);
      if (!cancelled) {
        setQueue(queueData);
        setManualTrades(tradesData);
        setLearning(learningData);
        setQueueLoading(false);
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
  const unreconciledTrades = usingMockReconciled
    ? MOCK_MANUAL_TRADES.filter(
        (t) => !reconciledMockIds.has(t.trade_id) && !isCancelledLog(t),
      )
    : (manualTrades?.trades ?? []).filter(
        (t) => !(t.learning_ready ?? false) && !isCancelledLog(t),
      );
  const realReconciledTrades = (manualTrades?.trades ?? []).filter(
    (t) => t.learning_ready === true,
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

          {unreconciledTrades.length === 0 ? (
            <div className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40">
              All trades reconciled.
            </div>
          ) : (
            <div className="space-y-3 mb-5" data-testid="awaiting-reconciliation-list">
              {unreconciledTrades.map((t) => (
                <div key={t.trade_id} className="space-y-1">
                  <ReconciliationCard trade={t} />
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
