'use client';

/**
 * SignalCard.tsx — extracted from frontend/src/app/live-signals/page.tsx
 * during the Identity Collapse sprint (Phase 10).
 *
 * Contains:
 *   * SignalEventCard            — per-row card with expand/collapse body
 *   * DisagreementDetailBlock    — Polymarket × Kalshi disagreement body
 *   * PairScoreComponentsBlock   — per-axis pair-score components
 *   * PAIR_SCORE_COMPONENT_LABELS — label table
 *
 * Behaviour preserved verbatim; helpers come from ./utils.
 */
import { useState } from 'react';
import type { LiveSignalEvent } from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import {
  SOURCE_ACCENT,
  SOURCE_LABELS,
  KALSHI_FRESHNESS_LABEL,
  KALSHI_ACTIVITY_LABEL,
  getTitle,
  getSubtitle,
  isKalshiQuarantined,
  kalshiDisplayCategory,
  formatTs,
} from './utils';

export function SignalEventCard({
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
export function DisagreementDetailBlock({ ev }: { ev: LiveSignalEvent }) {
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
export const PAIR_SCORE_COMPONENT_LABELS: Array<{
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

export function PairScoreComponentsBlock({
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

