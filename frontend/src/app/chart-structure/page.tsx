'use client';

import { useState } from 'react';
import { getChartStructure, bootstrapChartSymbol } from '@/lib/apiClient';
import type {
  ChartStructureResponse,
  ChartStructureReport,
  ChartMarketContext,
  ChartTrend,
  ChartVolatility,
  ChartSupportResistance,
  ChartBootstrapResponse,
  ChartFreshness,
  ChartFreshnessGate,
} from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { SourceHealthWarnings } from '@/components/SourceHealthWarnings';

const CHART_STATE_ACCENT: Record<string, string> = {
  TRENDING_UP: 'var(--sp-cyan)',
  TRENDING_DOWN: 'var(--sp-rust)',
  BREAKOUT_ATTEMPT: 'var(--sp-gold)',
  REVERSAL_RISK: '#d97757',
  VOLATILE_UNCLEAR: '#d57b6a',
  RANGE_BOUND: 'var(--sp-cyan)',
  COMPRESSED: '#a59ee6',
  INSUFFICIENT_DATA: 'var(--sp-mist)',
  ERROR: 'var(--sp-rust)',
};

const TREND_DIR_COLORS: Record<string, string> = {
  uptrend: 'var(--sp-cyan)',
  downtrend: 'var(--sp-rust)',
  sideways: 'var(--sp-mist)',
  insufficient_data: 'var(--sp-mist)',
};

const VOL_REGIME_COLORS: Record<string, string> = {
  compressed: '#a59ee6',
  normal: 'var(--sp-cyan)',
  expanded: '#d57b6a',
  insufficient_data: 'var(--sp-mist)',
};

const NEXT_STEP_COLORS: Record<string, string> = {
  WATCH_ONLY: 'var(--sp-cyan)',
  REQUEST_MORE_EVIDENCE: 'var(--sp-gold)',
  HUMAN_REVIEW: '#d97757',
  NO_ACTION: 'var(--sp-mist)',
};

type BootstrapPhase = 'idle' | 'discovering' | 'backfilling' | 'refreshing' | 'done' | 'failed';

function scoreColor(score: number): string {
  if (score >= 0.7) return 'var(--sp-cyan)';
  if (score >= 0.4) return 'var(--sp-gold)';
  return 'var(--sp-rust)';
}

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—';
  return v.toFixed(decimals);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function ContextPanel({ context }: { context: ChartMarketContext }) {
  const score = context.chart_confirmation_score;
  const color = scoreColor(score);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <div className="text-sm font-semibold" style={{ color: 'var(--sp-bone)' }}>Confirmation Score</div>
        <div className="flex-1 h-1.5 rounded overflow-hidden" style={{ background: 'rgba(232,231,227,0.06)' }}>
          <div
            className="h-full rounded transition-all"
            style={{ width: `${Math.round(score * 100)}%`, background: color }}
          />
        </div>
        <div className="text-sm font-mono font-bold" style={{ color }}>{fmt(score)}</div>
      </div>
      {context.confirmation_reasons.length > 0 && (
        <div>
          <div className="sp-eyebrow mb-1">Confirmations</div>
          <ul className="space-y-0.5">
            {context.confirmation_reasons.map((r, i) => (
              <li key={i} className="text-xs flex gap-1.5" style={{ color: 'var(--sp-bone)' }}>
                <span style={{ color: 'var(--sp-cyan)' }}>+</span>{r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {context.contradiction_reasons.length > 0 && (
        <div>
          <div className="sp-eyebrow mb-1">Contradictions</div>
          <ul className="space-y-0.5">
            {context.contradiction_reasons.map((r, i) => (
              <li key={i} className="text-xs flex gap-1.5" style={{ color: 'var(--sp-bone)' }}>
                <span style={{ color: 'var(--sp-rust)' }}>−</span>{r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TrendPanel({ trend }: { trend: ChartTrend }) {
  const dirColor = TREND_DIR_COLORS[trend.trend_direction] ?? 'var(--sp-bone)';
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
      <Pair label="Direction" value={trend.trend_direction} valueStyle={{ color: dirColor, textTransform: 'uppercase' }} />
      <Pair label="Strength" value={fmt(trend.trend_strength_score)} />
      <Pair label="Short SMA" value={fmt(trend.short_sma, 4)} />
      <Pair label="Medium SMA" value={fmt(trend.medium_sma, 4)} />
      <Pair label="Long SMA" value={fmt(trend.long_sma, 4)} />
      <Pair label="Dist from Short SMA" value={fmtPct(trend.distance_from_short_sma_pct)} />
      <Pair label="Consec Up Closes" value={String(trend.consecutive_up_closes)} />
      <Pair label="Consec Down Closes" value={String(trend.consecutive_down_closes)} />
    </div>
  );
}

function VolatilityPanel({ vol }: { vol: ChartVolatility }) {
  const regColor = VOL_REGIME_COLORS[vol.volatility_regime] ?? 'var(--sp-bone)';
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
      <Pair label="Regime" value={vol.volatility_regime} valueStyle={{ color: regColor, textTransform: 'uppercase' }} />
      <Pair label="ATR" value={fmt(vol.average_true_range, 4)} />
      <Pair label="ATR %" value={fmtPct(vol.atr_pct)} />
      <Pair label="Realized Vol" value={fmt(vol.realized_volatility_proxy, 4)} />
      <Pair
        label="Range Expansion"
        value={vol.range_expansion_flag ? 'YES' : 'no'}
        valueStyle={{ color: vol.range_expansion_flag ? 'var(--sp-gold)' : 'var(--sp-mist)' }}
      />
      <Pair
        label="Gap Flag"
        value={vol.gap_flag ? 'YES' : 'no'}
        valueStyle={{ color: vol.gap_flag ? 'var(--sp-gold)' : 'var(--sp-mist)' }}
      />
      <Pair
        label="Large Move"
        value={vol.large_move_flag ? 'YES' : 'no'}
        valueStyle={{ color: vol.large_move_flag ? '#d57b6a' : 'var(--sp-mist)' }}
      />
    </div>
  );
}

function SupportResistancePanel({ sr }: { sr: ChartSupportResistance }) {
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
      <Pair label="Breakout Proximity" value={sr.breakout_proximity.replace(/_/g, ' ')} valueStyle={{ textTransform: 'uppercase' }} />
      <Pair label="Rolling High" value={fmt(sr.rolling_high, 4)} />
      <Pair label="Rolling Low" value={fmt(sr.rolling_low, 4)} />
      <Pair label="Dist to High" value={fmtPct(sr.distance_to_rolling_high_pct)} />
      <Pair label="Dist to Low" value={fmtPct(sr.distance_to_rolling_low_pct)} />
    </div>
  );
}

function Pair({ label, value, valueStyle }: { label: string; value: string; valueStyle?: React.CSSProperties }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-widest mb-0.5" style={{ color: 'var(--sp-mist)' }}>{label}</div>
      <div className="font-mono" style={{ color: 'var(--sp-bone)', ...valueStyle }}>{value}</div>
    </div>
  );
}

function formatQuoteValue(value: number | null | undefined, currency: string | null | undefined): string {
  if (value == null) return '—';
  // Backend-provided currency drives display so we never hardcode $ for
  // an NSE symbol or INR for a US symbol.  When the source omits a
  // currency we fall back to a plain number — never a symbol guess.
  const formatted = value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
  if (currency && currency.trim()) {
    return `${formatted} ${currency.trim()}`;
  }
  return formatted;
}

function PriceTruthPanel({ response }: { response: ChartStructureResponse }) {
  const status = response.price_truth_status ?? response.price_truth?.price_truth_status ?? null;
  if (!status) return null;
  const reason = response.price_truth_reason ?? response.price_truth?.price_truth_reason ?? '';
  const dailyClose = response.latest_daily_close ?? response.price_truth?.latest_daily_close ?? null;
  const dailyTs = response.latest_daily_candle_utc ?? response.price_truth?.latest_daily_candle_utc ?? null;
  const quotePrice = response.latest_quote_price ?? response.price_truth?.latest_quote_price ?? null;
  const quoteCurrency = response.latest_quote_currency ?? response.price_truth?.latest_quote_currency ?? null;
  const quoteSource = response.latest_quote_source ?? response.price_truth?.latest_quote_source ?? null;
  const quoteTs = response.latest_quote_timestamp_utc ?? response.price_truth?.latest_quote_timestamp_utc ?? null;
  const ageMin = response.quote_age_minutes ?? response.price_truth?.quote_age_minutes ?? null;
  const delta = response.quote_price_delta ?? response.price_truth?.quote_price_delta ?? null;
  const deltaPct = response.quote_price_delta_pct ?? response.price_truth?.quote_price_delta_pct ?? null;
  const nextStep = response.price_truth?.suggested_next_step ?? '';

  const statusColor =
    status === 'QUOTE_ALIGNED'
      ? 'var(--sp-cyan)'
      : status === 'QUOTE_DIVERGES_FROM_DAILY' || status === 'INTERNAL_TIMESTAMP_MISMATCH'
        ? 'var(--sp-rust)'
        : 'var(--sp-gold)';

  const diverges =
    status === 'QUOTE_DIVERGES_FROM_DAILY' || status === 'INTERNAL_TIMESTAMP_MISMATCH';

  return (
    <div
      className="sp-card p-4 space-y-3"
      data-testid="chart-price-truth-panel"
      data-price-truth-status={status}
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="sp-eyebrow">Price Truth</div>
        <span
          className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded border"
          style={{ color: statusColor, borderColor: statusColor }}
          data-testid="price-truth-status-chip"
        >
          {status.replace(/_/g, ' ')}
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>
            Latest daily close
          </div>
          <div className="font-mono" style={{ color: 'var(--sp-bone)' }} data-testid="price-truth-daily-close">
            {formatQuoteValue(dailyClose, quoteCurrency)}
          </div>
          <div className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>
            {dailyTs ?? '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>
            Latest quote
          </div>
          <div className="font-mono" style={{ color: 'var(--sp-bone)' }} data-testid="price-truth-quote-price">
            {formatQuoteValue(quotePrice, quoteCurrency)}
          </div>
          <div className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }} data-testid="price-truth-quote-meta">
            {quoteSource ?? '—'}
            {quoteTs ? ` · ${quoteTs}` : ''}
            {ageMin != null ? ` · ${ageMin.toFixed(0)} min old` : ''}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>
            Delta vs daily close
          </div>
          <div
            className="font-mono"
            style={{ color: diverges ? 'var(--sp-rust)' : 'var(--sp-bone)' }}
            data-testid="price-truth-delta"
          >
            {delta == null ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(2)}`}
            {deltaPct != null ? ` (${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(2)}%)` : ''}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>
            Suggested next step
          </div>
          <div className="font-mono" style={{ color: statusColor }} data-testid="price-truth-next-step">
            {nextStep || '—'}
          </div>
        </div>
      </div>
      {reason && (
        <div
          className="text-[11px] leading-relaxed border rounded px-3 py-2"
          style={{
            borderColor: diverges ? 'var(--sp-rust)' : 'rgba(232,231,227,0.12)',
            color: diverges ? 'var(--sp-rust)' : 'var(--sp-mist)',
            background: diverges ? 'rgba(199, 87, 73, 0.07)' : 'transparent',
          }}
          data-testid="price-truth-reason"
        >
          {reason}
        </div>
      )}
      <div className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>
        Record-keeping only · No broker call · advisory_status=ADVISORY_ONLY
      </div>
    </div>
  );
}

function ReportView({
  report,
  response,
}: {
  report: ChartStructureReport;
  response: ChartStructureResponse;
}) {
  const nextStepColor = report.advisory?.suggested_next_step
    ? (NEXT_STEP_COLORS[report.advisory.suggested_next_step] ?? 'var(--sp-bone)')
    : 'var(--sp-bone)';

  return (
    <div className="space-y-4">
      {report.advisory && (
        <div className="sp-card p-4 space-y-2">
          <div className="sp-eyebrow">Advisory Summary</div>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--sp-bone)' }}>
            {report.advisory.advisory_summary}
          </p>
          <div className="flex items-center gap-2 pt-0.5">
            <span className="text-xs" style={{ color: 'var(--sp-mist)' }}>Suggested next step:</span>
            <span className="text-xs font-mono font-semibold" style={{ color: nextStepColor }}>
              {report.advisory.suggested_next_step}
            </span>
          </div>
        </div>
      )}

      <PriceTruthPanel response={response} />

      {report.summary && (
        <div className="sp-card p-4 space-y-3">
          <div className="sp-eyebrow">OHLCV Summary</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <div
                className="text-[10px] font-mono uppercase tracking-widest mb-1"
                style={{ color: 'var(--sp-mist)' }}
              >
                Latest Daily Close
              </div>
              <div
                className="text-lg font-bold font-mono"
                style={{ color: 'var(--sp-bone)' }}
                data-testid="chart-latest-close"
                title="Close of the latest daily OHLCV candle — not the current live quote."
              >
                {report.summary.latest_close != null
                  ? fmt(report.summary.latest_close, 4)
                  : '—'}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>Price Change</div>
              <div
                className="text-sm font-mono font-semibold"
                style={{ color: (report.summary.price_change_pct ?? 0) >= 0 ? 'var(--sp-cyan)' : 'var(--sp-rust)' }}
              >
                {fmtPct(report.summary.price_change_pct)}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>Candle Count</div>
              <div className="text-lg font-bold font-mono" style={{ color: 'var(--sp-bone)' }}>{report.summary.candle_count}</div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>H/L Range</div>
              <div className="text-sm font-mono" style={{ color: 'var(--sp-bone)' }}>{fmtPct(report.summary.high_low_range_pct)}</div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>Avg Volume</div>
              <div className="text-xs font-mono" style={{ color: 'var(--sp-bone)' }}>
                {report.summary.average_volume != null ? Number(report.summary.average_volume).toLocaleString() : '—'}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>Latest Volume</div>
              <div className="text-xs font-mono" style={{ color: 'var(--sp-bone)' }}>
                {report.summary.latest_volume != null ? Number(report.summary.latest_volume).toLocaleString() : '—'}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>First Candle</div>
              <div className="text-xs font-mono" style={{ color: 'var(--sp-mist)' }}>{report.summary.first_timestamp ?? '—'}</div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest mb-1" style={{ color: 'var(--sp-mist)' }}>Latest Candle</div>
              <div className="text-xs font-mono" style={{ color: 'var(--sp-mist)' }}>{report.summary.latest_timestamp ?? '—'}</div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {report.trend && (
          <div className="sp-card p-4 space-y-3">
            <div className="sp-eyebrow">Trend</div>
            <TrendPanel trend={report.trend} />
          </div>
        )}
        {report.volatility && (
          <div className="sp-card p-4 space-y-3">
            <div className="sp-eyebrow">Volatility</div>
            <VolatilityPanel vol={report.volatility} />
          </div>
        )}
        {report.support_resistance && (
          <div className="sp-card p-4 space-y-3">
            <div className="sp-eyebrow">Support / Resistance</div>
            <SupportResistancePanel sr={report.support_resistance} />
          </div>
        )}
      </div>

      {report.context && (
        <div className="sp-card p-4 space-y-3">
          <div className="sp-eyebrow">Market Context</div>
          <ContextPanel context={report.context} />
        </div>
      )}
    </div>
  );
}

function BootstrapPrompt({
  symbol,
  onConfirm,
  onCancel,
}: {
  symbol: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="sp-card p-6 space-y-4"
      style={{ borderColor: 'rgba(200, 154, 74, 0.32)' }}
    >
      <div className="sp-eyebrow" style={{ color: 'var(--sp-gold)' }}>Symbol Bootstrap</div>
      <div className="text-sm leading-relaxed" style={{ color: 'var(--sp-bone)' }}>
        Symbol data not found locally for{' '}
        <span className="font-mono font-bold">{symbol}</span>.
        Do you want to discover/register this symbol and download full historical OHLCV data?
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <span className="sp-chip sp-chip-gold">period · max</span>
        <span className="sp-chip sp-chip-cyan">interval · 1d</span>
        <span className="sp-chip">market-data only</span>
      </div>
      <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
        This only downloads local market data into SQLite. It does not place trades or connect to any broker.
        Advisory-only · broker_api_called = <span className="font-mono">false</span> · ai_execution_count = <span className="font-mono">0</span>.
      </p>
      <div className="flex items-center gap-3">
        <button type="button" onClick={onConfirm} className="sp-btn-primary" style={{ width: 'auto', minWidth: '180px' }}>
          Yes, download data
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2.5 rounded text-sm uppercase tracking-widest text-[12px]"
          style={{
            color: 'var(--sp-mist)',
            border: '1px solid var(--sp-line-strong)',
            background: 'transparent',
            letterSpacing: '0.16em',
          }}
        >
          No, cancel
        </button>
      </div>
    </div>
  );
}

function BootstrapProgress({
  phase,
  symbol,
  result,
}: {
  phase: BootstrapPhase;
  symbol: string;
  result: ChartBootstrapResponse | null;
}) {
  const phaseLabel: Record<BootstrapPhase, string> = {
    idle: '',
    discovering: 'Discovering/registering symbol…',
    backfilling: 'Downloading OHLCV candles…',
    refreshing: 'Completed, refreshing chart…',
    done: 'Bootstrap complete.',
    failed: 'Bootstrap failed.',
  };
  const accent =
    phase === 'failed'
      ? 'var(--sp-rust)'
      : phase === 'done' || phase === 'refreshing'
      ? 'var(--sp-cyan)'
      : 'var(--sp-gold)';
  return (
    <div className="sp-card p-5 space-y-3">
      <div className="flex items-center gap-3">
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{
            background: accent,
            boxShadow: `0 0 10px ${accent}`,
            animation: phase === 'failed' || phase === 'done' ? 'none' : 'pulse 1.6s ease-in-out infinite',
          }}
        />
        <div className="sp-eyebrow" style={{ color: accent }}>{phaseLabel[phase]}</div>
      </div>
      <div className="text-xs font-mono" style={{ color: 'var(--sp-mist)' }}>
        symbol: <span style={{ color: 'var(--sp-bone)' }}>{symbol}</span> · period: max · interval: 1d
      </div>
      {result && (
        <div className="space-y-1 text-xs" style={{ color: 'var(--sp-mist)' }}>
          <div>
            discovery_status:{' '}
            <span className="font-mono" style={{ color: statusColor(result.discovery_status) }}>
              {result.discovery_status}
            </span>
          </div>
          <div>
            backfill_status:{' '}
            <span className="font-mono" style={{ color: statusColor(result.backfill_status) }}>
              {result.backfill_status}
            </span>
          </div>
          {result.candles_written != null && (
            <div>
              candles_written: <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>{result.candles_written}</span>
            </div>
          )}
          {result.message && (
            <div className="pt-1" style={{ color: 'var(--sp-bone)' }}>{result.message}</div>
          )}
        </div>
      )}
      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.35; }
        }
      `}</style>
    </div>
  );
}

function statusColor(status: string): string {
  if (status === 'OK') return 'var(--sp-cyan)';
  if (status === 'ERROR') return 'var(--sp-rust)';
  return 'var(--sp-mist)';
}

const FRESHNESS_GATE_COLOR: Record<ChartFreshnessGate, string> = {
  PASS: 'var(--sp-cyan)',
  WARN: 'var(--sp-gold)',
  BLOCK: 'var(--sp-rust)',
};

function freshnessGateColor(gate: ChartFreshnessGate | undefined): string {
  if (!gate) return 'var(--sp-mist)';
  return FRESHNESS_GATE_COLOR[gate] ?? 'var(--sp-mist)';
}

function FreshnessPanel({
  freshness,
  symbol,
}: {
  freshness: ChartFreshness;
  symbol: string;
}) {
  const gate = freshness.freshness_gate;
  const color = freshnessGateColor(gate);
  const status = freshness.data_freshness_status;
  const isBlock = gate === 'BLOCK';
  const isWarn = gate === 'WARN';
  const ageStr =
    freshness.data_age_days != null
      ? `${freshness.data_age_days.toFixed(1)} days old`
      : 'unknown age';
  return (
    <div
      className="sp-card p-4 space-y-2"
      data-testid="chart-freshness-panel"
      data-freshness-gate={gate}
      data-freshness-status={status}
      style={{
        borderColor: isBlock
          ? 'rgba(160, 74, 58, 0.5)'
          : isWarn
          ? 'rgba(214, 168, 90, 0.45)'
          : 'rgba(94, 174, 168, 0.35)',
        background: isBlock
          ? 'rgba(160, 74, 58, 0.06)'
          : isWarn
          ? 'rgba(214, 168, 90, 0.04)'
          : 'transparent',
      }}
    >
      <div className="flex items-center gap-3 flex-wrap">
        <span
          className="text-[10px] font-mono uppercase tracking-widest font-semibold px-2 py-0.5 rounded"
          style={{
            color,
            border: `1px solid ${color}55`,
            background: 'rgba(232,231,227,0.03)',
          }}
          data-testid="chart-freshness-gate"
        >
          Freshness · {gate ?? '—'}
        </span>
        <span
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="chart-freshness-status"
        >
          {status ?? '—'}
        </span>
        <span
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="chart-freshness-source"
        >
          source · {freshness.source_kind ?? 'UNKNOWN'}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest mb-0.5" style={{ color: 'var(--sp-mist)' }}>
            Latest candle (UTC)
          </div>
          <div className="font-mono" style={{ color: 'var(--sp-bone)' }} data-testid="chart-latest-candle-utc">
            {freshness.latest_candle_utc ?? '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest mb-0.5" style={{ color: 'var(--sp-mist)' }}>
            Data age
          </div>
          <div className="font-mono" style={{ color: 'var(--sp-bone)' }} data-testid="chart-data-age-days">
            {ageStr}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest mb-0.5" style={{ color: 'var(--sp-mist)' }}>
            First candle (UTC)
          </div>
          <div className="font-mono" style={{ color: 'var(--sp-bone)' }}>
            {freshness.first_candle_utc ?? '—'}
          </div>
        </div>
      </div>
      {(isBlock || isWarn) && (
        <div
          className="text-sm leading-relaxed"
          style={{ color: isBlock ? '#d57b6a' : 'var(--sp-bone)' }}
          data-testid="chart-freshness-warning"
        >
          {isBlock
            ? `Market data for ${symbol} is ${(status ?? 'stale').toLowerCase()}. Chart structure analysis is blocked until fresh data is loaded. ${freshness.freshness_reason}`
            : `Market data for ${symbol} is delayed (${freshness.freshness_reason}). Treat any advisory verdict with caution and refresh OHLCV before relying on it.`}
        </div>
      )}
    </div>
  );
}

export default function ChartStructurePage() {
  const [symbolInput, setSymbolInput] = useState('');
  const [limitInput, setLimitInput] = useState('100');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ChartStructureResponse | null>(null);
  const [backendOffline, setBackendOffline] = useState(false);
  const [queried, setQueried] = useState(false);

  // Bootstrap state
  const [bootstrapPhase, setBootstrapPhase] = useState<BootstrapPhase>('idle');
  const [bootstrapResult, setBootstrapResult] = useState<ChartBootstrapResponse | null>(null);
  const [bootstrappingSymbol, setBootstrappingSymbol] = useState<string | null>(null);

  async function fetchChartFor(sym: string, lim: number) {
    setLoading(true);
    setBackendOffline(false);
    const data = await getChartStructure(sym, lim);
    if (!data) {
      setBackendOffline(true);
      setResult(null);
    } else {
      setResult(data);
    }
    setLoading(false);
  }

  async function handleLookup() {
    const sym = symbolInput.trim().toUpperCase();
    if (!sym) return;
    const lim = Math.max(1, Math.min(500, parseInt(limitInput, 10) || 100));
    setBootstrapPhase('idle');
    setBootstrapResult(null);
    setQueried(true);
    await fetchChartFor(sym, lim);
  }

  async function handleBootstrapConfirm() {
    if (!result) return;
    const sym = result.symbol;
    if (bootstrappingSymbol === sym) return; // prevent duplicate
    const lim = Math.max(1, Math.min(500, parseInt(limitInput, 10) || 100));

    setBootstrappingSymbol(sym);
    setBootstrapPhase('discovering');
    setBootstrapResult(null);

    // Single backend call performs discovery + backfill. We flip the phase
    // to "backfilling" optimistically so the UI conveys progress while the
    // request is in-flight (the request itself can take 20–60s on a real
    // backfill, but we don't block the user from clicking Cancel).
    const backfillTimer = setTimeout(() => {
      setBootstrapPhase((p) => (p === 'discovering' ? 'backfilling' : p));
    }, 1200);

    const data = await bootstrapChartSymbol(sym, 'max', '1d');
    clearTimeout(backfillTimer);

    if (!data) {
      setBootstrapPhase('failed');
      setBootstrapResult({
        ok: false,
        symbol: sym,
        period: 'max',
        interval: '1d',
        discovery_status: 'ERROR',
        backfill_status: 'SKIPPED',
        candles_written: null,
        message: 'Backend unreachable. Start the API server and try again.',
        advisory_status: 'ADVISORY_ONLY',
        execution_mode: 'HUMAN_ONLY',
        execution_gate: 'LOCKED',
        broker_api_called: false,
        broker_order_id: 'NONE',
        ai_execution_count: 0,
        human_review_required: true,
      });
      setBootstrappingSymbol(null);
      return;
    }

    setBootstrapResult(data);
    if (!data.ok) {
      setBootstrapPhase('failed');
      setBootstrappingSymbol(null);
      return;
    }

    setBootstrapPhase('refreshing');
    await fetchChartFor(sym, lim);
    setBootstrapPhase('done');
    setBootstrappingSymbol(null);
  }

  function handleBootstrapCancel() {
    setBootstrapPhase('idle');
    setBootstrapResult(null);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleLookup();
  }

  const chartState = result?.report?.context?.chart_state ?? result?.chart_state;
  const stateAccent = chartState ? (CHART_STATE_ACCENT[chartState] ?? 'var(--sp-mist)') : '';
  const freshness = result?.freshness ?? null;
  const freshnessGate: ChartFreshnessGate | undefined =
    result?.freshness_gate ?? freshness?.freshness_gate ?? undefined;
  const isFreshnessBlocked = freshnessGate === 'BLOCK';
  // Render the engine's chart-structure report only when (a) we got one
  // back AND (b) the freshness gate did not block.  This guarantees that
  // the operator never sees a normal "TRENDING_UP" verdict over 2004
  // fixture data even if a downstream component would otherwise render
  // it.  Stale-blocked responses already null out `report` server-side;
  // this is belt-and-braces.
  const hasReport = !!(result && result.report) && !isFreshnessBlocked;
  const isMissingData = !!(
    result && !result.report && result.candle_count === 0 && result.can_bootstrap !== false
  );
  const isError = !!(result && result.error);
  const showBootstrapPrompt =
    isMissingData && !isError && bootstrapPhase === 'idle' && !bootstrappingSymbol;
  const isBootstrapping =
    bootstrapPhase === 'discovering' ||
    bootstrapPhase === 'backfilling' ||
    bootstrapPhase === 'refreshing';

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="sp-eyebrow mb-1">Technical Engine</div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)', letterSpacing: '-0.01em' }}
          >
            Chart Structure
          </h1>
          <p className="text-sm mt-1" style={{ color: 'var(--sp-mist)' }}>
            Advisory-only OHLCV feature engine — reads local market data. No broker connection.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      <SourceHealthWarnings compact />

      <div
        className="rounded-lg px-4 py-3"
        style={{
          background: 'rgba(160, 74, 58, 0.04)',
          border: '1px solid rgba(160, 74, 58, 0.22)',
        }}
      >
        <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
          <span className="font-semibold" style={{ color: 'var(--sp-bone)' }}>
            Chart structure is advisory-only. No execution. Human review required.
          </span>{' '}
          This panel reads historical OHLCV candles from local SQLite and computes technical features.
          It does <span className="font-semibold" style={{ color: '#d57b6a' }}>not</span> place orders,
          connect to any broker, or produce buy/sell instructions.
        </p>
      </div>

      <div className="sp-card p-5">
        <div className="sp-eyebrow mb-3">Symbol Lookup</div>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>Symbol</label>
            <input
              type="text"
              placeholder="AAPL · BTC-USD · RELIANCE.NS"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              onKeyDown={handleKeyDown}
              className="sp-input font-mono w-56"
              disabled={isBootstrapping}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>Candle Limit</label>
            <input
              type="number"
              min={1}
              max={500}
              value={limitInput}
              onChange={(e) => setLimitInput(e.target.value)}
              className="sp-input font-mono w-24"
              disabled={isBootstrapping}
            />
          </div>
          <button
            onClick={handleLookup}
            disabled={loading || isBootstrapping || !symbolInput.trim()}
            className="sp-btn-primary"
            style={{ width: 'auto', minWidth: '120px' }}
          >
            {loading ? 'Loading…' : 'Fetch'}
          </button>
          {result && (
            <button
              onClick={() => { setResult(null); setQueried(false); setBootstrapPhase('idle'); setBootstrapResult(null); }}
              className="text-xs"
              style={{ color: 'var(--sp-mist)' }}
            >
              clear
            </button>
          )}
        </div>
        <p className="text-xs mt-3" style={{ color: 'var(--sp-mist)' }}>
          Examples: <span className="font-mono">AAPL</span> · <span className="font-mono">BTC-USD</span> · <span className="font-mono">RELIANCE.NS</span> · <span className="font-mono">SPY</span>
        </p>
      </div>

      {backendOffline && !loading && (
        <div
          className="rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs"
          style={{ background: 'rgba(214, 168, 90, 0.04)', border: '1px solid rgba(214, 168, 90, 0.22)' }}
        >
          <span className="sp-chip sp-chip-warn shrink-0">Backend Offline</span>
          <span style={{ color: 'var(--sp-mist)' }}>
            Could not reach the FastAPI server. Start it:{' '}
            <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {loading && (
        <div className="text-center py-16 text-sm" style={{ color: 'var(--sp-mist)' }}>
          Fetching chart structure…
        </div>
      )}

      {/* Bootstrap progress card sits above results */}
      {bootstrapPhase !== 'idle' && result && (
        <BootstrapProgress phase={bootstrapPhase} symbol={result.symbol} result={bootstrapResult} />
      )}

      {!loading && result && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="text-lg font-bold font-mono" style={{ color: 'var(--sp-bone)' }}>{result.symbol}</div>
            {chartState && (
              <span
                className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full uppercase tracking-widest"
                style={{
                  color: stateAccent,
                  border: `1px solid ${stateAccent.startsWith('var') ? 'rgba(232,231,227,0.18)' : `${stateAccent}55`}`,
                  background: 'rgba(232,231,227,0.03)',
                }}
              >
                {chartState}
              </span>
            )}
            <span className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>
              {result.candle_count} candle{result.candle_count !== 1 ? 's' : ''}
            </span>
            <span className="sp-chip sp-chip-rust">Execution · Locked</span>
            <span className="sp-chip sp-chip-gold">Advisory_Only</span>
            <span className="sp-chip sp-chip-warn">Human_Review_Required</span>
          </div>

          {isError && (
            <div
              className="rounded-lg px-4 py-3 text-sm"
              style={{ color: '#d57b6a', background: 'rgba(160, 74, 58, 0.06)', border: '1px solid rgba(160, 74, 58, 0.32)' }}
            >
              Error: {result.error}
            </div>
          )}

          {freshness && (
            <FreshnessPanel freshness={freshness} symbol={result.symbol} />
          )}

          {isFreshnessBlocked && (
            <div
              className="sp-card p-4 space-y-2"
              data-testid="chart-stale-data-block"
              style={{
                borderColor: 'rgba(160, 74, 58, 0.5)',
                background: 'rgba(160, 74, 58, 0.06)',
              }}
            >
              <div className="sp-eyebrow" style={{ color: '#d57b6a' }}>
                Stale data — analysis blocked
              </div>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--sp-bone)' }}>
                {result.advisory_summary ??
                  `Market data for ${result.symbol} is stale. Chart structure analysis is blocked until fresh data is loaded.`}
              </p>
              <div className="flex items-center gap-2 pt-0.5 flex-wrap">
                <span className="text-xs" style={{ color: 'var(--sp-mist)' }}>
                  Suggested next step:
                </span>
                <span
                  className="text-xs font-mono font-semibold"
                  style={{ color: 'var(--sp-gold)' }}
                  data-testid="chart-suggested-next-step"
                >
                  {result.suggested_next_step ?? 'DATA_REFRESH_REQUIRED'}
                </span>
              </div>
            </div>
          )}

          {showBootstrapPrompt && (
            <BootstrapPrompt
              symbol={result.symbol}
              onConfirm={handleBootstrapConfirm}
              onCancel={handleBootstrapCancel}
            />
          )}

          {/* Show the no-data block only when the user declined / closed the prompt */}
          {isMissingData && !isError && !showBootstrapPrompt && bootstrapPhase === 'idle' && (
            <div className="sp-card-soft p-6 text-center space-y-2">
              <p className="text-sm" style={{ color: 'var(--sp-bone)' }}>
                {result.message ?? result.advisory_summary ?? 'No OHLCV data found for this symbol.'}
              </p>
              <p className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
                Re-open the bootstrap prompt by fetching this symbol again.
              </p>
            </div>
          )}

          {hasReport && <ReportView report={result.report!} response={result} />}
        </div>
      )}

      {!loading && !queried && (
        <div className="text-center py-16 space-y-2">
          <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
            Enter a symbol above and press Fetch to view chart structure.
          </p>
          <p className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
            Missing symbols can be downloaded from the UI — no terminal needed.
          </p>
        </div>
      )}
    </div>
  );
}
