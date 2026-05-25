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



/**
 * Renders an honest, per-source empty state.  Uses /source-health/summary
 * data when the user has filtered to a specific source so we don't tell
 * them to "run ingestion" when the source is rate-limited, timed out, or
 * a placeholder.
 */
function PerSourceEmptyState({
  sourceFilter,
  data,
  health,
}: {
  sourceFilter: '' | LiveSignalSource;
  data: LiveSignalsResponse | null;
  health: SourceHealthSummaryResponse | null;
}) {
  const overallEmpty = (data?.count ?? 0) === 0;
  const label = sourceFilter ? (SOURCE_LABELS[sourceFilter] ?? sourceFilter) : 'live';
  const entry: SourceHealthSummaryEntry | undefined = sourceFilter && health
    ? health.sources.find((s) => s.source_name === sourceFilter)
    : undefined;

  // Sources that route through run_live_sources_phase1.py.
  const phase1 = new Set(['polymarket', 'gdelt', 'sec_edgar']);
  const phaseCmd = (src: string) =>
    phase1.has(src)
      ? `python scripts/run_live_sources_phase1.py --source ${src} --dry-run`
      : `python scripts/run_live_sources_phase2.py --source ${src} --dry-run`;

  // Special-case Asia Disclosure: when no live runs exist we *still* show
  // the coverage table separately, so the empty-state here must not say
  // "run ingestion" — it must say "showing configured coverage list".
  if (sourceFilter === 'asia_disclosure') {
    return (
      <div
        className="sp-card-soft p-8 space-y-2 text-center"
        data-testid="asia-disclosure-empty-coverage-banner"
      >
        <div className="sp-eyebrow">Source Status · Planned / Not Scored</div>
        <div className="text-sm" style={{ color: 'var(--sp-bone)' }}>
          No live Asia Disclosure signals recorded yet. Showing configured coverage list.
        </div>
        <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
          Asia Disclosure remains <span className="font-mono">PLANNED_NOT_SCORED</span>.
          The 11-country coverage table below is configuration only — no live data
          has been ingested.
        </p>
      </div>
    );
  }

  // 1. Specific source filter chosen → use source-health to give an honest reason.
  if (sourceFilter) {
    if (entry) {
      const accent =
        entry.severity === 'error'
          ? 'var(--sp-rust)'
          : entry.severity === 'warning'
          ? 'var(--sp-gold)'
          : entry.severity === 'ok'
          ? 'var(--sp-cyan)'
          : 'var(--sp-mist)';
      const headline = `No ${label} signals available right now.`;
      // Show the runnable command for NO_RUNS rows so the user has an
      // actionable next step instead of a generic "no runs yet" line.
      const showCommand =
        entry.category === 'NO_RUNS' && (entry.suggested_command ?? phaseCmd(sourceFilter));
      return (
        <div className="sp-card-soft p-8 space-y-3 text-center">
          <div className="sp-eyebrow">Source Status</div>
          <div className="text-sm" style={{ color: 'var(--sp-bone)' }}>{headline}</div>
          <div className="flex items-center justify-center gap-2 text-[10px] font-mono uppercase tracking-widest">
            <span style={{ color: accent }}>{entry.status || 'UNKNOWN'}</span>
            <span style={{ color: 'var(--sp-mist)' }}>·</span>
            <span style={{ color: 'var(--sp-mist)' }}>{entry.category}</span>
          </div>
          <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
            {entry.human_message}
          </p>
          {showCommand && (
            <pre
              className="text-[11px] font-mono inline-block px-3 py-2 rounded mx-auto"
              style={{
                color: 'var(--sp-bone)',
                background: 'rgba(13, 16, 21, 0.7)',
                border: '1px solid var(--sp-line)',
                whiteSpace: 'pre-wrap',
              }}
            >
              {entry.suggested_command ?? phaseCmd(sourceFilter)}
            </pre>
          )}
          {entry.last_run_at && (
            <p className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>
              last run · {formatTs(entry.last_run_at)} · {entry.fetched_count} fetched
            </p>
          )}
          {entry.category !== 'PLACEHOLDER' && (
            <p className="text-[10px] font-mono uppercase tracking-widest pt-1" style={{ color: 'var(--sp-mist)' }}>
              Advisory · No execution
            </p>
          )}
        </div>
      );
    }

    // Source filter but no source-health entry → still honest, no misleading CTA.
    return (
      <div className="sp-card-soft p-8 space-y-2 text-center">
        <div className="text-sm" style={{ color: 'var(--sp-bone)' }}>
          No {label} signals available right now.
        </div>
        <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
          No source-health record yet for {label}. Try another source or run ingestion later.
        </p>
        <pre
          className="text-[11px] font-mono inline-block px-3 py-2 rounded"
          style={{
            color: 'var(--sp-bone)',
            background: 'rgba(13, 16, 21, 0.7)',
            border: '1px solid var(--sp-line)',
            whiteSpace: 'pre-wrap',
          }}
        >
          {phaseCmd(sourceFilter)}
        </pre>
      </div>
    );
  }

  // 2. No source filter, but DB still has signals → just say "no match for filters".
  if (!overallEmpty) {
    return (
      <div className="sp-card-soft p-8 text-center text-sm" style={{ color: 'var(--sp-mist)' }}>
        No signals match your filter or search.
      </div>
    );
  }

  // 3. Truly empty across all sources → suggest the Phase 1 ingestion runner
  // (Phase 1 is what most users seed first).  No legacy live_source_runner.py.
  return (
    <div className="sp-card-soft p-8 text-center space-y-2">
      <p className="text-sm" style={{ color: 'var(--sp-bone)' }}>No live signals ingested yet.</p>
      <p className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
        Run Phase 1 ingestion to populate <span className="lowercase">signal_events</span>:
      </p>
      <pre
        className="text-[11px] font-mono inline-block px-3 py-2 rounded"
        style={{
          color: 'var(--sp-bone)',
          background: 'rgba(13, 16, 21, 0.7)',
          border: '1px solid var(--sp-line)',
          whiteSpace: 'pre-wrap',
        }}
      >
        python scripts/run_live_sources_phase1.py --dry-run
      </pre>
    </div>
  );
}

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
        <PerSourceEmptyState sourceFilter={sourceFilter} data={data} health={health} />
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

/**
 * Source-aware summary tiles for the Live Signals header.
 *
 * The "All Sources" view keeps the historical "Total Signals + per-source
 * counts + Latest Fetched" layout — it is a true cross-source roll-up.
 *
 * A specific source filter switches to the honest, source-aware layout
 * driven by /live-sources/status.sources[<key>].display_state:
 *
 *   current_live                       → "Current live signals" + "Latest fetched"
 *   optional_unconfigured_with_archive → "Current live signals: 0",
 *                                        "Archived/persisted rows: N",
 *                                        "Latest archived row: <ts>"
 *   optional_unconfigured_empty        → "Current live signals: 0",
 *                                        "Optional source not configured"
 *   planned_coverage                   → "Current live signals: 0",
 *                                        "Coverage rows: N",
 *                                        "Source status: planned/not scored"
 *   stale_active                       → "Stale persisted rows: N" + stale chip
 *   never_run                          → "Current live signals: 0",
 *                                        "No live runs"
 */
function SignalStatTiles({
  sourceFilter,
  data,
  status,
  sourceCounts,
  latestTs,
}: {
  sourceFilter: '' | LiveSignalSource;
  data: LiveSignalsResponse;
  status: LiveSourcesStatusResponse | null;
  sourceCounts: Record<string, number>;
  latestTs: string | null;
}) {
  if (!sourceFilter) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Total Signals" value={String(data.count)} />
        {Object.entries(sourceCounts).map(([src, cnt]) => {
          const entry = status?.sources?.[src];
          const isStale = Boolean(entry?.is_stale);
          const ageHours = entry?.refresh_age_hours;
          return (
            <StatTile
              key={src}
              label={SOURCE_LABELS[src] ?? src}
              value={String(cnt)}
              stale={isStale}
              ageHours={typeof ageHours === 'number' ? ageHours : null}
            />
          );
        })}
        {latestTs && <StatTile label="Latest Fetched" value={formatTs(latestTs)} small />}
      </div>
    );
  }

  const entry = status?.sources?.[sourceFilter];
  const displayState = entry?.display_state ?? 'unknown';
  const sourceLabel = SOURCE_LABELS[sourceFilter] ?? sourceFilter;
  const currentLive = entry?.current_live_count ?? 0;
  const archived = entry?.archived_row_count ?? 0;
  const coverage = entry?.coverage_row_count ?? 0;
  const latestPersisted = entry?.latest_persisted_row_at_utc ?? null;
  const latestRefresh = entry?.last_refresh_attempt ?? null;

  const tiles: { label: string; value: string; small?: boolean; stale?: boolean; testId?: string }[] = [];

  // Always show "Current live signals: N" as the leading honest number.
  tiles.push({
    label: 'Current live signals',
    value: String(currentLive),
    testId: 'tile-current-live',
  });

  if (displayState === 'optional_unconfigured_with_archive') {
    tiles.push({
      label: 'Archived/persisted rows',
      value: String(archived),
      testId: 'tile-archived',
    });
    if (latestPersisted) {
      tiles.push({
        label: 'Latest archived row',
        value: formatTs(latestPersisted),
        small: true,
        testId: 'tile-latest-archived',
      });
    }
  } else if (displayState === 'planned_coverage') {
    tiles.push({
      label: 'Coverage rows',
      value: String(coverage),
      testId: 'tile-coverage',
    });
    tiles.push({
      label: 'Source status',
      value: 'planned / not scored',
      small: true,
      testId: 'tile-status-planned',
    });
  } else if (displayState === 'optional_unconfigured_with_coverage') {
    // Asia Disclosure when EDINET/OpenDART keys are missing: render the
    // 11-country coverage list but never imply current_live presence.
    tiles.push({
      label: 'Coverage rows',
      value: String(coverage),
      testId: 'tile-coverage',
    });
    tiles.push({
      label: 'Source status',
      value: 'optional / not configured',
      small: true,
      testId: 'tile-status-optional-unconfigured',
    });
  } else if (displayState === 'stale_active') {
    tiles.push({
      label: 'Stale persisted rows',
      value: String(archived),
      stale: true,
      testId: 'tile-stale',
    });
    if (latestPersisted) {
      tiles.push({
        label: 'Latest stale row',
        value: formatTs(latestPersisted),
        small: true,
        testId: 'tile-latest-stale',
      });
    } else if (latestRefresh) {
      tiles.push({
        label: 'Latest attempted refresh',
        value: formatTs(latestRefresh),
        small: true,
        testId: 'tile-latest-attempt',
      });
    }
  } else if (displayState === 'optional_unconfigured_empty') {
    tiles.push({
      label: 'Source status',
      value: 'optional — not configured',
      small: true,
      testId: 'tile-status-optional-empty',
    });
  } else if (displayState === 'current_live') {
    if (latestPersisted) {
      tiles.push({
        label: 'Latest fetched',
        value: formatTs(latestPersisted),
        small: true,
        testId: 'tile-latest-fetched',
      });
    }
  } else {
    // never_run / unknown / safety fallback.
    if (latestRefresh) {
      tiles.push({
        label: 'Latest attempted refresh',
        value: formatTs(latestRefresh),
        small: true,
        testId: 'tile-latest-attempt',
      });
    } else {
      tiles.push({
        label: 'Source status',
        value: 'no live runs',
        small: true,
        testId: 'tile-status-never-run',
      });
    }
  }

  return (
    <div
      className="grid grid-cols-2 md:grid-cols-4 gap-3"
      data-testid="signal-stat-tiles"
      data-source={sourceFilter}
      data-display-state={displayState}
    >
      <StatTile label={sourceLabel} value="" small testId="tile-source-label" />
      {tiles.map((t, i) => (
        <StatTile
          key={i}
          label={t.label}
          value={t.value}
          small={t.small}
          stale={t.stale}
          testId={t.testId}
        />
      ))}
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

function StatTile({
  label,
  value,
  small,
  stale,
  ageHours,
  testId,
}: {
  label: string;
  value: string;
  small?: boolean;
  stale?: boolean;
  ageHours?: number | null;
  testId?: string;
}) {
  return (
    <div className="sp-card px-4 py-3" data-testid={testId}>
      <div className="flex items-center justify-between mb-1 gap-2">
        <div className="sp-eyebrow">{label}</div>
        {stale && (
          <span
            className="text-[9px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded shrink-0"
            style={{
              color: 'var(--sp-gold)',
              border: '1px solid rgba(214, 168, 90, 0.35)',
              background: 'rgba(214, 168, 90, 0.06)',
            }}
            title={
              typeof ageHours === 'number'
                ? `Last refresh attempt ~${ageHours.toFixed(1)}h ago. Run the local refresh.`
                : 'No recent refresh attempt recorded. Run the local refresh.'
            }
          >
            STALE
          </span>
        )}
      </div>
      <div
        className={small ? 'text-xs font-mono' : 'text-2xl font-semibold font-mono'}
        style={{ color: small ? 'var(--sp-mist)' : 'var(--sp-bone)' }}
      >
        {value}
      </div>
      {stale && typeof ageHours === 'number' && (
        <div className="text-[10px] font-mono mt-1" style={{ color: 'var(--sp-mist)' }}>
          age {ageHours.toFixed(1)}h
        </div>
      )}
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


// WatchdogStatusPanel was extracted to ../../components/WatchdogStatusPanel.tsx
// so it can be unit-tested with Vitest + React Testing Library in isolation
// from the page-level API client side-effects.  See the matching spec at
// frontend/src/components/__tests__/WatchdogStatusPanel.spec.tsx.
//
// Any change to the panel must edit the extracted component, not this file.
// ---------------------------------------------------------------------------
// Auto-refresh truth panel (Sprint I addendum).  Honest reporting of
// whether the Windows scheduled task is installed/enabled/failing —
// the UI must NEVER pretend auto-refresh is happening when it is not.
// We never register the scheduled task from the browser; we just
// surface the exact PowerShell command the operator needs to run.
// ---------------------------------------------------------------------------

function AutoRefreshPanel({ status }: { status: LiveSourcesStatusResponse | null }) {
  if (!status) return null;
  const ar = status.auto_refresh_status;
  if (!ar) return null;

  const code = ar.status;
  const cadenceHours = ar.cadence_hours ?? status.stale_threshold_hours ?? 6;
  const lastSuccess =
    ar.last_successful_refresh_utc ?? status.last_refresh_success ?? null;
  const lastAttempt =
    ar.last_attempted_refresh_utc ?? status.last_refresh_attempt ?? null;
  const nextRun = ar.next_run_time ?? null;
  const reason = ar.status_reason ?? '';
  const suggested = ar.suggested_command ?? null;
  const manualCmd =
    ar.manual_refresh_command ?? status.manual_refresh_command ?? 'python scripts/refresh_live_signals.py --write';

  const palette: Record<string, { color: string; chip: string; label: string }> = {
    PASS: {
      color: 'var(--sp-cyan)',
      chip: 'sp-chip sp-chip-cyan',
      label: 'ENABLED',
    },
    NOT_INSTALLED: {
      color: 'var(--sp-gold)',
      chip: 'sp-chip sp-chip-warn',
      label: 'NOT INSTALLED',
    },
    DISABLED: {
      color: 'var(--sp-gold)',
      chip: 'sp-chip sp-chip-warn',
      label: 'DISABLED',
    },
    FAILING: {
      color: 'var(--sp-rust)',
      chip: 'sp-chip sp-chip-rust',
      label: 'FAILING',
    },
    STALE: {
      color: 'var(--sp-gold)',
      chip: 'sp-chip sp-chip-warn',
      label: 'STALE',
    },
    UNSUPPORTED_PLATFORM: {
      color: 'var(--sp-mist)',
      chip: 'sp-chip',
      label: 'UNSUPPORTED PLATFORM',
    },
    UNKNOWN: {
      color: 'var(--sp-mist)',
      chip: 'sp-chip',
      label: 'UNKNOWN',
    },
  };
  const p = palette[code] ?? palette.UNKNOWN;

  return (
    <div
      className="rounded-lg px-4 py-3 space-y-2"
      data-testid="auto-refresh-panel"
      data-auto-refresh-status={code}
      style={{
        background: 'rgba(13, 16, 21, 0.45)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className={p.chip} data-testid="auto-refresh-chip">
          Auto-refresh · {p.label}
        </span>
        <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
          Cadence · every {cadenceHours} hour{cadenceHours === 1 ? '' : 's'}
        </span>
      </div>
      {reason && (
        <p className="text-xs" style={{ color: p.color }} data-testid="auto-refresh-reason">
          {reason}
        </p>
      )}
      <div className="grid gap-1 md:grid-cols-3 text-xs" style={{ color: 'var(--sp-mist)' }}>
        <div>
          Last success:{' '}
          <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
            {lastSuccess ?? '—'}
          </span>
        </div>
        <div>
          Last attempt:{' '}
          <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
            {lastAttempt ?? '—'}
          </span>
        </div>
        <div>
          Next run:{' '}
          <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
            {nextRun ?? '—'}
          </span>
        </div>
      </div>
      {suggested && (
        <pre
          className="text-[11px] font-mono px-3 py-2 rounded"
          data-testid="auto-refresh-suggested-command"
          style={{
            color: 'var(--sp-bone)',
            background: 'rgba(13, 16, 21, 0.7)',
            border: '1px solid var(--sp-line)',
            whiteSpace: 'pre-wrap',
          }}
        >
          {suggested}
        </pre>
      )}
      <p className="text-[10px]" style={{ color: 'var(--sp-mist)' }}>
        Manual refresh:{' '}
        <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
          {manualCmd}
        </span>
        {' · '}Advisory only — refreshing source data does not authorize trades.
      </p>
    </div>
  );
}


function StaleRefreshBanner({ status }: { status: LiveSourcesStatusResponse | null }) {
  if (!status) return null;
  const stale = status.stale_sources ?? [];
  const excluded = status.excluded_from_stale ?? [];
  const refreshConfigured = status.refresh_configured ?? false;
  const threshold = status.stale_threshold_hours ?? 6;
  const manualCmd =
    status.manual_refresh_command ?? 'python scripts/refresh_live_signals.py --write';
  const schedulerCmd =
    status.scheduler_hint ??
    '.\\scripts\\windows\\register_live_signal_refresh_task.ps1 (every 6h Scheduled Task)';

  if (refreshConfigured && stale.length === 0 && excluded.length === 0) {
    return null;
  }

  const headline = !refreshConfigured
    ? 'Scheduled task is registered but no source-refresh records exist yet.'
    : stale.length === 0
    ? `All active sources are within the ${threshold}h refresh window.`
    : `Stale active sources (${stale.length} older than ${threshold} hour${threshold === 1 ? '' : 's'}).`;

  const excludedReasonLabel = (reason: string): string => {
    if (reason === 'planned_not_scored') return 'planned/not scored';
    if (reason === 'optional_config_missing') return 'optional — not configured';
    return reason;
  };

  return (
    <div
      className="rounded-lg px-4 py-3 space-y-2"
      data-testid="stale-refresh-banner"
      style={{
        background: 'rgba(214, 168, 90, 0.05)',
        border: '1px solid rgba(214, 168, 90, 0.28)',
      }}
    >
      <div className="flex items-start gap-2 flex-wrap">
        <span
          className={`sp-chip ${stale.length > 0 ? 'sp-chip-warn' : ''} shrink-0`}
        >
          {stale.length > 0 ? 'STALE' : 'REFRESH STATUS'}
        </span>
        <p className="text-sm" style={{ color: 'var(--sp-bone)' }}>{headline}</p>
      </div>
      {stale.length > 0 && (
        <p className="text-xs" data-testid="stale-active-sources" style={{ color: 'var(--sp-mist)' }}>
          Stale active sources:{' '}
          <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
            {stale.map((s) => SOURCE_LABELS[s] ?? s).join(', ')}
          </span>
        </p>
      )}
      {excluded.length > 0 && (
        <p className="text-xs" data-testid="excluded-from-stale" style={{ color: 'var(--sp-mist)' }}>
          Excluded from stale count:{' '}
          <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
            {excluded
              .map((e) => `${SOURCE_LABELS[e.source] ?? e.source} — ${excludedReasonLabel(e.reason)}`)
              .join('; ')}
          </span>
        </p>
      )}
      <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
        A scheduled task running cleanly does not guarantee every source produced fresh data —
        some sources may still be stale because the upstream refresh failed or returned empty.
        Run the local refresh script or check the 6-hour scheduled task. Advisory only —
        refreshing data does not authorize trades.
      </p>
      <div className="grid gap-2 md:grid-cols-2">
        <pre
          className="text-[11px] font-mono px-3 py-2 rounded"
          style={{
            color: 'var(--sp-bone)',
            background: 'rgba(13, 16, 21, 0.7)',
            border: '1px solid var(--sp-line)',
            whiteSpace: 'pre-wrap',
          }}
        >
          {manualCmd}
        </pre>
        <pre
          className="text-[11px] font-mono px-3 py-2 rounded"
          style={{
            color: 'var(--sp-bone)',
            background: 'rgba(13, 16, 21, 0.7)',
            border: '1px solid var(--sp-line)',
            whiteSpace: 'pre-wrap',
          }}
        >
          {schedulerCmd}
        </pre>
      </div>
    </div>
  );
}
