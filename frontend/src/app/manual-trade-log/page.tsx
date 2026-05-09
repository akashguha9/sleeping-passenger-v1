import { MOCK_MANUAL_TRADES } from '@/lib/mockData';
import { ManualTradeLogForm } from '@/components/ManualTradeLogForm';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

export default function ManualTradeLogPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Manual Trade Log</h1>
          <p className="text-sm text-slate-500 mt-0.5">Record trades you have placed manually</p>
        </div>
        <div className="flex items-center gap-2">
          <HumanOnlyBadge size="md" />
          <AdvisoryOnlyBadge size="md" />
        </div>
      </div>

      {/* Safety notice */}
      <div className="bg-slate-900 border border-amber-900/40 rounded-lg p-4 space-y-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-amber-400">
          <span>⚠</span>
          <span>HUMAN_ONLY — This system does not place trades</span>
        </div>
        <p className="text-xs text-slate-400">
          This form is a <strong className="text-white">record-keeping tool only</strong>. It does not submit, route, or execute any order on any broker or exchange.
          Broker API: <span className="text-emerald-400 font-mono font-semibold">NOT CONNECTED</span>.
          AI executions: <span className="text-emerald-400 font-mono font-bold">0</span>.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Form */}
        <div>
          <ManualTradeLogForm />
        </div>

        {/* Logged trades */}
        <div>
          <h2 className="text-sm font-semibold text-slate-300 mb-3">
            Previously Logged Trades ({MOCK_MANUAL_TRADES.length})
          </h2>
          {MOCK_MANUAL_TRADES.length === 0 ? (
            <div className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40">
              No trades logged yet.
            </div>
          ) : (
            <div className="space-y-3">
              {MOCK_MANUAL_TRADES.map((t) => (
                <div key={t.trade_id} className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-bold font-mono text-white">{t.ticker}</span>
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded font-mono ${
                        t.side === 'BUY'
                          ? 'text-emerald-400 bg-emerald-950/30 border border-emerald-900/40'
                          : 'text-red-400 bg-red-950/30 border border-red-900/40'
                      }`}>
                        {t.side === 'BUY' ? 'LONG' : 'SHORT'}
                      </span>
                    </div>
                    <HumanOnlyBadge />
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-xs mb-2">
                    <div className="bg-slate-900/40 rounded p-2">
                      <span className="text-slate-500 block">Qty</span>
                      <span className="font-mono text-slate-200">{t.quantity}</span>
                    </div>
                    <div className="bg-slate-900/40 rounded p-2">
                      <span className="text-slate-500 block">Price</span>
                      <span className="font-mono text-slate-200">${t.price.toFixed(2)}</span>
                    </div>
                    <div className="bg-slate-900/40 rounded p-2">
                      <span className="text-slate-500 block">Executed</span>
                      <span className="font-mono text-slate-400 text-xs">{formatTs(t.executed_at)}</span>
                    </div>
                  </div>

                  <p className="text-xs text-slate-400 leading-relaxed mb-2">{t.thesis}</p>

                  <div className="flex items-center gap-3 text-xs text-slate-600">
                    <span>{t.trade_id}</span>
                    <span>·</span>
                    <span>Broker order: {t.broker_order_id}</span>
                    <span>·</span>
                    <span>AI exec: <span className="text-emerald-400">0</span></span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
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
