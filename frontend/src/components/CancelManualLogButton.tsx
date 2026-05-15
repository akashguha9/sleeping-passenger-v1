'use client';

import { useState } from 'react';
import { cancelManualTradeLog, ApiHttpError } from '@/lib/apiClient';

interface Props {
  tradeId: string;
  ticker?: string;
  onCancelled?: (tradeId: string) => void;
}

const SAFETY_BLURB =
  'Cancel this manual log? This only cancels the local record. It does not call a broker and does not cancel any broker order.';

/**
 * Destructive-secondary action attached to each unreconciled manual trade
 * card in the Reconciliation tab.  Clicking opens an inline confirmation
 * panel; confirming POSTs to /manual-trades/{id}/cancel.  The backend
 * route is record-keeping only — it NEVER calls a broker, NEVER cancels a
 * real order, and NEVER changes ai_execution_count.
 */
export function CancelManualLogButton({ tradeId, ticker, onCancelled }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setSubmitting(true);
    setError(null);
    try {
      await cancelManualTradeLog(tradeId, {
        reason:
          'duplicate manual log; broker API not called; AI executions = 0; exclude from P/L and exposure',
      });
      setConfirmOpen(false);
      onCancelled?.(tradeId);
    } catch (e) {
      // Prefer the backend's structured `message` (and `reason`) so the
      // operator sees "This trade has been reconciled" rather than a
      // bare "HTTP 400".  Falls back to the generic string when the
      // backend (or a proxy) returns a non-JSON body.
      if (e instanceof ApiHttpError) {
        const tail = e.reason ? ` [${e.reason}]` : '';
        setError(`Could not cancel log: ${e.message}${tail}. The card has been kept.`);
      } else if (e instanceof Error && e.message) {
        setError(`Could not cancel log (${e.message}). The card has been kept.`);
      } else {
        setError('Could not cancel log. The card has been kept.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!confirmOpen) {
    return (
      <div
        className="flex items-center justify-end gap-2 text-[11px]"
        data-testid="cancel-log-row"
        data-trade-id={tradeId}
      >
        <span className="text-slate-600">
          local log only · no broker call · record-keeping
        </span>
        <button
          type="button"
          onClick={() => {
            setError(null);
            setConfirmOpen(true);
          }}
          className="px-2.5 py-1 rounded border border-red-900/60 bg-red-950/30 text-red-300 hover:bg-red-950/50 hover:text-red-200 font-mono uppercase tracking-wider text-[10px] transition-colors"
          data-testid="cancel-log-btn"
          data-advisory-only="true"
          data-execution-permission="false"
          aria-label={
            ticker
              ? `Cancel duplicate manual log for ${ticker} (${tradeId})`
              : `Cancel duplicate manual log ${tradeId}`
          }
          title="Cancel this local manual log entry. Record-keeping only — no broker call."
        >
          Cancel Log
        </button>
      </div>
    );
  }

  return (
    <div
      className="border border-red-900/40 bg-red-950/20 rounded p-3 text-xs space-y-2"
      data-testid="cancel-log-confirm"
      data-trade-id={tradeId}
      data-advisory-only="true"
      data-execution-permission="false"
      role="alertdialog"
      aria-label="Confirm cancel local manual log"
    >
      <p className="text-slate-200">{SAFETY_BLURB}</p>
      <p className="text-[10px] font-mono uppercase tracking-wider text-emerald-400">
        Broker API: NOT CALLED · AI executions: 0 · Local log only
      </p>
      {error && (
        <p
          className="text-red-300 bg-red-950/40 border border-red-900/40 rounded px-2 py-1.5"
          data-testid="cancel-log-error"
        >
          {error}
        </p>
      )}
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          disabled={submitting}
          onClick={() => {
            setConfirmOpen(false);
            setError(null);
          }}
          className="px-2.5 py-1 rounded border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700 text-[11px] disabled:opacity-50 transition-colors"
          data-testid="cancel-log-keep-btn"
        >
          Keep log
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={handleConfirm}
          className="px-2.5 py-1 rounded border border-red-800 bg-red-900/60 text-red-100 hover:bg-red-900 text-[11px] font-semibold disabled:opacity-50 transition-colors"
          data-testid="cancel-log-confirm-btn"
        >
          {submitting ? 'Cancelling…' : 'Yes, cancel local log'}
        </button>
      </div>
    </div>
  );
}
