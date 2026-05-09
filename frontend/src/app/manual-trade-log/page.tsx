'use client';

import { useState, useEffect } from 'react';
import { getManualTrades } from '@/lib/apiClient';
import type { ManualTradeListResponse } from '@/types';
import { ManualTradeLogForm } from '@/components/ManualTradeLogForm';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

export default function ManualTradeLogPage() {
  const [result, setResult] = useState<ManualTradeListResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getManualTrades().then((data) => {
      setResult(data);
      setLoading(false);
    });
  }, []);

  const trades = result?.trades ?? [];
  const isOffline = !loading && result === null;

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

      {isOffline && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">BACKEND OFFLINE</span>
          <span className="text-slate-400">
            Trade log unavailable. Start the FastAPI server:{' '}
            <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

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
            {loading ? 'Loading trades…' : `Previously Logged Trades (${trades.length})`}
          </h2>

          {loading ? (
            <div className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40">
              Loading…
            </div>
          ) : trades.length === 0 ? (
            <div className="text-sm text-slate-500 text-center py-8 bg-slate-800/40 rounded-lg border border-slate-700/40">
              {isOffline ? 'Backend offline — trade data unavailable.' : 'No trades logged yet.'}
            </div>
          ) : (
            <div className="space-y-3">
              {trades.map((t) => (
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
                      <span className="text-slate-500 block">Size</span>
                      <span className="font-mono text-slate-200">{t.quantity}</span>
                    </div>
                    <div className="bg-slate-900/40 rounded p-2">
                      <span className="text-slate-500 block">Price</span>
                      <span className="font-mono text-slate-200">${t.price.toFixed(2)}</span>
                    </div>
                    <div className="bg-slate-900/40 rounded p-2">
                      <span className="text-slate-500 block">Timestamp</span>
                      <span className="font-mono text-slate-400 text-xs">{formatTs(t.executed_at)}</span>
                    </div>
                  </div>

                  {t.thesis && (
                    <p className="text-xs text-slate-400 leading-relaxed mb-2">{t.thesis}</p>
                  )}

                  <div className="flex items-center gap-3 text-xs text-slate-600 flex-wrap">
                    <span className="font-mono truncate">{t.trade_id}</span>
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
