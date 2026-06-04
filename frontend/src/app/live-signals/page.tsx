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
  { value: 'kalshi', label: 'Kalshi' },
  { value: 'prediction_market_disagreement', label: 'Disagreements' },
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
  kalshi: 'rgba(142, 196, 168, 0.9)',
  prediction_market_disagreement: 'rgba(214, 168, 90, 0.9)',
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
  kalshi: 'Kalshi',
  prediction_market_disagreement: 'Prediction Market Disagreement',
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
  if (ev.source_name === 'prediction_market_disagreement') {
    // The persisted disagreement payload uses ``customer_label`` as its
    // operator-facing headline; ``title`` may be absent.
    return (p.customer_label as string) || 'Prediction Market Disagreement Alert';
  }
  if (ev.source_name === 'kalshi') {
    // Prefer the deterministic display_title written by the Kalshi
    // normalizer — it has already rejected raw "yes X, yes Y" outcome
    // dumps and applied the priority chain (event_title → market_title
    // → title → question → subtitle → ticker label).
    return (
      (p.display_title as string) ||
      (p.primary_title as string) ||
      (p.title as string) ||
      ev.event_id
    );
  }
  return p.title || p.question as string || ev.event_id;
}

function isKalshiQuarantined(ev: LiveSignalEvent): boolean {
  if (ev.source_name !== 'kalshi') return false;
  const p = ev.raw_payload;
  if (p.visible_in_kalshi_feed === false) return true;
  if (p.category_allowed === false) return true;
  return false;
}

const KALSHI_DISPLAY_LABEL_BY_SLUG: Record<string, string> = {
  elections: 'Elections',
  politics: 'Politics',
  crypto: 'Crypto',
  commodities: 'Commodities',
  economics: 'Economics',
  finance: 'Finance',
  tech_science: 'Tech & Science',
};

function kalshiDisplayCategory(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  if (typeof p.display_category === 'string' && p.display_category.trim()) {
    return p.display_category;
  }
  if (typeof p.mvp_category === 'string' && KALSHI_DISPLAY_LABEL_BY_SLUG[p.mvp_category]) {
    return KALSHI_DISPLAY_LABEL_BY_SLUG[p.mvp_category];
  }
  return String(p.category || '');
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
  if (ev.source_name === 'prediction_market_disagreement') {
    const parts: string[] = [];
    if (p.pair_type) parts.push(String(p.pair_type));
    if (p.probability_gap != null) {
      parts.push(`Gap: ${(Number(p.probability_gap) * 100).toFixed(1)} percentage points`);
    }
    if (p.status) parts.push(`Status: ${String(p.status)}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'kalshi') {
    const parts: string[] = [];
    const cat = kalshiDisplayCategory(ev);
    if (cat) parts.push(cat.toUpperCase());
    if (p.source_market_id) parts.push(`Market ${p.source_market_id}`);
    if (p.implied_probability != null) {
      parts.push(`Implied: ${(Number(p.implied_probability) * 100).toFixed(1)}%`);
    } else if (p.yes_price != null) {
      parts.push(`YES: ${Number(p.yes_price).toFixed(2)}`);
    }
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.open_interest != null) parts.push(`OI: ${Number(p.open_interest).toLocaleString()}`);
    if (p.close_time_utc) parts.push(`Closes: ${p.close_time_utc}`);
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
    // kalshi-specific fields
    p.category,
    p.source_label,
    p.source_market_id,
    p.market_url,
    p.semantic_text,
    ...((p.asset_tags as string[] | undefined) ?? []),
    ...((p.event_tags as string[] | undefined) ?? []),
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

const KALSHI_FRESHNESS_LABEL: Record<string, string> = {
  LIVE_VERIFIED: 'Source · LIVE_VERIFIED',
  SOURCE_STALE: 'Source · SOURCE_STALE',
  UNVERIFIED: 'Source · UNVERIFIED',
  SOURCE_ERROR: 'Source · SOURCE_ERROR',
};

const KALSHI_ACTIVITY_LABEL: Record<string, string> = {
  MARKET_OPEN: 'Market · OPEN',
  MARKET_CLOSED: 'Market · CLOSED',
  MARKET_EXPIRED: 'Market · EXPIRED',
  MARKET_UNKNOWN: 'Market · UNKNOWN',
};

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
  // Kalshi rows carry per-record freshness + activity status; suppress
  // the generic STALE_ACTIVE chip for Kalshi in favour of the two
  // explicit badges so the operator never conflates source staleness
  // with market activity.
  const isStaleRow =
    displayState === 'stale_active' && ev.source_name !== 'kalshi';
  const isKalshi = ev.source_name === 'kalshi';
  const kFreshness =
    isKalshi && typeof ev.raw_payload.source_freshness_status === 'string'
      ? ev.raw_payload.source_freshness_status
      : '';
  const kActivity =
    isKalshi && typeof ev.raw_payload.market_activity_status === 'string'
      ? ev.raw_payload.market_activity_status
      : '';
  const kBadge =
    isKalshi && typeof ev.raw_payload.ui_badge_status === 'string'
      ? ev.raw_payload.ui_badge_status
      : '';

  return (
    <div
      className="sp-card p-4 space-y-2.5"
      data-testid="signal-event-card"
      data-display-state={displayState ?? 'unknown'}
      data-row-classification={
        isArchived ? 'archived' : isStaleRow ? 'stale' : 'current_live'
      }
      data-kalshi-source-freshness={kFreshness || undefined}
      data-kalshi-market-activity={kActivity || undefined}
      data-kalshi-ui-badge={kBadge || undefined}
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
          {isKalshi && kFreshness && (
            <span
              className="text-[10px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded"
              data-testid="kalshi-source-freshness-badge"
              style={{
                color:
                  kFreshness === 'LIVE_VERIFIED'
                    ? 'var(--sp-cyan)'
                    : kFreshness === 'SOURCE_ERROR'
                    ? '#d57b6a'
                    : 'var(--sp-gold)',
                border: '1px solid rgba(214, 168, 90, 0.35)',
                background: 'rgba(13, 16, 21, 0.6)',
              }}
              title="How fresh the source's last successful fetch is — independent of whether the market itself is open."
            >
              {KALSHI_FRESHNESS_LABEL[kFreshness] || `Source · ${kFreshness}`}
            </span>
          )}
          {isKalshi && kActivity && (
            <span
              className="text-[10px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded"
              data-testid="kalshi-market-activity-badge"
              style={{
                color:
                  kActivity === 'MARKET_OPEN'
                    ? 'var(--sp-cyan)'
                    : kActivity === 'MARKET_EXPIRED'
                    ? '#d57b6a'
                    : 'var(--sp-gold)',
                border: '1px solid rgba(125, 211, 252, 0.28)',
                background: 'rgba(13, 16, 21, 0.6)',
              }}
              title="Whether the Kalshi market itself is still open — independent of source freshness."
            >
              {KALSHI_ACTIVITY_LABEL[kActivity] || `Market · ${kActivity}`}
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

      {ev.source_name === 'prediction_market_disagreement' && (
        <DisagreementDetailBlock ev={ev} />
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
 * Per-card body for Disagreement alerts — Polymarket vs Kalshi probabilities,
 * gap, pair type, status pill, and review-required wording.  The forbidden
 * customer-facing trading verbs (see live-signals.disagreement.spec.tsx and
 * tests/test_frontend_no_execution_language.py) MUST NOT appear in this
 * block, in any subtree, ever.
 */
function DisagreementDetailBlock({ ev }: { ev: LiveSignalEvent }) {
  const p = ev.raw_payload;
  const polyProb =
    p.polymarket_probability != null
      ? `${(Number(p.polymarket_probability) * 100).toFixed(1)}%`
      : '—';
  const kalshiProb =
    p.kalshi_probability != null
      ? `${(Number(p.kalshi_probability) * 100).toFixed(1)}%`
      : '—';
  const gap =
    p.probability_gap != null
      ? `${(Number(p.probability_gap) * 100).toFixed(1)} percentage points`
      : '—';
  const pairType = String(p.pair_type ?? 'UNKNOWN_PAIR_TYPE');
  const status = String(p.status ?? 'UNKNOWN');
  const reasons = (p.resolution_mismatch_reasons as string[] | undefined) ?? [];
  const polyProbSource = (p.probability_source_polymarket as string | undefined) ?? '';
  const kalshiProbSource = (p.probability_source_kalshi as string | undefined) ?? '';
  const components =
    (p.pair_score_components as Record<string, number> | undefined) ?? undefined;
  const embeddingProvider = (p.embedding_provider as string | undefined) ?? '';
  const embeddingModel = (p.embedding_model as string | undefined) ?? '';
  const embeddingAvailable = p.embedding_available as boolean | undefined;
  const embeddingStatusReason =
    (p.embedding_status_reason as string | undefined) ?? '';

  const statusChipClass =
    status === 'ALERT'
      ? 'sp-chip sp-chip-rust'
      : status === 'DIAGNOSTIC' || pairType === 'SAME_EVENT_DIFFERENT_THRESHOLD'
      ? 'sp-chip sp-chip-warn'
      : 'sp-chip';
  const statusLabel =
    status === 'ALERT'
      ? 'Alert'
      : status === 'DIAGNOSTIC' || status === 'PROBABILITY_MISSING'
      ? `Watch · ${status.toLowerCase()}`
      : status === 'WATCH'
      ? 'Watch only'
      : status;

  return (
    <div
      className="rounded p-3 space-y-2 text-xs"
      data-testid="disagreement-detail-block"
      style={{
        background: 'rgba(13, 16, 21, 0.45)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="grid gap-2 md:grid-cols-2">
        <div data-testid="disagreement-poly-row">
          <div className="sp-eyebrow">Polymarket</div>
          <p style={{ color: 'var(--sp-bone)' }}>{String(p.polymarket_title ?? '—')}</p>
          <p className="font-mono" style={{ color: 'var(--sp-mist)' }}>
            Implied probability: {polyProb}
          </p>
          {polyProbSource && (
            <p
              className="text-[10px] font-mono"
              style={{ color: 'var(--sp-mist)' }}
              data-testid="disagreement-poly-prob-source"
            >
              Polymarket probability source · {polyProbSource}
            </p>
          )}
        </div>
        <div data-testid="disagreement-kalshi-row">
          <div className="sp-eyebrow">Kalshi</div>
          <p style={{ color: 'var(--sp-bone)' }}>{String(p.kalshi_title ?? '—')}</p>
          <p className="font-mono" style={{ color: 'var(--sp-mist)' }}>
            Implied probability: {kalshiProb}
          </p>
          {kalshiProbSource && (
            <p
              className="text-[10px] font-mono"
              style={{ color: 'var(--sp-mist)' }}
              data-testid="disagreement-kalshi-prob-source"
            >
              Kalshi probability source · {kalshiProbSource}
            </p>
          )}
        </div>
      </div>
      <PairScoreComponentsBlock
        components={components}
        embeddingProvider={embeddingProvider}
        embeddingModel={embeddingModel}
        embeddingAvailable={embeddingAvailable}
        embeddingStatusReason={embeddingStatusReason}
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className={statusChipClass} data-testid="disagreement-status-chip">
          {statusLabel}
        </span>
        <span
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="disagreement-pair-type"
        >
          Pair type · {pairType}
        </span>
        <span
          className="text-[10px] font-mono"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="disagreement-gap"
        >
          Cross-venue probability gap · {gap}
        </span>
      </div>
      {reasons.length > 0 && (
        <p
          className="text-[10px]"
          style={{ color: 'var(--sp-gold)' }}
          data-testid="disagreement-mismatch-reasons"
        >
          Blocked by resolution mismatch — resolution terms may differ across venues:
          <span className="ml-1 font-mono" style={{ color: 'var(--sp-bone)' }}>
            {reasons.join('; ')}
          </span>
        </p>
      )}
      <p
        className="text-[10px]"
        style={{ color: 'var(--sp-mist)' }}
        data-testid="disagreement-advisory-line"
      >
        Disagreement alert · Advisory only · Human review required · No
        broker action authorised. Resolution terms may differ across
        venues.
      </p>
    </div>
  );
}


/**
 * Renders the per-axis pair-score components emitted by the disagreement
 * scanner.  Pure presentational — driven entirely off the persisted
 * payload so the operator can see why a pair did or did not promote to
 * a clean alert.  Falls back gracefully when the scanner ran with an
 * older payload that lacks these fields.
 */
const PAIR_SCORE_COMPONENT_LABELS: Array<{
  key: string;
  label: string;
}> = [
  { key: 'text_score', label: 'Text' },
  { key: 'entity_score', label: 'Entity' },
  { key: 'category_score', label: 'Category' },
  { key: 'date_score', label: 'Date/window' },
  { key: 'threshold_score', label: 'Threshold' },
  { key: 'resolution_score', label: 'Resolution' },
  { key: 'embedding_score', label: 'Embedding' },
  { key: 'final_score', label: 'Final score' },
];

function PairScoreComponentsBlock({
  components,
  embeddingProvider,
  embeddingModel,
  embeddingAvailable,
  embeddingStatusReason,
}: {
  components?: Record<string, number>;
  embeddingProvider?: string;
  embeddingModel?: string;
  embeddingAvailable?: boolean;
  embeddingStatusReason?: string;
}) {
  const hasComponents =
    components && Object.keys(components).length > 0;
  const hasEmbeddingMetadata = Boolean(
    embeddingProvider || embeddingModel || embeddingAvailable !== undefined,
  );
  if (!hasComponents && !hasEmbeddingMetadata) {
    return (
      <div
        className="rounded p-2 text-[11px]"
        data-testid="pair-score-components-fallback"
        style={{
          background: 'rgba(13, 16, 21, 0.4)',
          border: '1px dashed var(--sp-line)',
          color: 'var(--sp-mist)',
        }}
      >
        Pair score components unavailable for this alert.
      </div>
    );
  }
  return (
    <div
      className="rounded p-2 space-y-1.5 text-[11px]"
      data-testid="pair-score-components"
      style={{
        background: 'rgba(13, 16, 21, 0.4)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="sp-eyebrow">Pair score components</div>
      {hasComponents ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-3 gap-y-1 font-mono">
          {PAIR_SCORE_COMPONENT_LABELS.map(({ key, label }) => {
            const value = components ? components[key] : undefined;
            if (value === undefined || value === null) return null;
            const isFinal = key === 'final_score';
            return (
              <div
                key={key}
                data-testid={`pair-score-${key}`}
                className="flex items-center justify-between gap-1"
                style={{
                  color: isFinal ? 'var(--sp-bone)' : 'var(--sp-mist)',
                }}
              >
                <span className="uppercase tracking-widest text-[9px]">
                  {label}
                </span>
                <span
                  className={isFinal ? 'font-semibold' : ''}
                  style={{ color: isFinal ? 'var(--sp-cyan)' : 'var(--sp-bone)' }}
                >
                  {Number(value).toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <p
          className="font-mono"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="pair-score-components-missing"
        >
          Pair score components unavailable
        </p>
      )}
      {hasEmbeddingMetadata && (
        <div
          className="flex flex-wrap gap-x-3 gap-y-1 font-mono"
          data-testid="pair-score-embedding-meta"
        >
          {embeddingProvider && (
            <span
              data-testid="pair-score-embedding-provider"
              style={{ color: 'var(--sp-mist)' }}
            >
              Embedding provider · <span style={{ color: 'var(--sp-bone)' }}>{embeddingProvider}</span>
            </span>
          )}
          {embeddingModel && (
            <span
              data-testid="pair-score-embedding-model"
              style={{ color: 'var(--sp-mist)' }}
            >
              Model · <span style={{ color: 'var(--sp-bone)' }}>{embeddingModel}</span>
            </span>
          )}
          {embeddingAvailable !== undefined && (
            <span
              data-testid="pair-score-embedding-available"
              style={{
                color:
                  embeddingAvailable === false ? 'var(--sp-gold)' : 'var(--sp-mist)',
              }}
            >
              Availability ·{' '}
              <span style={{ color: 'var(--sp-bone)' }}>
                {embeddingAvailable ? 'true' : 'false'}
              </span>
            </span>
          )}
        </div>
      )}
      {embeddingAvailable === false && (
        <p
          className="text-[10px]"
          style={{ color: 'var(--sp-gold)' }}
          data-testid="pair-score-embedding-fallback"
        >
          Embedding unavailable — deterministic/local scoring used
          {embeddingStatusReason ? ` (${embeddingStatusReason})` : ''}.
        </p>
      )}
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
    return data.live_signal_events
      // Strict canonical source guard. When a specific source tab is selected,
      // render ONLY rows whose canonical `source_name` matches the selected
      // source. This keeps the Kalshi tab Kalshi-only (excluding Polymarket and
      // prediction_market_disagreement rows that merely mention "Kalshi" in
      // their text), and prevents a stale All-Sources response — still in state
      // while a source-scoped refetch is in flight — from leaking foreign rows
      // into a source tab. All Sources (sourceFilter === '') shows everything.
      .filter((ev) => sourceFilter === '' || ev.source_name === sourceFilter)
      .filter((ev) => !isKalshiQuarantined(ev))
      .filter((ev) => matchesSearch(ev, searchQuery));
  }, [data, searchQuery, sourceFilter]);

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
