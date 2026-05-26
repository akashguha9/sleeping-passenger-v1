'use client';

import type { KalshiSourceHealthResponse } from '@/types';

/**
 * KalshiOperatorTruthPanel — operator-facing summary of the Kalshi
 * source-health artifact.
 *
 * Contract:
 *   - NEVER renders API Key ID, private-key path, auth headers, or
 *     signatures.  Even if the upstream payload accidentally contained
 *     such keys we ignore the values: this component renders only
 *     fields enumerated below.
 *   - Always renders the canonical safety block (advisory-only,
 *     execution-locked, broker_api_called=false, ai_execution_count=0).
 *   - When ``records_allowed === 0`` but the source is live verified,
 *     surfaces an HONEST "no allowed-scope markets found" line
 *     (callers must NOT collapse this to "source failed").
 */
export interface KalshiOperatorTruthPanelProps {
  data: KalshiSourceHealthResponse | null;
}

const FORBIDDEN_LABEL_FRAGMENTS = [
  'api_key_id',
  'private_key',
  'authorization',
  'kalshi-access-key',
  'kalshi-access-signature',
  'kalshi-access-timestamp',
];

/**
 * Defence-in-depth: scrub any forbidden auth markers from a string
 * before rendering it.  We never expect the backend to send these
 * tokens, but if a future payload accidentally embeds them in an
 * error message we redact at the boundary.
 */
function safeText(value: unknown): string {
  if (value == null) return '';
  const s = String(value);
  const lc = s.toLowerCase();
  for (const needle of FORBIDDEN_LABEL_FRAGMENTS) {
    if (lc.includes(needle)) return '<redacted>';
  }
  return s;
}

function formatFreshnessAge(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function computeFreshnessAgeSeconds(
  lastSuccessAt: string | undefined,
): number | null {
  if (!lastSuccessAt) return null;
  const t = new Date(lastSuccessAt).valueOf();
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 1000;
}

function StatRow({
  label,
  value,
  testId,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  testId?: string;
  tone?: 'normal' | 'warn' | 'good' | 'error';
}) {
  const color =
    tone === 'good'
      ? 'var(--sp-cyan)'
      : tone === 'warn'
      ? 'var(--sp-gold)'
      : tone === 'error'
      ? '#d57b6a'
      : 'var(--sp-bone)';
  return (
    <div
      className="flex items-center justify-between gap-3"
      data-testid={testId}
    >
      <span
        className="text-[10px] font-mono uppercase tracking-widest"
        style={{ color: 'var(--sp-mist)' }}
      >
        {label}
      </span>
      <span className="text-xs font-mono" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

export function KalshiOperatorTruthPanel({
  data,
}: KalshiOperatorTruthPanelProps) {
  if (!data) {
    return (
      <div
        className="sp-card-soft p-4 space-y-2"
        data-testid="kalshi-operator-truth-panel"
        data-mode="unknown"
      >
        <div
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-mist)' }}
        >
          Kalshi · Operator Truth · Read-only · Advisory only
        </div>
        <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
          Kalshi source-health artifact not available. Run{' '}
          <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
            python scripts/kalshi_live_smoke.py --dry-run --env demo
          </span>{' '}
          to generate it.
        </p>
      </div>
    );
  }

  const mode = data.mode || (data.is_mock_run ? 'mock_fixture' : 'skipped');
  const env = data.env || 'demo';
  const sourceStatus = data.source_freshness_status || 'UNVERIFIED';
  const ttl = data.freshness_ttl_seconds ?? 0;
  const ageSeconds = computeFreshnessAgeSeconds(data.last_successful_fetch_at_utc);
  const recordsSeen = data.records_seen_total ?? 0;
  const recordsAllowed = data.records_allowed ?? 0;
  const recordsQuarantined = data.records_quarantined ?? 0;
  const acceptedCats = data.category_allowed_counts || {};
  const quarantinedCats = data.category_rejected_counts || {};
  const enrichmentAttempted = data.event_enrichment_attempted ?? 0;
  const enrichmentSucceeded = data.event_enrichment_succeeded ?? 0;
  const enrichmentFailed = data.event_enrichment_failed ?? 0;
  const enrichmentRate = data.event_enrichment_failure_rate ?? 0;
  const isLiveVerifiedEmpty =
    sourceStatus === 'LIVE_VERIFIED_SOURCE_EMPTY_FOR_ALLOWED_SCOPE';
  const isHealthy =
    sourceStatus === 'LIVE_VERIFIED' || isLiveVerifiedEmpty;
  const isError =
    sourceStatus === 'SOURCE_ERROR' ||
    sourceStatus === 'SOURCE_RATE_LIMITED' ||
    sourceStatus === 'SOURCE_ERROR_TIMEOUT' ||
    sourceStatus === 'SOURCE_ERROR_PRODUCTION_ENV_MISSING';

  // Split-semantic truth (API health vs canonical signal_events).  The
  // backend now serves these via /source-health/kalshi; when absent
  // (older API or local artifact only), default to UNKNOWN so the UI
  // doesn't silently merge them back into a single chip.
  const apiHealthStatus = data.api_health_status || (isHealthy ? 'LIVE_VERIFIED' : 'UNKNOWN');
  const canonicalSignalStatus = data.canonical_signal_status || 'UNKNOWN';
  const semanticFresh = Boolean(data.semantic_fresh);
  const isDegraded = Boolean(data.degraded);
  const canonicalLiveCount = data.canonical_live_count ?? 0;
  const apiHealthTone: 'good' | 'warn' | 'error' =
    apiHealthStatus === 'LIVE_VERIFIED'
      ? 'good'
      : apiHealthStatus === 'AUTH_FAILED' || apiHealthStatus === 'API_ERROR'
      ? 'error'
      : 'warn';
  const canonicalTone: 'good' | 'warn' | 'error' =
    canonicalSignalStatus === 'LIVE_CANONICAL' ||
    canonicalSignalStatus === 'DUPLICATE_REFRESHED'
      ? 'good'
      : canonicalSignalStatus === 'STALE_CANONICAL' ||
        canonicalSignalStatus === 'MISSING_CANONICAL'
      ? 'error'
      : 'warn';
  const splitMessage =
    data.operator_message ||
    (apiHealthStatus === 'LIVE_VERIFIED' &&
    canonicalSignalStatus === 'ZERO_FRESH_ROWS'
      ? 'Kalshi API is live, but no fresh canonical signal_events rows were produced. This usually means accepted markets were deduped, filtered, or not wired into canonical persistence.'
      : apiHealthStatus === 'LIVE_VERIFIED' &&
        canonicalSignalStatus === 'FILTERED'
      ? 'Kalshi API is live, but returned markets were filtered/quarantined by allowlist.'
      : '');

  // Defence in depth: explicitly read safety stamps as booleans, never
  // forward unknown keys to the DOM.
  const advisoryOnly = data.advisory_only === true;
  const humanReviewRequired = data.human_review_required === true;
  const executionLocked = data.execution_locked === true;
  const brokerApiCalled = data.broker_api_called === true;
  const aiExecutionCount = data.ai_execution_count ?? 0;

  return (
    <div
      className="sp-card-soft p-4 space-y-3"
      data-testid="kalshi-operator-truth-panel"
      data-mode={mode}
      data-env={env}
      data-source-status={sourceStatus}
      data-auth-used={String(Boolean(data.auth_used))}
      data-read-only="true"
      data-execution-locked={String(executionLocked)}
      data-broker-api-called={String(brokerApiCalled)}
      data-ai-execution-count={String(aiExecutionCount)}
      data-records-allowed={String(recordsAllowed)}
      data-records-quarantined={String(recordsQuarantined)}
      data-records-seen={String(recordsSeen)}
      data-seek-allowed={String(Boolean(data.seek_allowed))}
      data-allowed-found={String(Boolean(data.allowed_found))}
    >
      <div className="flex items-center justify-between gap-3">
        <div
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-mist)' }}
        >
          Kalshi · Operator Truth · Read-only · Advisory only
        </div>
        <div className="flex items-center gap-2">
          <span
            className="sp-chip"
            data-testid="kalshi-operator-mode-chip"
          >
            Mode · {mode.replace(/_/g, ' ')}
          </span>
          <span
            className="sp-chip"
            data-testid="kalshi-operator-env-chip"
          >
            Env · {env}
          </span>
          <span
            className={
              isHealthy
                ? 'sp-chip'
                : isError
                ? 'sp-chip sp-chip-rust'
                : 'sp-chip sp-chip-warn'
            }
            data-testid="kalshi-operator-source-status-chip"
          >
            Source · {sourceStatus}
          </span>
        </div>
      </div>

      <div
        className="grid gap-2 md:grid-cols-2 text-xs"
        data-testid="kalshi-operator-truth-split"
        data-api-health-status={apiHealthStatus}
        data-canonical-signal-status={canonicalSignalStatus}
        data-semantic-fresh={String(semanticFresh)}
        data-degraded={String(isDegraded)}
      >
        <StatRow
          label="Kalshi API health"
          value={apiHealthStatus}
          tone={apiHealthTone}
          testId="kalshi-operator-api-health-status"
        />
        <StatRow
          label="Kalshi canonical live signals"
          value={`${canonicalSignalStatus} (${canonicalLiveCount} fresh)`}
          tone={canonicalTone}
          testId="kalshi-operator-canonical-signal-status"
        />
      </div>

      {splitMessage && (
        <p
          className="text-xs"
          style={{ color: isDegraded ? 'var(--sp-gold)' : 'var(--sp-mist)' }}
          data-testid="kalshi-operator-truth-message"
        >
          {splitMessage}
        </p>
      )}

      <div className="grid gap-2 md:grid-cols-2 text-xs">
        <StatRow
          label="Last successful fetch"
          value={safeText(data.last_successful_fetch_at_utc) || '—'}
          testId="kalshi-operator-last-fetch"
        />
        <StatRow
          label="Freshness age / TTL"
          value={`${formatFreshnessAge(ageSeconds)} / ${formatFreshnessAge(ttl)}`}
          testId="kalshi-operator-freshness-age"
        />
        <StatRow
          label="Records seen"
          value={String(recordsSeen)}
          testId="kalshi-operator-records-seen"
        />
        <StatRow
          label="Records allowed"
          value={String(recordsAllowed)}
          tone={recordsAllowed > 0 ? 'good' : 'warn'}
          testId="kalshi-operator-records-allowed"
        />
        <StatRow
          label="Records quarantined"
          value={String(recordsQuarantined)}
          tone={recordsQuarantined > 0 ? 'warn' : 'normal'}
          testId="kalshi-operator-records-quarantined"
        />
        <StatRow
          label="Pages scanned"
          value={String(data.pages_scanned ?? 0)}
          testId="kalshi-operator-pages-scanned"
        />
        <StatRow
          label="Seek allowed"
          value={data.seek_allowed ? 'yes' : 'no'}
          testId="kalshi-operator-seek-allowed"
        />
        <StatRow
          label="Allowed found"
          value={data.allowed_found ? 'yes' : 'no'}
          tone={data.allowed_found ? 'good' : 'warn'}
          testId="kalshi-operator-allowed-found"
        />
        <StatRow
          label="Event enrichment"
          value={`${enrichmentSucceeded}/${enrichmentAttempted} (fail rate ${(
            enrichmentRate * 100
          ).toFixed(1)}%)`}
          testId="kalshi-operator-event-enrichment"
        />
        <StatRow
          label="Event enrichment failed"
          value={String(enrichmentFailed)}
          tone={enrichmentFailed > 0 ? 'warn' : 'normal'}
          testId="kalshi-operator-event-enrichment-failed"
        />
      </div>

      <div className="grid gap-2 md:grid-cols-2 text-xs">
        <div data-testid="kalshi-operator-accepted-categories">
          <div
            className="text-[10px] font-mono uppercase tracking-widest mb-1"
            style={{ color: 'var(--sp-mist)' }}
          >
            Accepted categories
          </div>
          {Object.keys(acceptedCats).length === 0 ? (
            <span className="text-xs" style={{ color: 'var(--sp-mist)' }}>
              —
            </span>
          ) : (
            <ul className="space-y-0.5">
              {Object.entries(acceptedCats).map(([slug, count]) => (
                <li
                  key={slug}
                  className="text-xs font-mono"
                  data-testid={`kalshi-operator-accepted-category-${slug}`}
                >
                  <span style={{ color: 'var(--sp-bone)' }}>{slug}</span>
                  <span style={{ color: 'var(--sp-cyan)' }}> · {count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div data-testid="kalshi-operator-quarantined-categories">
          <div
            className="text-[10px] font-mono uppercase tracking-widest mb-1"
            style={{ color: 'var(--sp-mist)' }}
          >
            Quarantined categories
          </div>
          {Object.keys(quarantinedCats).length === 0 ? (
            <span className="text-xs" style={{ color: 'var(--sp-mist)' }}>
              —
            </span>
          ) : (
            <ul className="space-y-0.5">
              {Object.entries(quarantinedCats).map(([slug, count]) => (
                <li
                  key={slug || '<missing>'}
                  className="text-xs font-mono"
                  data-testid={`kalshi-operator-quarantined-category-${
                    slug || 'missing'
                  }`}
                >
                  <span style={{ color: 'var(--sp-bone)' }}>
                    {safeText(slug) || '<missing>'}
                  </span>
                  <span style={{ color: 'var(--sp-gold)' }}> · {count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {isLiveVerifiedEmpty && (
        <p
          className="text-xs"
          style={{ color: 'var(--sp-gold)' }}
          data-testid="kalshi-operator-empty-scope-message"
        >
          Live source verified; no allowed-scope markets found in scanned
          page window. This is honest empty — not a source failure.
        </p>
      )}

      <div
        className="flex flex-wrap items-center gap-2 pt-1"
        data-testid="kalshi-operator-safety-block"
      >
        <span
          className="sp-chip"
          data-testid="kalshi-operator-advisory-chip"
          data-advisory-only={String(advisoryOnly)}
        >
          Advisory only · {advisoryOnly ? 'true' : 'false'}
        </span>
        <span
          className="sp-chip sp-chip-warn"
          data-testid="kalshi-operator-human-review-chip"
          data-human-review-required={String(humanReviewRequired)}
        >
          Human review · {humanReviewRequired ? 'required' : 'not required'}
        </span>
        <span
          className="sp-chip sp-chip-rust"
          data-testid="kalshi-operator-execution-locked-chip"
          data-execution-locked={String(executionLocked)}
        >
          Execution · {executionLocked ? 'locked' : 'unlocked'}
        </span>
        <span
          className="text-[10px] font-mono"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="kalshi-operator-broker-state"
        >
          Broker API called · {brokerApiCalled ? 'true' : 'false'}
        </span>
        <span
          className="text-[10px] font-mono"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="kalshi-operator-ai-execution-count"
        >
          AI executions · {aiExecutionCount}
        </span>
        <span
          className="text-[10px] font-mono"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="kalshi-operator-auth-used"
        >
          Auth used · {data.auth_used ? 'yes' : 'no'}
        </span>
      </div>
    </div>
  );
}

export default KalshiOperatorTruthPanel;
