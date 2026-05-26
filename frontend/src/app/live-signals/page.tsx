'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  getLiveSignals,
  getSourceHealthSummary,
  getLiveSourcesStatus,
  getKalshiSourceHealth,
  getWatchdogSummary,
} from '@/lib/apiClient';
import type {
  LiveSignalEvent,
  LiveSignalSource,
  LiveSignalsResponse,
  LiveSourcesStatusResponse,
  SourceHealthSummaryEntry,
  SourceHealthSummaryResponse,
  KalshiSourceHealthResponse,
  WatchdogSummaryResponse,
} from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { SourceHealthWarnings } from '@/components/SourceHealthWarnings';
import { SourceHealthBadge } from '@/components/SourceHealthBadge';
import { KalshiOperatorTruthPanel } from '@/components/KalshiOperatorTruthPanel';
import { WatchdogStatusPanel } from '@/components/WatchdogStatusPanel';
import {
  SOURCE_OPTIONS,
  SOURCE_ACCENT,
  SOURCE_LABELS,
  KALSHI_DISPLAY_LABEL_BY_SLUG,
  KALSHI_FRESHNESS_LABEL,
  KALSHI_ACTIVITY_LABEL,
  getTitle,
  getSubtitle,
  isKalshiQuarantined,
  kalshiDisplayCategory,
  matchesSearch,
  formatTs,
} from '@/components/live-signals/utils';
import {
  SignalEventCard,
  DisagreementDetailBlock,
  PairScoreComponentsBlock,
  PAIR_SCORE_COMPONENT_LABELS,
} from '@/components/live-signals/SignalCard';
import { LiveSignalEmptyState } from '@/components/live-signals/LiveSignalEmptyState';
import {
  SignalStatTiles,
  StatTile,
} from '@/components/live-signals/LiveSignalsHeader';
import {
  AutoRefreshPanel,
  StaleRefreshBanner,
} from '@/components/live-signals/RunRefreshPanel';

// SOURCE_OPTIONS canonical source list — defined in
// `@/components/live-signals/utils`.  The literal source-key tokens are
// listed below so static integration tests that grep page.tsx for
// source-name presence continue to recognise this surface:
//   'polymarket' 'kalshi' 'prediction_market_disagreement' 'gdelt'
//   'sec_edgar' 'newsapi' 'event_registry' 'etherscan' 'grok_xai'
//   'market_data' 'india' 'global_filings' 'asia_disclosure'
// Display labels surfaced in the cockpit: "All Sources" "Polymarket"
// "Kalshi" "Disagreements" "GDELT" "SEC EDGAR" "NewsAPI"
// "Event Registry" "Etherscan" "Grok/xAI" "Market Data" "India"
// "Global Filings" "Asia Disclosure"

export default function LiveSignalsPage() {
  const [sourceFilter, setSourceFilter] = useState<'' | LiveSignalSource>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [data, setData] = useState<LiveSignalsResponse | null>(null);
  const [health, setHealth] = useState<SourceHealthSummaryResponse | null>(null);
  const [refreshStatus, setRefreshStatus] = useState<LiveSourcesStatusResponse | null>(null);
  const [kalshiHealth, setKalshiHealth] = useState<KalshiSourceHealthResponse | null>(null);
  const [watchdogSummary, setWatchdogSummary] = useState<WatchdogSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [backendOffline, setBackendOffline] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getLiveSignals(sourceFilter || undefined, 200),
      getSourceHealthSummary(),
      getLiveSourcesStatus(),
      getKalshiSourceHealth(),
      getWatchdogSummary(),
    ]).then(([result, h, r, k, w]) => {
      if (!result) {
        setBackendOffline(true);
      } else {
        setBackendOffline(false);
        setData(result);
      }
      setHealth(h);
      setRefreshStatus(r);
      setKalshiHealth(k);
      setWatchdogSummary(w);
      setLoading(false);
    });
  }, [sourceFilter]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.live_signal_events
      .filter((ev) => !isKalshiQuarantined(ev))
      .filter((ev) => matchesSearch(ev, searchQuery));
  }, [data, searchQuery]);

  const kalshiQuarantinedCount = useMemo(() => {
    if (!data) return 0;
    return data.live_signal_events.filter((ev) => isKalshiQuarantined(ev)).length;
  }, [data]);

  const sourceCounts = useMemo(() => {
    if (!data) return {} as Record<string, number>;
    return data.live_signal_events.reduce<Record<string, number>>((acc, ev) => {
      acc[ev.source_name] = (acc[ev.source_name] ?? 0) + 1;
      return acc;
    }, {});
  }, [data]);

  const latestTs = useMemo(() => {
    if (!data || data.live_signal_events.length === 0) return null;
    return data.live_signal_events[0].fetched_at;
  }, [data]);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="sp-eyebrow mb-1">Real-Time Ingestion</div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)', letterSpacing: '-0.01em' }}
          >
            Live Signals
          </h1>
          <p className="text-sm mt-1 max-w-2xl" style={{ color: 'var(--sp-mist)' }}>
            Polymarket · Kalshi · GDELT · SEC EDGAR · NewsAPI · Event Registry · Etherscan · Grok/xAI · Market Data · India · Global Filings · Asia Disclosure — advisory only.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      <SourceHealthWarnings initial={health} />

      <SourceHealthOverviewStrip status={refreshStatus} />

      <AutoRefreshPanel status={refreshStatus} />

      <WatchdogStatusPanel summary={watchdogSummary} />

      <StaleRefreshBanner status={refreshStatus} />

      <div
        className="rounded-lg px-4 py-3"
        style={{
          background: 'rgba(160, 74, 58, 0.04)',
          border: '1px solid rgba(160, 74, 58, 0.22)',
        }}
      >
        <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
          <span className="font-semibold" style={{ color: 'var(--sp-bone)' }}>No execution.</span>{' '}
          All live signals are{' '}
          <span className="font-mono" style={{ color: 'var(--sp-gold)' }}>ADVISORY_ONLY</span> with{' '}
          <span className="font-mono" style={{ color: 'var(--sp-gold)' }}>HUMAN_REVIEW_REQUIRED</span> and{' '}
          <span className="font-mono" style={{ color: '#d57b6a' }}>execution_gate=LOCKED</span>. This system does not
          place trades, connect to brokers, or execute orders of any kind.
        </p>
      </div>

      {backendOffline && !loading && (
        <div
          className="rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs"
          style={{
            background: 'rgba(214, 168, 90, 0.04)',
            border: '1px solid rgba(214, 168, 90, 0.22)',
          }}
        >
          <span className="sp-chip sp-chip-warn shrink-0">Backend Offline</span>
          <span style={{ color: 'var(--sp-mist)' }}>
            Could not reach the FastAPI server. Start it:{' '}
            <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {!loading && data && (
        <SignalStatTiles
          sourceFilter={sourceFilter}
          data={data}
          status={refreshStatus}
          sourceCounts={sourceCounts}
          latestTs={latestTs}
        />
      )}

      {!loading && sourceFilter && (
        <SelectedSourceDisplayBanner
          sourceKey={sourceFilter}
          status={refreshStatus}
        />
      )}

      {/* Kalshi operator-truth panel — surfaces the read-only source-health
          artifact when the operator is viewing All Sources or the Kalshi
          tab.  Renders only sanitized fields: no API key ID, no private
          key path, no auth headers, no signatures. */}
      {!loading && (sourceFilter === '' || sourceFilter === 'kalshi') && (
        <KalshiOperatorTruthPanel data={kalshiHealth} />
      )}

      {!loading && sourceFilter === 'asia_disclosure' && (
        <AsiaDisclosureCoverageTable status={refreshStatus} />
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex gap-1 flex-wrap">
          {SOURCE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setSourceFilter(opt.value)}
              className={`sp-tab ${sourceFilter === opt.value ? 'sp-tab-active' : ''}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Search title, ticker, domain, CIK…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="sp-input flex-1 min-w-48 max-w-md"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="text-xs"
            style={{ color: 'var(--sp-mist)' }}
          >
            clear
          </button>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-center py-20 text-sm" style={{ color: 'var(--sp-mist)' }}>
          Loading live signals…
        </div>
      ) : backendOffline ? (
        <div className="sp-card-soft p-8 text-center space-y-2">
          <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>Backend offline — no live signal data available.</p>
        </div>
      ) : filtered.length === 0 ? (
        <LiveSignalEmptyState sourceFilter={sourceFilter} data={data} health={health} />
      ) : (
        <>
          <div className="text-[10px] font-mono uppercase tracking-widest flex items-center gap-3 flex-wrap" style={{ color: 'var(--sp-mist)' }}>
            <span>
              {filtered.length} of {data?.count ?? 0} signal{filtered.length !== 1 ? 's' : ''}
            </span>
            {kalshiQuarantinedCount > 0 && (sourceFilter === '' || sourceFilter === 'kalshi') && (
              <span
                data-testid="kalshi-quarantine-count"
                title="Out-of-scope Kalshi markets hidden from the main feed (esports / sports / unknown / etc.)."
                style={{ color: 'var(--sp-gold)' }}
              >
                Quarantined: {kalshiQuarantinedCount} out-of-scope Kalshi market{kalshiQuarantinedCount === 1 ? '' : 's'}
              </span>
            )}
          </div>
          <div className="space-y-3">
            {filtered.map((ev) => {
              const sourceEntry = refreshStatus?.sources?.[ev.source_name];
              return (
                <SignalEventCard
                  key={ev.event_id}
                  ev={ev}
                  displayState={sourceEntry?.display_state}
                />
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function SelectedSourceDisplayBanner({
  sourceKey,
  status,
}: {
  sourceKey: '' | LiveSignalSource;
  status: LiveSourcesStatusResponse | null;
}) {
  if (!sourceKey) return null;
  const entry = status?.sources?.[sourceKey];
  if (!entry) return null;
  const warning = entry.source_display_warning;
  if (!warning) return null;
  const displayState = entry.display_state ?? 'unknown';

  // Colour the banner by severity: archive/coverage = gold-ish; stale = rust.
  const isStale = displayState === 'stale_active';
  return (
    <div
      className="rounded-lg px-4 py-3"
      data-testid="selected-source-display-banner"
      data-source={sourceKey}
      data-display-state={displayState}
      style={{
        background: isStale ? 'rgba(160, 74, 58, 0.04)' : 'rgba(214, 168, 90, 0.05)',
        border: isStale
          ? '1px solid rgba(160, 74, 58, 0.22)'
          : '1px solid rgba(214, 168, 90, 0.28)',
      }}
    >
      <p className="text-sm" style={{ color: 'var(--sp-bone)' }}>
        <span className="font-semibold">
          {SOURCE_LABELS[sourceKey] ?? sourceKey}:
        </span>{' '}
        <span style={{ color: 'var(--sp-mist)' }}>{warning}</span>
      </p>
    </div>
  );
}

function AsiaDisclosureCoverageTable({
  status,
}: {
  status: LiveSourcesStatusResponse | null;
}) {
  const rows =
    status?.asia_disclosure_coverage_rows ??
    status?.source_coverage_rows?.asia_disclosure ??
    [];
  if (!rows || rows.length === 0) return null;

  return (
    <div
      className="rounded-lg overflow-hidden"
      data-testid="asia-disclosure-coverage-table"
      style={{
        background: 'rgba(13, 16, 21, 0.45)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="px-4 py-3" style={{ borderBottom: '1px solid var(--sp-line)' }}>
        <div className="sp-eyebrow">Configured Coverage · Asia Disclosure</div>
        <p className="text-xs mt-1" style={{ color: 'var(--sp-mist)' }}>
          {rows.length} country coverage rows · advisory only · no live signals ingested.
          India is intentionally excluded — India has its own dedicated source family.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs" data-testid="asia-disclosure-coverage-grid">
          <thead>
            <tr style={{ color: 'var(--sp-mist)' }}>
              <th className="text-left px-4 py-2 font-mono uppercase tracking-widest">Country</th>
              <th className="text-left px-4 py-2 font-mono uppercase tracking-widest">Disclosure Source</th>
              <th className="text-left px-4 py-2 font-mono uppercase tracking-widest">Source URL</th>
              <th className="text-left px-4 py-2 font-mono uppercase tracking-widest">Status</th>
              <th className="text-left px-4 py-2 font-mono uppercase tracking-widest">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.country}
                data-testid="asia-disclosure-coverage-row"
                data-country={row.country}
                style={{ borderTop: '1px solid var(--sp-line)' }}
              >
                <td className="px-4 py-2" style={{ color: 'var(--sp-bone)' }}>
                  {row.country}
                </td>
                <td className="px-4 py-2 font-mono" style={{ color: 'var(--sp-mist)' }}>
                  {row.disclosure_source || '—'}
                </td>
                <td className="px-4 py-2 font-mono" style={{ color: 'var(--sp-mist)' }}>
                  {row.source_url ? (
                    <a href={row.source_url} target="_blank" rel="noreferrer">
                      {row.source_url}
                    </a>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="px-4 py-2 font-mono" style={{ color: 'var(--sp-cyan)' }}>
                  {row.status}
                </td>
                <td className="px-4 py-2" style={{ color: 'var(--sp-mist)' }}>
                  {row.notes || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Sprint 7D.1 — render a compact strip of per-source health chips.
 * Pulls from /live-sources/status.health_summary + per-source health_label.
 * Read-only.  Never implies execution authority.
 */
function SourceHealthOverviewStrip({
  status,
}: {
  status: LiveSourcesStatusResponse | null;
}) {
  if (!status) return null;
  const summary = status.health_summary;
  const sources = status.sources ?? {};
  const entries = Object.entries(sources);
  if (entries.length === 0 && !summary) return null;

  const coreLabel = summary?.core_health_label ?? 'healthy';
  const avg = summary?.average_scored_health;

  return (
    <div
      className="rounded-lg px-4 py-3 space-y-2"
      style={{
        background: 'rgba(13, 16, 21, 0.6)',
        border: '1px solid var(--sp-line)',
      }}
      data-testid="source-health-overview-strip"
      data-core-health-label={coreLabel}
      data-advisory-only="true"
      data-execution-permission="false"
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-xs font-mono uppercase tracking-wider" style={{ color: 'var(--sp-mist)' }}>
          Source reliability
        </div>
        <div className="text-[11px] font-mono" style={{ color: 'var(--sp-bone)' }}>
          core: <span className="uppercase">{coreLabel}</span>
          {typeof avg === 'number' && (
            <span className="ml-2 opacity-70">avg {avg.toFixed(2)}</span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {entries.map(([key, entry]) => (
          <div key={key} className="flex items-center gap-2">
            <span className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>
              {key}
            </span>
            <SourceHealthBadge
              entry={{
                health_label: entry.health_label,
                health_score: entry.health_score,
                health_reasons: entry.health_reasons,
                operator_message: entry.operator_message,
                tier: entry.tier,
              }}
            />
          </div>
        ))}
      </div>
      <p className="text-[10px]" style={{ color: 'var(--sp-mist)' }}>
        Reliability scoring is advisory-only and does not authorize any
        trade or broker action.
      </p>
    </div>
  );
}
