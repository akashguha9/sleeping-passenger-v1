'use client';

import { useState } from 'react';
import { getChartStructure } from '@/lib/apiClient';
import type {
  ChartStructureResponse,
  ChartStructureReport,
  ChartMarketContext,
  ChartTrend,
  ChartVolatility,
  ChartSupportResistance,
} from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

const CHART_STATE_COLORS: Record<string, string> = {
  TRENDING_UP: 'text-emerald-400 bg-emerald-900/30 border-emerald-700/40',
  TRENDING_DOWN: 'text-red-400 bg-red-900/30 border-red-700/40',
  BREAKOUT_ATTEMPT: 'text-amber-400 bg-amber-900/30 border-amber-700/40',
  REVERSAL_RISK: 'text-orange-400 bg-orange-900/30 border-orange-700/40',
  VOLATILE_UNCLEAR: 'text-rose-400 bg-rose-900/30 border-rose-700/40',
  RANGE_BOUND: 'text-sky-400 bg-sky-900/30 border-sky-700/40',
  COMPRESSED: 'text-indigo-400 bg-indigo-900/30 border-indigo-700/40',
  INSUFFICIENT_DATA: 'text-slate-400 bg-slate-800/60 border-slate-700/40',
  ERROR: 'text-red-400 bg-red-900/30 border-red-700/40',
};

const TREND_DIR_COLORS: Record<string, string> = {
  uptrend: 'text-emerald-400',
  downtrend: 'text-red-400',
  sideways: 'text-sky-400',
  insufficient_data: 'text-slate-500',
};

const VOL_REGIME_COLORS: Record<string, string> = {
  compressed: 'text-indigo-400',
  normal: 'text-emerald-400',
  expanded: 'text-rose-400',
  insufficient_data: 'text-slate-500',
};

const NEXT_STEP_COLORS: Record<string, string> = {
  WATCH_ONLY: 'text-sky-400',
  REQUEST_MORE_EVIDENCE: 'text-amber-400',
  HUMAN_REVIEW: 'text-orange-400',
  NO_ACTION: 'text-slate-400',
};

function scoreBar(score: number): string {
  if (score >= 0.7) return 'bg-emerald-500';
  if (score >= 0.4) return 'bg-amber-500';
  return 'bg-red-500';
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

function InvariantRow({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5 rounded bg-slate-900/60">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-semibold ${mono ? 'font-mono' : ''} text-emerald-400`}>{value}</span>
    </div>
  );
}

function ContextPanel({ context }: { context: ChartMarketContext }) {
  const score = context.chart_confirmation_score;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <div className="text-sm font-semibold text-slate-300">Confirmation Score</div>
        <div className="flex-1 h-2 rounded bg-slate-700 overflow-hidden">
          <div
            className={`h-full rounded transition-all ${scoreBar(score)}`}
            style={{ width: `${Math.round(score * 100)}%` }}
          />
        </div>
        <div className={`text-sm font-mono font-bold ${scoreBar(score).replace('bg-', 'text-')}`}>
          {fmt(score)}
        </div>
      </div>
      {context.confirmation_reasons.length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-1">Confirmations</div>
          <ul className="space-y-0.5">
            {context.confirmation_reasons.map((r, i) => (
              <li key={i} className="text-xs text-emerald-300 flex gap-1.5">
                <span className="text-emerald-600">+</span>{r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {context.contradiction_reasons.length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-1">Contradictions</div>
          <ul className="space-y-0.5">
            {context.contradiction_reasons.map((r, i) => (
              <li key={i} className="text-xs text-red-300 flex gap-1.5">
                <span className="text-red-600">−</span>{r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TrendPanel({ trend }: { trend: ChartTrend }) {
  const dirColor = TREND_DIR_COLORS[trend.trend_direction] ?? 'text-slate-300';
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
      <div>
        <div className="text-slate-500 mb-0.5">Direction</div>
        <div className={`font-mono font-semibold uppercase ${dirColor}`}>{trend.trend_direction}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Strength</div>
        <div className="font-mono text-slate-200">{fmt(trend.trend_strength_score)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Short SMA</div>
        <div className="font-mono text-slate-300">{fmt(trend.short_sma, 4)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Medium SMA</div>
        <div className="font-mono text-slate-300">{fmt(trend.medium_sma, 4)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Long SMA</div>
        <div className="font-mono text-slate-300">{fmt(trend.long_sma, 4)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Dist from Short SMA</div>
        <div className="font-mono text-slate-300">{fmtPct(trend.distance_from_short_sma_pct)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Consec Up Closes</div>
        <div className="font-mono text-slate-200">{trend.consecutive_up_closes}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Consec Down Closes</div>
        <div className="font-mono text-slate-200">{trend.consecutive_down_closes}</div>
      </div>
    </div>
  );
}

function VolatilityPanel({ vol }: { vol: ChartVolatility }) {
  const regColor = VOL_REGIME_COLORS[vol.volatility_regime] ?? 'text-slate-300';
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
      <div>
        <div className="text-slate-500 mb-0.5">Regime</div>
        <div className={`font-mono font-semibold uppercase ${regColor}`}>{vol.volatility_regime}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">ATR</div>
        <div className="font-mono text-slate-300">{fmt(vol.average_true_range, 4)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">ATR %</div>
        <div className="font-mono text-slate-300">{fmtPct(vol.atr_pct)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Realized Vol Proxy</div>
        <div className="font-mono text-slate-300">{fmt(vol.realized_volatility_proxy, 4)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Range Expansion</div>
        <div className={`font-mono font-semibold ${vol.range_expansion_flag ? 'text-amber-400' : 'text-slate-500'}`}>
          {vol.range_expansion_flag ? 'YES' : 'no'}
        </div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Gap Flag</div>
        <div className={`font-mono font-semibold ${vol.gap_flag ? 'text-amber-400' : 'text-slate-500'}`}>
          {vol.gap_flag ? 'YES' : 'no'}
        </div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Large Move</div>
        <div className={`font-mono font-semibold ${vol.large_move_flag ? 'text-rose-400' : 'text-slate-500'}`}>
          {vol.large_move_flag ? 'YES' : 'no'}
        </div>
      </div>
    </div>
  );
}

function SupportResistancePanel({ sr }: { sr: ChartSupportResistance }) {
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
      <div>
        <div className="text-slate-500 mb-0.5">Breakout Proximity</div>
        <div className="font-mono font-semibold text-slate-200 uppercase">{sr.breakout_proximity.replace(/_/g, ' ')}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Rolling High</div>
        <div className="font-mono text-slate-300">{fmt(sr.rolling_high, 4)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Rolling Low</div>
        <div className="font-mono text-slate-300">{fmt(sr.rolling_low, 4)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Dist to High</div>
        <div className="font-mono text-slate-300">{fmtPct(sr.distance_to_rolling_high_pct)}</div>
      </div>
      <div>
        <div className="text-slate-500 mb-0.5">Dist to Low</div>
        <div className="font-mono text-slate-300">{fmtPct(sr.distance_to_rolling_low_pct)}</div>
      </div>
    </div>
  );
}

function ReportView({ report }: { report: ChartStructureReport }) {
  const nextStepColor = report.advisory?.suggested_next_step
    ? (NEXT_STEP_COLORS[report.advisory.suggested_next_step] ?? 'text-slate-300')
    : 'text-slate-300';

  return (
    <div className="space-y-4">
      {/* Advisory summary */}
      {report.advisory && (
        <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-2">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Advisory Summary</div>
          <p className="text-sm text-slate-200 leading-relaxed">{report.advisory.advisory_summary}</p>
          <div className="flex items-center gap-2 pt-0.5">
            <span className="text-xs text-slate-500">Suggested next step:</span>
            <span className={`text-xs font-mono font-semibold ${nextStepColor}`}>
              {report.advisory.suggested_next_step}
            </span>
          </div>
        </div>
      )}

      {/* Summary stats */}
      {report.summary && (
        <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-2">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">OHLCV Summary</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <div className="text-xs text-slate-500">Latest Close</div>
              <div className="text-lg font-bold font-mono text-white">
                {report.summary.latest_close != null ? `$${fmt(report.summary.latest_close, 4)}` : '—'}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Price Change</div>
              <div className={`text-sm font-mono font-semibold ${
                (report.summary.price_change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
              }`}>
                {fmtPct(report.summary.price_change_pct)}
              </div>
              <div className="text-xs text-slate-600 font-mono">
                {report.summary.price_change_abs != null
                  ? `${(report.summary.price_change_abs ?? 0) >= 0 ? '+' : ''}${fmt(report.summary.price_change_abs, 4)}`
                  : ''}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Candle Count</div>
              <div className="text-lg font-bold font-mono text-white">{report.summary.candle_count}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">H/L Range</div>
              <div className="text-sm font-mono text-slate-300">{fmtPct(report.summary.high_low_range_pct)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Avg Volume</div>
              <div className="text-xs font-mono text-slate-300">
                {report.summary.average_volume != null
                  ? Number(report.summary.average_volume).toLocaleString()
                  : '—'}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Latest Volume</div>
              <div className="text-xs font-mono text-slate-300">
                {report.summary.latest_volume != null
                  ? Number(report.summary.latest_volume).toLocaleString()
                  : '—'}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">First Candle</div>
              <div className="text-xs font-mono text-slate-400">{report.summary.first_timestamp ?? '—'}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Latest Candle</div>
              <div className="text-xs font-mono text-slate-400">{report.summary.latest_timestamp ?? '—'}</div>
            </div>
          </div>
        </div>
      )}

      {/* Three-column detail panels */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Trend */}
        {report.trend && (
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-3">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Trend</div>
            <TrendPanel trend={report.trend} />
          </div>
        )}

        {/* Volatility */}
        {report.volatility && (
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-3">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Volatility</div>
            <VolatilityPanel vol={report.volatility} />
          </div>
        )}

        {/* Support / Resistance */}
        {report.support_resistance && (
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-3">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Support / Resistance</div>
            <SupportResistancePanel sr={report.support_resistance} />
          </div>
        )}
      </div>

      {/* Confirmation / Context */}
      {report.context && (
        <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-3">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Market Context</div>
          <ContextPanel context={report.context} />
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

  async function handleLookup() {
    const sym = symbolInput.trim().toUpperCase();
    if (!sym) return;
    const lim = Math.max(1, Math.min(500, parseInt(limitInput, 10) || 100));
    setLoading(true);
    setQueried(true);
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

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleLookup();
  }

  const chartState = result?.report?.context?.chart_state ?? result?.chart_state;
  const stateColor = chartState ? (CHART_STATE_COLORS[chartState] ?? CHART_STATE_COLORS.INSUFFICIENT_DATA) : '';
  const hasReport = !!(result && result.report);
  const isInsufficient = !!(result && !result.report && result.candle_count === 0);
  const isError = !!(result && result.error);

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Chart Structure</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Advisory-only OHLCV feature engine — reads local market data, no broker connection
          </p>
        </div>
        <div className="flex items-center gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      {/* Safety banner */}
      <div className="bg-slate-900 border border-red-900/40 rounded-lg px-4 py-3">
        <p className="text-sm text-slate-400">
          <span className="text-white font-semibold">Chart structure is advisory-only. No execution. Human review required.</span>{' '}
          This panel reads historical OHLCV candles from local SQLite and computes technical features.
          It does{' '}
          <span className="text-red-400 font-semibold">not</span>{' '}
          place orders, connect to any broker, or produce buy/sell instructions.
          All results carry{' '}
          <span className="font-mono text-amber-400">ADVISORY_ONLY</span>,{' '}
          <span className="font-mono text-red-400">execution_gate=LOCKED</span>, and{' '}
          <span className="font-mono text-amber-400">HUMAN_REVIEW_REQUIRED</span>.
        </p>
      </div>

      {/* Execution invariants */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-2">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Execution Invariants</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <InvariantRow label="Advisory" value="ADVISORY_ONLY" />
          <InvariantRow label="Execution gate" value="LOCKED" />
          <InvariantRow label="Human review" value="REQUIRED" />
          <InvariantRow label="AI execution count" value="0" />
          <InvariantRow label="Broker API called" value="false" />
          <InvariantRow label="Broker order ID" value="NONE" />
          <InvariantRow label="Mode" value="HUMAN_REVIEW_REQUIRED" />
          <InvariantRow label="AI executions" value="AI_EXECUTION_COUNT=0" />
        </div>
      </div>

      {/* Symbol lookup */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Symbol Lookup</div>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">Symbol</label>
            <input
              type="text"
              placeholder="AAPL · BTC-USD · RELIANCE.NS"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-56 bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500 font-mono"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">Candle limit</label>
            <input
              type="number"
              min={1}
              max={500}
              value={limitInput}
              onChange={(e) => setLimitInput(e.target.value)}
              className="w-24 bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-slate-500 font-mono"
            />
          </div>
          <button
            onClick={handleLookup}
            disabled={loading || !symbolInput.trim()}
            className="px-4 py-1.5 rounded bg-slate-700 text-sm text-white font-medium hover:bg-slate-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? 'Loading…' : 'Fetch'}
          </button>
          {result && (
            <button
              onClick={() => { setResult(null); setQueried(false); }}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              clear
            </button>
          )}
        </div>
        <p className="text-xs text-slate-600 mt-2">
          Examples: <span className="font-mono">AAPL</span> · <span className="font-mono">BTC-USD</span> · <span className="font-mono">RELIANCE.NS</span> · <span className="font-mono">SPY</span>
        </p>
      </div>

      {/* Backend offline */}
      {backendOffline && !loading && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">BACKEND OFFLINE</span>
          <span className="text-slate-400">
            Could not reach the FastAPI server. Start it with:{' '}
            <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="text-center py-16 text-slate-500 text-sm">Fetching chart structure…</div>
      )}

      {/* Results */}
      {!loading && result && (
        <div className="space-y-4">
          {/* Header row */}
          <div className="flex items-center gap-3 flex-wrap">
            <div className="text-lg font-bold font-mono text-white">{result.symbol}</div>
            {chartState && (
              <span className={`text-xs font-semibold px-2 py-0.5 rounded border font-mono ${stateColor}`}>
                {chartState}
              </span>
            )}
            <span className="text-xs font-mono text-slate-500">
              {result.candle_count} candle{result.candle_count !== 1 ? 's' : ''}
            </span>
            <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/30 border border-red-800/40 text-red-400 font-mono">
              EXECUTION LOCKED
            </span>
            <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900/30 border border-amber-800/40 text-amber-400 font-mono">
              ADVISORY_ONLY
            </span>
            <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900/30 border border-amber-800/40 text-amber-400 font-mono">
              HUMAN_REVIEW_REQUIRED
            </span>
          </div>

          {/* Error state */}
          {isError && (
            <div className="bg-slate-900 border border-red-800/40 rounded-lg px-4 py-3 text-sm text-red-400">
              Error: {result.error}
            </div>
          )}

          {/* Insufficient data */}
          {isInsufficient && !isError && (
            <div className="bg-slate-900 border border-slate-700/60 rounded-lg px-4 py-5 space-y-2 text-center">
              <p className="text-slate-400 text-sm">
                {result.advisory_summary ?? 'No OHLCV data found for this symbol.'}
              </p>
              {result.run_ingestion && (
                <p className="text-xs text-slate-600">
                  Ingest market data first:{' '}
                  <span className="font-mono text-slate-400">{result.run_ingestion}</span>
                </p>
              )}
              <p className="text-xs text-slate-600 mt-1">
                Run:{' '}
                <span className="font-mono">python scripts/run_live_sources_phase2.py --source market_data --write</span>
              </p>
            </div>
          )}

          {/* Report */}
          {hasReport && <ReportView report={result.report!} />}
        </div>
      )}

      {/* Not yet queried */}
      {!loading && !queried && (
        <div className="text-center py-16 space-y-2">
          <p className="text-slate-500 text-sm">Enter a symbol above and press Fetch to view chart structure.</p>
          <p className="text-xs text-slate-600">
            Requires market data ingestion:{' '}
            <span className="font-mono">python scripts/run_live_sources_phase2.py --source market_data --write</span>
          </p>
        </div>
      )}
    </div>
  );
}
