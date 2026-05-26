'use client';

/**
 * LiveSignalsHeader — SignalStatTiles + StatTile extracted from
 * app/live-signals/page.tsx during the Full Role-Uplift Sprint, Phase 7.
 *
 * SAFETY CONTRACT
 * ---------------
 * Advisory-only.  Read-only.  The per-source tile copy intentionally uses
 * "current live signals", "stale persisted rows", "planned / not scored",
 * "optional / not configured", etc., and NEVER uses any execution-style
 * verb.  Stale tiles are tagged with an explicit STALE chip rather than
 * being silently downgraded.
 */
import type {
  LiveSignalSource,
  LiveSignalsResponse,
  LiveSourcesStatusResponse,
} from '@/types';
import { SOURCE_LABELS, formatTs } from '@/components/live-signals/utils';

export interface StatTileProps {
  label: string;
  value: string;
  small?: boolean;
  stale?: boolean;
  ageHours?: number | null;
  testId?: string;
}

export function StatTile({
  label,
  value,
  small,
  stale,
  ageHours,
  testId,
}: StatTileProps) {
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

export interface SignalStatTilesProps {
  sourceFilter: '' | LiveSignalSource;
  data: LiveSignalsResponse;
  status: LiveSourcesStatusResponse | null;
  sourceCounts: Record<string, number>;
  latestTs: string | null;
}

export function SignalStatTiles({
  sourceFilter,
  data,
  status,
  sourceCounts,
  latestTs,
}: SignalStatTilesProps) {
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

export default SignalStatTiles;
