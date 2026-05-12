'use client';

import { useState, useEffect } from 'react';
import { getManualTrades } from '@/lib/apiClient';
import type { ManualTradeListResponse, ManualTradeLog } from '@/types';
import { ManualTradeLogForm } from '@/components/ManualTradeLogForm';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { SourceHealthWarnings } from '@/components/SourceHealthWarnings';

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
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="sp-eyebrow mb-1">Record-Keeping</div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)', letterSpacing: '-0.01em' }}
          >
            Manual Trade Log
          </h1>
          <p className="text-sm mt-1" style={{ color: 'var(--sp-mist)' }}>
            Record trades you have already placed manually — no orders are routed from here.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <HumanOnlyBadge size="md" />
          <AdvisoryOnlyBadge size="md" />
        </div>
      </div>

      <SourceHealthWarnings compact />

      {isOffline && (
        <div
          className="rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs"
          style={{
            background: 'rgba(214, 168, 90, 0.04)',
            border: '1px solid rgba(214, 168, 90, 0.22)',
          }}
        >
          <span className="sp-chip sp-chip-warn shrink-0">Backend Offline</span>
          <span style={{ color: 'var(--sp-mist)' }}>
            Trade log unavailable. Start the FastAPI server:{' '}
            <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>python scripts/api_server.py</span>
          </span>
        </div>
      )}

      <div
        className="sp-card p-5 space-y-2"
        style={{ borderColor: 'rgba(200, 154, 74, 0.2)' }}
      >
        <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: 'var(--sp-gold)' }}>
          <span>◆</span>
          <span>HUMAN_ONLY — This system does not place trades</span>
        </div>
        <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
          This form is a <strong style={{ color: 'var(--sp-bone)' }}>record-keeping tool only</strong>. It does not submit, route, or execute any order on any broker or exchange.
          Broker API: <span className="font-mono" style={{ color: 'var(--sp-cyan)' }}>NOT CONNECTED</span>.
          AI executions: <span className="font-mono font-bold" style={{ color: 'var(--sp-cyan)' }}>0</span>.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3">
          <ManualTradeLogForm />
        </div>

        <div className="lg:col-span-2">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="sp-eyebrow">Previously Logged</h2>
            <span className="text-xs font-mono" style={{ color: 'var(--sp-mist)' }}>
              {loading ? '…' : trades.length}
            </span>
          </div>

          {loading ? (
            <div className="sp-card-soft p-6 text-center text-sm" style={{ color: 'var(--sp-mist)' }}>
              Loading…
            </div>
          ) : trades.length === 0 ? (
            <div className="sp-card-soft p-6 text-center text-sm" style={{ color: 'var(--sp-mist)' }}>
              {isOffline ? 'Backend offline — trade data unavailable.' : 'No trades logged yet.'}
            </div>
          ) : (
            <div className="space-y-3">
              {trades.map((t) => (
                <TradeCard key={t.trade_id} t={t} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TradeCard({ t }: { t: ManualTradeLog }) {
  const leverage = leverageDisplay(t.leverage);
  const isLong = t.side === 'BUY';
  return (
    <div className="sp-card p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="font-bold font-mono text-sm" style={{ color: 'var(--sp-bone)' }}>
            {t.ticker}
          </span>
          <span
            className="text-[10px] font-semibold px-2 py-0.5 rounded-full font-mono uppercase tracking-widest"
            style={
              isLong
                ? {
                    color: 'var(--sp-cyan)',
                    border: '1px solid rgba(95, 189, 200, 0.32)',
                    background: 'rgba(95, 189, 200, 0.05)',
                  }
                : {
                    color: '#d57b6a',
                    border: '1px solid rgba(160, 74, 58, 0.32)',
                    background: 'rgba(160, 74, 58, 0.06)',
                  }
            }
          >
            {isLong ? 'LONG' : 'SHORT'}
          </span>
          {leverage !== '1.0x' && (
            <span className="sp-chip sp-chip-gold">Lev · {leverage}</span>
          )}
        </div>
        <HumanOnlyBadge />
      </div>

      <div className="grid grid-cols-4 gap-2 text-xs mb-3">
        <Stat label="Size" value={String(t.quantity)} />
        <Stat label="Price" value={`$${Number(t.price).toFixed(2)}`} />
        <Stat label="Leverage" value={leverage} accent />
        <Stat label="When" value={formatTs(t.executed_at)} small />
      </div>

      {t.thesis && (
        <p className="text-xs leading-relaxed mb-3" style={{ color: 'var(--sp-mist)' }}>
          {t.thesis}
        </p>
      )}

      <div className="flex items-center gap-3 text-[10px] font-mono flex-wrap" style={{ color: 'var(--sp-mist)' }}>
        <span className="truncate">{t.trade_id}</span>
        <span>·</span>
        <span>Broker order: {t.broker_order_id}</span>
        <span>·</span>
        <span>AI exec: <span style={{ color: 'var(--sp-cyan)' }}>0</span></span>
      </div>
    </div>
  );
}

function Stat({ label, value, accent, small }: { label: string; value: string; accent?: boolean; small?: boolean }) {
  return (
    <div
      className="rounded p-2"
      style={{
        background: 'rgba(13, 16, 21, 0.5)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="text-[9px] font-mono uppercase tracking-widest mb-0.5" style={{ color: 'var(--sp-mist)' }}>
        {label}
      </div>
      <div
        className={`font-mono ${small ? 'text-[10px]' : 'text-xs'}`}
        style={{ color: accent ? 'var(--sp-gold)' : 'var(--sp-bone)' }}
      >
        {value}
      </div>
    </div>
  );
}

function leverageDisplay(value: number | undefined | null): string {
  const n = typeof value === 'number' && !isNaN(value) && value >= 1 ? value : 1.0;
  // Show one decimal when not integer, otherwise still print 1.0x form
  if (Math.abs(n - Math.round(n)) < 1e-6) return `${n.toFixed(1)}x`;
  return `${n.toFixed(2).replace(/0$/, '')}x`;
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}
