'use client';

/**
 * SourceConfigurationSnapshot — top-level "how many sources are alive?"
 * tile.  Renders configured / not-configured / fresh / stale / degraded /
 * failed counts in a single line so a first-day operator can see the
 * health of the ingestion surface at a glance.
 *
 * SAFETY CONTRACT
 * ---------------
 * Advisory-only.  Reads existing /live-sources/status fields; never
 * triggers a refresh, never calls a broker, never displays
 * execution-style language.  When the backend is unavailable, the
 * component reports the truthful unavailable state — never invents data.
 */
import type { LiveSourceStatusEntry, LiveSourcesStatusResponse } from '@/types';

/**
 * Read an optional string-valued field from a LiveSourceStatusEntry that the
 * static type does not declare.  Older backend snapshots emit a flat
 * `freshness` key instead of the canonical `freshness_state`; we tolerate
 * both without weakening LiveSourceStatusEntry with an index signature.
 *
 * Goes through `unknown` so TypeScript treats the bridge as deliberate
 * rather than an unsafe Record cast (TS2352).
 */
function readOptionalString(
  entry: LiveSourceStatusEntry,
  key: string,
): string | undefined {
  const bag = entry as unknown as Record<string, unknown>;
  const value = bag[key];
  return typeof value === 'string' ? value : undefined;
}

export interface SourceConfigurationSnapshotProps {
  status: LiveSourcesStatusResponse | null;
  isMock: boolean;
  watchdogStatus?: string | null;
  className?: string;
}

export interface SnapshotCounts {
  configured: number;
  not_configured: number;
  total: number;
  fresh: number;
  stale: number;
  overdue: number;
  degraded: number;
  failed: number;
  never_run: number;
  skipped: number;
  completeness: number; // configured / total in [0,1]
}

export function computeSnapshotCounts(
  status: LiveSourcesStatusResponse | null,
): SnapshotCounts {
  const empty: SnapshotCounts = {
    configured: 0,
    not_configured: 0,
    total: 0,
    fresh: 0,
    stale: 0,
    overdue: 0,
    degraded: 0,
    failed: 0,
    never_run: 0,
    skipped: 0,
    completeness: 0,
  };
  if (!status || !status.sources) return empty;

  const entries = Object.values(status.sources);
  const total = entries.length;
  let configured = 0;
  let not_configured = 0;
  let fresh = 0;
  let stale = 0;
  let overdue = 0;
  let degraded = 0;
  let failed = 0;
  let never_run = 0;
  let skipped = 0;

  for (const entry of entries) {
    if (entry?.credential_configured) configured += 1;
    else not_configured += 1;

    // `freshness_state` is the canonical typed field; `freshness` is a
    // legacy flat alias some older backend snapshots still emit.  Read the
    // typed field directly and fall back to the legacy alias via a typed
    // helper so we don't widen LiveSourceStatusEntry with an index
    // signature.  Default to never_run for unknown values.
    const freshness = (
      entry.freshness_state ??
      readOptionalString(entry, 'freshness') ??
      'never_run'
    ).toLowerCase();

    if (freshness === 'fresh') fresh += 1;
    else if (freshness === 'stale') stale += 1;
    else if (freshness === 'overdue') overdue += 1;
    else if (freshness === 'degraded' || freshness.startsWith('degraded')) degraded += 1;
    else if (freshness === 'failed') failed += 1;
    else if (freshness === 'never_run') never_run += 1;
    else if (freshness === 'skipped') skipped += 1;
  }

  const completeness = total > 0 ? configured / total : 0;
  return {
    configured,
    not_configured,
    total,
    fresh,
    stale,
    overdue,
    degraded,
    failed,
    never_run,
    skipped,
    completeness,
  };
}

export function SourceConfigurationSnapshot({
  status,
  isMock,
  watchdogStatus,
  className,
}: SourceConfigurationSnapshotProps) {
  // Backend unavailable / mock mode — render truthful "no live data" tile.
  if (isMock || !status) {
    return (
      <div
        data-testid="source-configuration-snapshot"
        data-snapshot-state="unavailable"
        className={className ?? ''}
      >
        <span
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-gold)' }}
        >
          Source configuration unavailable — backend offline — mock UI state active
        </span>
      </div>
    );
  }

  const counts = computeSnapshotCounts(status);
  const completenessPct = Math.round(counts.completeness * 100);
  const wd = watchdogStatus ? watchdogStatus.toUpperCase() : null;

  return (
    <div
      data-testid="source-configuration-snapshot"
      data-snapshot-state="present"
      data-configured={counts.configured}
      data-total={counts.total}
      data-not-configured={counts.not_configured}
      data-fresh={counts.fresh}
      data-stale={counts.stale}
      data-degraded={counts.degraded}
      data-failed={counts.failed}
      data-completeness-pct={completenessPct}
      className={className ?? ''}
    >
      <span
        className="text-[10px] font-mono uppercase tracking-widest"
        style={{ color: 'var(--sp-cyan)' }}
      >
        Sources
      </span>
      <span className="text-xs ml-2" style={{ color: 'var(--sp-mist)' }}>
        <span data-testid="snapshot-configured" className="font-mono" style={{ color: 'var(--sp-bone)' }}>
          {counts.configured}/{counts.total}
        </span>{' '}
        configured ({completenessPct}%) ·{' '}
        <span data-testid="snapshot-not-configured" className="font-mono">
          {counts.not_configured}
        </span>{' '}
        not configured ·{' '}
        <span data-testid="snapshot-fresh" className="font-mono" style={{ color: 'var(--sp-cyan)' }}>
          {counts.fresh}
        </span>{' '}
        fresh ·{' '}
        <span data-testid="snapshot-stale" className="font-mono" style={{ color: 'var(--sp-gold)' }}>
          {counts.stale}
        </span>{' '}
        stale ·{' '}
        <span data-testid="snapshot-degraded" className="font-mono" style={{ color: 'var(--sp-gold)' }}>
          {counts.degraded}
        </span>{' '}
        degraded ·{' '}
        <span data-testid="snapshot-failed" className="font-mono" style={{ color: '#d57b6a' }}>
          {counts.failed}
        </span>{' '}
        failed
        {wd ? (
          <>
            {' · '}
            <span data-testid="snapshot-watchdog" className="font-mono">
              watchdog {wd}
            </span>
          </>
        ) : null}
      </span>
    </div>
  );
}

export default SourceConfigurationSnapshot;
