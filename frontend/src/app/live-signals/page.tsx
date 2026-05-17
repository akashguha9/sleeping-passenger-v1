'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  getLiveSignals,
  getSourceHealthSummary,
  getLiveSourcesStatus,
} from '@/lib/apiClient';
import type {
  LiveSignalEvent,
  LiveSignalSource,
  LiveSignalsResponse,
  LiveSourcesStatusResponse,
  SourceHealthSummaryEntry,
  SourceHealthSummaryResponse,
} from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { SourceHealthWarnings } from '@/components/SourceHealthWarnings';
import { SourceHealthBadge } from '@/components/SourceHealthBadge';

const SOURCE_OPTIONS: { value: '' | LiveSignalSource; label: string }[] = [
  { value: '', label: 'All Sources' },
  { value: 'polymarket', label: 'Polymarket' },
  { value: 'gdelt', label: 'GDELT' },
  { value: 'sec_edgar', label: 'SEC EDGAR' },
  { value: 'newsapi', label: 'NewsAPI' },
  { value: 'event_registry', label: 'Event Registry' },
  { value: 'etherscan', label: 'Etherscan' },
  { value: 'grok_xai', label: 'Grok/xAI' },
  { value: 'market_data', label: 'Market Data' },
  { value: 'india', label: 'India' },
  { value: 'global_filings', label: 'Global Filings' },
  { value: 'asia_disclosure', label: 'Asia Disclosure' },
];

const SOURCE_ACCENT: Record<string, string> = {
  polymarket: 'rgba(167, 139, 250, 0.9)',
  gdelt: 'rgba(125, 211, 252, 0.9)',
  sec_edgar: 'rgba(200, 154, 74, 0.9)',
  newsapi: 'rgba(95, 189, 200, 0.9)',
  event_registry: 'rgba(110, 200, 196, 0.9)',
  etherscan: 'rgba(217, 119, 87, 0.9)',
  grok_xai: 'rgba(165, 158, 230, 0.9)',
  market_data: 'rgba(122, 175, 232, 0.9)',
  india: 'rgba(216, 168, 96, 0.9)',
  global_filings: 'rgba(214, 142, 158, 0.9)',
  asia_disclosure: 'rgba(213, 123, 106, 0.9)',
};

const SOURCE_LABELS: Record<string, string> = {
  polymarket: 'Polymarket',
  gdelt: 'GDELT',
  sec_edgar: 'SEC EDGAR',
  newsapi: 'NewsAPI',
  event_registry: 'Event Registry',
  etherscan: 'Etherscan',
  grok_xai: 'Grok/xAI',
  market_data: 'Market Data',
  india: 'India (NSE/RBI/SEBI)',
  global_filings: 'Global Filings',
  asia_disclosure: 'Asia Disclosure',
};

function getTitle(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  return p.title || p.question as string || ev.event_id;
}

function getSubtitle(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  if (ev.source_name === 'polymarket') {
    const parts: string[] = [];
    if (p.market_id) parts.push(`Market ${p.market_id}`);
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.liquidity != null) parts.push(`Liq: ${Number(p.liquidity).toLocaleString()}`);
    if (p.end_date) parts.push(`Ends: ${p.end_date}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'gdelt') {
    const parts: string[] = [];
    if (p.domain) parts.push(p.domain as string);
    if (p.sourcecountry) parts.push(p.sourcecountry as string);
    if (p.seendate) parts.push(`Seen: ${p.seendate}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'sec_edgar') {
    const parts: string[] = [];
    if (p.form_type) parts.push(p.form_type as string);
    if (p.cik) parts.push(`CIK ${p.cik}`);
    if (p.filing_date) parts.push(`Filed: ${p.filing_date}`);
    if (p.accession_number) parts.push(p.accession_number as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'newsapi') {
    const parts: string[] = [];
    if (p.publisher) parts.push(p.publisher as string);
    if (p.published_at) parts.push(`Published: ${p.published_at}`);
    if (p.url) parts.push(p.url as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'event_registry') {
    const parts: string[] = [];
    if (p.publisher) parts.push(p.publisher as string);
    if (p.date_time) parts.push(`Date: ${p.date_time}`);
    if (p.url) parts.push(p.url as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'etherscan') {
    const parts: string[] = [];
    if (p.hash) parts.push(`Hash: ${(p.hash as string).slice(0, 14)}…`);
    if (p.from_address) parts.push(`From: ${(p.from_address as string).slice(0, 10)}…`);
    if (p.to_address) parts.push(`To: ${(p.to_address as string).slice(0, 10)}…`);
    if (p.block_number) parts.push(`Block: ${p.block_number}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'grok_xai') {
    const parts: string[] = [];
    if (p.narrative_frame) parts.push(`Frame: ${p.narrative_frame as string}`);
    if (p.confidence_score != null) parts.push(`Confidence: ${Number(p.confidence_score).toFixed(2)}`);
    if (p.model_name) parts.push(`Model: ${p.model_name as string}`);
    if (p.created_at) parts.push(`At: ${p.created_at as string}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'market_data') {
    const parts: string[] = [];
    if (p.symbol) parts.push(String(p.symbol));
    if (p.latest_price != null) parts.push(`$${Number(p.latest_price).toFixed(2)}`);
    if (p.price_change_pct != null) {
      const pct = Number(p.price_change_pct);
      parts.push(`${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`);
    }
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.market_confirmation_score != null) parts.push(`Score: ${Number(p.market_confirmation_score).toFixed(2)}`);
    if (p.provider) parts.push(`(${p.provider as string})`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'india') {
    const parts: string[] = [];
    if (p.regulatory_source) parts.push(String(p.regulatory_source).toUpperCase());
    if (p.index_name) parts.push(String(p.index_name));
    if (p.last_price != null) parts.push(`₹${Number(p.last_price).toLocaleString()}`);
    if (p.percent_change != null) {
      const pct = Number(p.percent_change);
      parts.push(`${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`);
    }
    if (p.regulatory_note) parts.push(String(p.regulatory_note));
    return parts.join(' · ');
  }
  if (ev.source_name === 'global_filings') {
    const parts: string[] = [];
    if (p.jurisdiction) parts.push(String(p.jurisdiction));
    if (p.exchange_or_regulator) parts.push(String(p.exchange_or_regulator));
    if (p.disclosure_type) parts.push(String(p.disclosure_type).replace(/_/g, ' '));
    if (p.issuer_name) parts.push(String(p.issuer_name));
    if (p.ticker_or_identifier) parts.push(`[${String(p.ticker_or_identifier)}]`);
    if (p.published_at) parts.push(`Filed: ${String(p.published_at)}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'asia_disclosure') {
    const parts: string[] = [];
    if (p.jurisdiction) parts.push(String(p.jurisdiction));
    if (p.exchange_or_regulator) parts.push(String(p.exchange_or_regulator));
    if (p.disclosure_type) parts.push(String(p.disclosure_type).replace(/_/g, ' '));
    if (p.issuer_name) parts.push(String(p.issuer_name));
    if (p.ticker_or_identifier) parts.push(`[${String(p.ticker_or_identifier)}]`);
    if (p.published_at) parts.push(`Filed: ${String(p.published_at)}`);
    if (p.language) parts.push(`Lang: ${String(p.language)}`);
    return parts.join(' · ');
  }
  return ev.event_id;
}

function matchesSearch(ev: LiveSignalEvent, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const p = ev.raw_payload;
  return [
    ev.event_id,
    ev.source_name,
    p.title,
    p.market_id,
    p.domain,
    p.cik,
    p.form_type,
    p.accession_number,
    p.sourcecountry,
    p.language,
    p.publisher,
    p.description,
    p.url,
    p.body,
    p.date_time,
    p.hash,
    p.from_address,
    p.to_address,
    p.block_number,
    p.interpreted_topic,
    p.narrative_frame,
    p.summary_text,
    p.source_prompt,
    p.model_name,
    p.symbol,
    p.provider,
    p.period,
    p.interval,
    p.index_name,
    p.regulatory_source,
    p.regulatory_url,
    p.regulatory_note,
    p.issuer_name,
    p.ticker_or_identifier,
    p.jurisdiction,
    p.exchange_or_regulator,
    p.disclosure_type,
    p.summary,
  ]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(q));
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts;
  }
}

function SignalEventCard({
  ev,
  displayState,
}: {
  ev: LiveSignalEvent;
  displayState?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const accent = SOURCE_ACCENT[ev.source_name] ?? 'rgba(154, 155, 151, 0.7)';
  const sourceLabel = SOURCE_LABELS[ev.source_name] ?? ev.source_name;
  const isArchived =
    displayState === 'optional_unconfigured_with_archive' ||
    displayState === 'planned_coverage' ||
    displayState === 'optional_unconfigured_with_coverage';
  const isStaleRow = displayState === 'stale_active';

  return (
    <div
      className="sp-card p-4 space-y-2.5"
      data-testid="signal-event-card"
      data-display-state={displayState ?? 'unknown'}
      data-row-classification={
        isArchived ? 'archived' : isStaleRow ? 'stale' : 'current_live'
      }
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full uppercase tracking-widest"
            style={{
              color: accent,
              border: `1px solid ${accent.replace('0.9', '0.32')}`,
              background: accent.replace('0.9', '0.05'),
            }}
          >
            {sourceLabel}
          </span>
          <span className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>{ev.event_id}</span>
          {isArchived && (
            <span
              className="text-[10px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded"
              data-testid="archived-row-chip"
              style={{
                color: 'var(--sp-gold)',
                border: '1px solid rgba(214, 168, 90, 0.35)',
                background: 'rgba(214, 168, 90, 0.06)',
              }}
              title="Archived/persisted record — source is not configured or not scored"
            >
              ARCHIVED · NOT_CURRENT_LIVE
            </span>
          )}
          {isStaleRow && (
            <span
              className="text-[10px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded"
              data-testid="stale-row-chip"
              style={{
                color: 'var(--sp-gold)',
                border: '1px solid rgba(214, 168, 90, 0.35)',
                background: 'rgba(214, 168, 90, 0.06)',
              }}
              title="Stale active source — refresh failed or rate-limited"
            >
              STALE_ACTIVE
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="sp-chip sp-chip-rust">Execution · Locked</span>
          <span className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>{formatTs(ev.fetched_at)}</span>
        </div>
      </div>

      <p className="text-sm leading-snug" style={{ color: 'var(--sp-bone)' }}>{getTitle(ev)}</p>

      {getSubtitle(ev) && (
        <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>{getSubtitle(ev)}</p>
      )}

      <div className="flex items-center gap-2 flex-wrap pt-0.5">
        <span className="sp-chip">{ev.advisory_status}</span>
        {ev.human_review_required && (
          <span className="sp-chip sp-chip-warn">Human_Review_Required</span>
        )}
        <span className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>
          AI executions: <span style={{ color: 'var(--sp-cyan)' }}>{ev.ai_execution_count}</span>
        </span>
      </div>

      <div>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-[10px] font-mono uppercase tracking-widest transition-colors"
          style={{ color: 'var(--sp-mist)' }}
        >
          {expanded ? '▲ hide payload' : '▼ show raw payload'}
        </button>
        {expanded && (
          <pre
            className="mt-2 text-xs rounded p-3 overflow-x-auto max-h-48 leading-relaxed font-mono"
            style={{
              color: 'var(--sp-mist)',
              background: 'rgba(13, 16, 21, 0.7)',
              border: '1px solid var(--sp-line)',
            }}
          >
            {JSON.stringify(ev.raw_payload, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

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
  const [loading, setLoading] = useState(true);
  const [backendOffline, setBackendOffline] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getLiveSignals(sourceFilter || undefined, 200),
      getSourceHealthSummary(),
      getLiveSourcesStatus(),
    ]).then(([result, h, r]) => {
      if (!result) {
        setBackendOffline(true);
      } else {
        setBackendOffline(false);
        setData(result);
      }
      setHealth(h);
      setRefreshStatus(r);
      setLoading(false);
    });
  }, [sourceFilter]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.live_signal_events.filter((ev) => matchesSearch(ev, searchQuery));
  }, [data, searchQuery]);

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
            Polymarket · GDELT · SEC EDGAR · NewsAPI · Event Registry · Etherscan · Grok/xAI · Market Data · India · Global Filings · Asia Disclosure — advisory only.
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
          <div className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
            {filtered.length} of {data?.count ?? 0} signal{filtered.length !== 1 ? 's' : ''}
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
