'use client';

import { useEffect, useMemo, useState } from 'react';
import { reconcileTrade } from '@/lib/apiClient';
import type { ManualTradeLog } from '@/types';
import { HumanOnlyBadge } from './HumanOnlyBadge';
import { AdvisoryOnlyBadge } from './AdvisoryOnlyBadge';

export type ReconciliationActionMode =
  | 'PARTIAL_TP'
  | 'CLOSE_TRADE'
  | 'STOP_HIT'
  | 'UPDATE_OUTCOME';

const POST_TRADE_OUTCOMES = [
  'OPEN',
  'PARTIAL_TP',
  'CLOSED_WIN',
  'CLOSED_LOSS',
  'BREAKEVEN',
  'STOPPED_OUT',
  'MANUAL_EXIT',
  'TIMEOUT_EXIT',
] as const;

const OUTCOME_QUALITIES = [
  '',
  'GOOD_PROCESS_WIN',
  'GOOD_PROCESS_LOSS',
  'BAD_PROCESS_WIN',
  'BAD_PROCESS_LOSS',
  'UNDETERMINED',
] as const;

const QUANTITY_PRECISION = 4;

interface Props {
  open: boolean;
  trade: ManualTradeLog | null;
  mode: ReconciliationActionMode;
  onClose: () => void;
  onSubmitted: () => void;
}

interface FormState {
  actual_exit_price: string;
  exit_quantity: string;
  partial_take_profit_price: string;
  partial_take_profit_quantity: string;
  runner_quantity: string;
  stop_loss_price: string;
  stop_loss_hit: boolean;
  invalidation_level: string;
  exit_reason: string;
  outcome_quality: (typeof OUTCOME_QUALITIES)[number];
  mistake_tags: string;
  lesson_takeaway: string;
  notes: string;
  post_trade_outcome: (typeof POST_TRADE_OUTCOMES)[number];
}

function defaultPostOutcomeFor(mode: ReconciliationActionMode): FormState['post_trade_outcome'] {
  if (mode === 'PARTIAL_TP') return 'PARTIAL_TP';
  if (mode === 'STOP_HIT') return 'STOPPED_OUT';
  if (mode === 'CLOSE_TRADE') return 'CLOSED_WIN';
  return 'CLOSED_WIN';
}

function emptyForm(mode: ReconciliationActionMode): FormState {
  return {
    actual_exit_price: '',
    exit_quantity: '',
    partial_take_profit_price: '',
    partial_take_profit_quantity: '',
    runner_quantity: '',
    stop_loss_price: '',
    stop_loss_hit: mode === 'STOP_HIT',
    invalidation_level: '',
    exit_reason: '',
    outcome_quality: '',
    mistake_tags: '',
    lesson_takeaway: '',
    notes: '',
    post_trade_outcome: defaultPostOutcomeFor(mode),
  };
}

function toRoundedString(value: number, precision = QUANTITY_PRECISION): string {
  if (!isFinite(value)) return '';
  return value.toFixed(precision);
}

function modeTitle(mode: ReconciliationActionMode): string {
  switch (mode) {
    case 'PARTIAL_TP':
      return 'Log Partial Take-Profit';
    case 'CLOSE_TRADE':
      return 'Close Trade';
    case 'STOP_HIT':
      return 'Record Stop Hit';
    case 'UPDATE_OUTCOME':
    default:
      return 'Update Outcome';
  }
}

export function ReconciliationActionModal({
  open,
  trade,
  mode,
  onClose,
  onSubmitted,
}: Props) {
  const [form, setForm] = useState<FormState>(() => emptyForm(mode));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const totalQuantity = trade?.quantity ?? 0;
  const entryPrice = trade?.price ?? 0;

  // Default 70 / 30 partial-tp split — runner = total - tp to avoid drift.
  const defaultPartialTpQty = useMemo(
    () => Number(toRoundedString(totalQuantity * 0.7)),
    [totalQuantity],
  );
  const defaultRunnerQty = useMemo(
    () => Number(toRoundedString(Math.max(0, totalQuantity - defaultPartialTpQty))),
    [totalQuantity, defaultPartialTpQty],
  );

  // Reset form when the modal opens or the action mode changes.
  useEffect(() => {
    if (!open) return;
    const next = emptyForm(mode);
    if (mode === 'PARTIAL_TP') {
      next.partial_take_profit_quantity = toRoundedString(defaultPartialTpQty);
      next.exit_quantity = toRoundedString(defaultPartialTpQty);
      next.runner_quantity = toRoundedString(defaultRunnerQty);
      next.post_trade_outcome = 'PARTIAL_TP';
    } else if (mode === 'CLOSE_TRADE' || mode === 'STOP_HIT' || mode === 'UPDATE_OUTCOME') {
      next.exit_quantity = toRoundedString(totalQuantity);
      next.runner_quantity = '0';
      next.post_trade_outcome = defaultPostOutcomeFor(mode);
    }
    setForm(next);
    setError('');
  }, [open, mode, totalQuantity, defaultPartialTpQty, defaultRunnerQty]);

  if (!open || !trade) return null;

  const exitPriceNum = parseFloat(form.actual_exit_price || form.partial_take_profit_price);
  const exitQtyNum = parseFloat(form.exit_quantity || form.partial_take_profit_quantity);
  const realisedPnlPreview =
    isFinite(exitPriceNum) && isFinite(exitQtyNum)
      ? Number(((exitPriceNum - entryPrice) * exitQtyNum).toFixed(4))
      : null;

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!trade) return;
    setError('');
    const exitPrice = parseFloat(
      mode === 'PARTIAL_TP'
        ? form.partial_take_profit_price
        : form.actual_exit_price,
    );
    const exitQty = parseFloat(
      mode === 'PARTIAL_TP'
        ? form.partial_take_profit_quantity
        : form.exit_quantity,
    );
    if (!isFinite(exitPrice) || exitPrice <= 0) {
      setError('Exit price must be a positive number.');
      return;
    }
    if (!isFinite(exitQty) || exitQty <= 0) {
      setError('Exit quantity must be a positive number.');
      return;
    }
    if (exitQty > totalQuantity + 0.0001) {
      setError(
        `Exit quantity ${exitQty} exceeds logged total ${totalQuantity}.`,
      );
      return;
    }

    setSubmitting(true);
    try {
      const payload: Parameters<typeof reconcileTrade>[1] = {
        actual_fill_price: exitPrice,
        actual_quantity: exitQty,
        post_trade_outcome: form.post_trade_outcome,
        outcome_quality: form.outcome_quality || undefined,
        mistake_tags: form.mistake_tags || undefined,
        lesson_takeaway: form.lesson_takeaway || undefined,
        notes: form.notes || undefined,
        invalidation_level: form.invalidation_level || undefined,
        exit_reason: form.exit_reason || undefined,
      };
      if (mode === 'PARTIAL_TP') {
        payload.partial_take_profit_price = exitPrice;
        payload.partial_take_profit_quantity = exitQty;
        const runnerNum = parseFloat(form.runner_quantity);
        if (isFinite(runnerNum) && runnerNum >= 0) {
          payload.runner_quantity = runnerNum;
        }
        payload.take_profit_plan = '70% TP / 30% runner';
      }
      if (mode === 'STOP_HIT') {
        payload.stop_loss_hit = true;
        const sl = parseFloat(form.stop_loss_price || form.actual_exit_price);
        if (isFinite(sl) && sl > 0) {
          payload.stop_loss_price = sl;
        }
      }
      await reconcileTrade(trade.trade_id, payload);
      onSubmitted();
      onClose();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'unknown error';
      setError(`Failed to log reconciliation — ${message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
      data-testid="reconciliation-action-modal"
      role="dialog"
      aria-modal="true"
    >
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-xl max-h-[90vh] overflow-y-auto p-6">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h2 className="text-lg font-semibold text-white">{modeTitle(mode)}</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {trade.ticker} · qty {totalQuantity} · entry {entryPrice}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <HumanOnlyBadge />
            <AdvisoryOnlyBadge />
          </div>
        </div>

        <div
          className="text-[11px] text-slate-400 bg-slate-950 border border-slate-800 rounded px-3 py-2 mb-3"
          data-testid="reconciliation-record-keeping-note"
        >
          Record-keeping only. No broker call. AI executions:{' '}
          <span className="text-emerald-400 font-mono">0</span>.
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === 'PARTIAL_TP' && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">
                  Partial TP Price
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                  value={form.partial_take_profit_price}
                  onChange={(e) =>
                    update('partial_take_profit_price', e.target.value)
                  }
                  data-testid="modal-partial-tp-price"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">
                  Partial TP Quantity
                  <span className="text-[10px] text-slate-600 ml-1">
                    (default 70% = {defaultPartialTpQty})
                  </span>
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                  value={form.partial_take_profit_quantity}
                  onChange={(e) => {
                    update('partial_take_profit_quantity', e.target.value);
                    update('exit_quantity', e.target.value);
                  }}
                  data-testid="modal-partial-tp-qty"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-xs text-slate-500 mb-1">
                  Runner Quantity
                  <span className="text-[10px] text-slate-600 ml-1">
                    (default 30% = {defaultRunnerQty})
                  </span>
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                  value={form.runner_quantity}
                  onChange={(e) => update('runner_quantity', e.target.value)}
                  data-testid="modal-runner-qty"
                />
              </div>
            </div>
          )}

          {mode !== 'PARTIAL_TP' && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">
                  Actual Exit / Fill Price
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                  value={form.actual_exit_price}
                  onChange={(e) => update('actual_exit_price', e.target.value)}
                  data-testid="modal-exit-price"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">
                  Exit Quantity
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                  value={form.exit_quantity}
                  onChange={(e) => update('exit_quantity', e.target.value)}
                  data-testid="modal-exit-qty"
                />
              </div>
            </div>
          )}

          {mode === 'STOP_HIT' && (
            <div>
              <label className="block text-xs text-slate-500 mb-1">
                Stop-Loss Price (defaults to exit price)
              </label>
              <input
                type="number"
                step="any"
                min="0"
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                value={form.stop_loss_price}
                onChange={(e) => update('stop_loss_price', e.target.value)}
                data-testid="modal-stop-loss-price"
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Post-Trade Outcome
            </label>
            <select
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
              value={form.post_trade_outcome}
              onChange={(e) =>
                update(
                  'post_trade_outcome',
                  e.target.value as FormState['post_trade_outcome'],
                )
              }
              data-testid="modal-post-trade-outcome"
            >
              {POST_TRADE_OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Outcome Quality
            </label>
            <select
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
              value={form.outcome_quality}
              onChange={(e) =>
                update(
                  'outcome_quality',
                  e.target.value as FormState['outcome_quality'],
                )
              }
              data-testid="modal-outcome-quality"
            >
              {OUTCOME_QUALITIES.map((q) => (
                <option key={q || 'none'} value={q}>
                  {q || '—'}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-500 mb-1">
                Invalidation level (optional)
              </label>
              <input
                type="text"
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                value={form.invalidation_level}
                onChange={(e) => update('invalidation_level', e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">
                Exit reason (optional)
              </label>
              <input
                type="text"
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
                value={form.exit_reason}
                onChange={(e) => update('exit_reason', e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Mistake tags (comma-separated, optional)
            </label>
            <input
              type="text"
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200"
              placeholder="oversized, late_entry, fomo"
              value={form.mistake_tags}
              onChange={(e) => update('mistake_tags', e.target.value)}
              data-testid="modal-mistake-tags"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Lesson / takeaway
            </label>
            <textarea
              rows={2}
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 resize-none"
              value={form.lesson_takeaway}
              onChange={(e) => update('lesson_takeaway', e.target.value)}
              data-testid="modal-lesson"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Notes (optional)
            </label>
            <textarea
              rows={2}
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 resize-none"
              value={form.notes}
              onChange={(e) => update('notes', e.target.value)}
            />
          </div>

          {realisedPnlPreview !== null && (
            <div
              className="text-xs text-slate-400 bg-slate-950 border border-slate-800 rounded px-3 py-2"
              data-testid="modal-realised-pnl-preview"
            >
              Realised P/L preview:{' '}
              <span
                className={
                  realisedPnlPreview >= 0 ? 'text-emerald-400' : 'text-red-400'
                }
              >
                {realisedPnlPreview >= 0 ? '+' : ''}
                {realisedPnlPreview.toFixed(4)}
              </span>{' '}
              <span className="text-slate-600">
                = ({form.actual_exit_price || form.partial_take_profit_price}{' '}
                − {entryPrice}) × {form.exit_quantity || form.partial_take_profit_quantity}
              </span>
            </div>
          )}

          {error && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-900/40 rounded px-3 py-2">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-slate-400 hover:text-slate-200 px-3 py-2"
              data-testid="modal-cancel"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="bg-sky-700 hover:bg-sky-600 disabled:opacity-50 text-white text-sm font-semibold rounded px-4 py-2"
              data-testid="modal-submit"
            >
              {submitting ? 'Saving…' : 'Save Reconciliation'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
