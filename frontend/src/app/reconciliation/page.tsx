'use client';

import { useState } from 'react';
import { reconcileTrade } from '@/lib/apiClient';
import { MOCK_MANUAL_TRADES, MOCK_RECONCILIATIONS } from '@/lib/mockData';
import { ReconciliationCard } from '@/components/ReconciliationCard';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

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

  const reconciledTradeIds = new Set(MOCK_RECONCILIATIONS.map((r) => r.trade_id));
  const unreconciledTrades = MOCK_MANUAL_TRADES.filter((t) => !reconciledTradeIds.has(t.trade_id));

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Reconciled trades */}
        <div>
          <h2 className="text-sm font-semibold text-slate-300 mb-3">
            Reconciled ({MOCK_RECONCILIATIONS.length})
          </h2>
          {MOCK_RECONCILIATIONS.length === 0 ? (
            <div className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40">
              No reconciled trades yet.
            </div>
          ) : (
            <div className="space-y-3">
              {MOCK_RECONCILIATIONS.map((rec) => {
                const trade = MOCK_MANUAL_TRADES.find((t) => t.trade_id === rec.trade_id);
                if (!trade) return null;
                return <ReconciliationCard key={rec.reconciliation_id} trade={trade} reconciliation={rec} />;
              })}
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
            <div className="space-y-3 mb-5">
              {unreconciledTrades.map((t) => (
                <ReconciliationCard key={t.trade_id} trade={t} />
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
