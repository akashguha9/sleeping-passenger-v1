import type { TradeReconciliation, ManualTradeLog } from '@/types';
import { HumanOnlyBadge } from './HumanOnlyBadge';
import { UNKNOWN_CURRENCY } from '@/lib/supportedCurrencies';

const OUTCOME_STYLE: Record<string, string> = {
  WIN:       'text-emerald-400 bg-emerald-950/40 border-emerald-800/50',
  LOSS:      'text-red-400 bg-red-950/40 border-red-800/50',
  BREAKEVEN: 'text-yellow-400 bg-yellow-950/40 border-yellow-800/50',
  UNKNOWN:   'text-slate-400 bg-slate-800 border-slate-700',
};

interface Props {
  trade: ManualTradeLog;
  reconciliation?: TradeReconciliation;
}

// Format a numeric price/P&L value with its native currency tag.  We
// deliberately avoid the "$" symbol because operator-entered trades
// can be in any of the supported currencies — see
// frontend/src/lib/supportedCurrencies.ts.  Legacy rows whose currency
// reads back as UNKNOWN render without a tag rather than guessing.
function formatMoney(value: number, currency: string | null | undefined): string {
  const num = value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
  const cur = (currency ?? '').trim();
  if (!cur || cur === UNKNOWN_CURRENCY) return num;
  return `${num} ${cur}`;
}

export function ReconciliationCard({ trade, reconciliation }: Props) {
  const outcomeCls = reconciliation
    ? OUTCOME_STYLE[reconciliation.outcome_status] ?? OUTCOME_STYLE['UNKNOWN']
    : OUTCOME_STYLE['UNKNOWN'];

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-bold text-white font-mono">{trade.ticker}</span>
            <span className={`text-xs px-2 py-0.5 rounded border font-mono font-semibold ${trade.side === 'BUY' ? 'text-emerald-400 bg-emerald-950/30 border-emerald-900/40' : 'text-red-400 bg-red-950/30 border-red-900/40'}`}>
              {trade.side === 'BUY' ? 'LONG' : 'SHORT'}
            </span>
            {reconciliation && (
              <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${outcomeCls}`}>
                {reconciliation.outcome_status}
              </span>
            )}
          </div>
          <div className="text-xs text-slate-500">{trade.trade_id} · {formatTs(trade.executed_at)}</div>
        </div>
        <HumanOnlyBadge />
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4 text-sm">
        <Stat label="Qty" value={trade.quantity.toString()} />
        <Stat
          label="Log Price"
          value={formatMoney(trade.price, trade.currency)}
          testid="reconciliation-log-price"
        />
        <Stat
          label="Fill Price"
          value={
            reconciliation
              ? formatMoney(reconciliation.actual_fill_price, trade.currency)
              : '—'
          }
          testid="reconciliation-fill-price"
        />
      </div>

      {reconciliation && reconciliation.pnl_estimate !== 0 && (
        <div className="mb-3">
          <span className="text-xs text-slate-500">Realized P&amp;L</span>
          <p
            className={`text-lg font-bold font-mono mt-0.5 ${reconciliation.pnl_estimate > 0 ? 'text-emerald-400' : 'text-red-400'}`}
            data-testid="reconciliation-pnl"
          >
            {reconciliation.pnl_estimate > 0 ? '+' : ''}
            {formatMoney(reconciliation.pnl_estimate, trade.currency)}
          </p>
        </div>
      )}

      <div className="space-y-2 text-sm">
        <div>
          <span className="text-xs text-slate-500 block mb-0.5">Thesis</span>
          <p className="text-slate-300 text-xs leading-relaxed">{trade.thesis}</p>
        </div>
        {reconciliation?.outcome_notes && (
          <div>
            <span className="text-xs text-slate-500 block mb-0.5">Outcome Notes</span>
            <p className="text-slate-300 text-xs leading-relaxed">{reconciliation.outcome_notes}</p>
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center gap-3 text-xs text-slate-600">
        <span>Broker API: <span className="text-emerald-400 font-mono">NOT CALLED</span></span>
        <span>·</span>
        <span>AI executions: <span className="text-emerald-400 font-mono">0</span></span>
        <span>·</span>
        <span>{trade.logged_by}</span>
      </div>
    </div>
  );
}

function Stat({ label, value, testid }: { label: string; value: string; testid?: string }) {
  return (
    <div className="bg-slate-900/40 rounded p-2">
      <span className="text-xs text-slate-500 block mb-0.5">{label}</span>
      <span className="text-sm font-mono text-slate-200" data-testid={testid}>{value}</span>
    </div>
  );
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}
