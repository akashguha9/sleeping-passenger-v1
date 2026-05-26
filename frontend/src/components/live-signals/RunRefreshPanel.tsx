'use client';

/**
 * RunRefreshPanel — AutoRefreshPanel + StaleRefreshBanner extracted from
 * app/live-signals/page.tsx during the Full Role-Uplift Sprint, Phase 7.
 *
 * SAFETY CONTRACT
 * ---------------
 * Advisory-only.  Read-only.  Renders the operator's view of the auto-
 * refresh scheduled task (status, cadence, last attempt) and the stale-
 * source banner.  Every command shown is a *suggested* shell command;
 * nothing is auto-executed and the explicit "Advisory only — refreshing
 * source data does not authorize trades." disclaimer is preserved.
 */
import type { LiveSourcesStatusResponse } from '@/types';
import { SOURCE_LABELS } from '@/components/live-signals/utils';

export function AutoRefreshPanel({
  status,
}: {
  status: LiveSourcesStatusResponse | null;
}) {
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

export function StaleRefreshBanner({
  status,
}: {
  status: LiveSourcesStatusResponse | null;
}) {
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
