'use client';

/**
 * WatchdogStatusPanel — read-only cockpit chip for the refresh
 * watchdog summary.
 *
 * Renders the contents of ``runtime/refresh_watchdog_summary.json`` (as
 * surfaced by ``GET /source-health/watchdog``) so the operator can see
 * at a glance whether the 30-minute self-healing watchdog ran, what it
 * found, and what improved.
 *
 * SAFETY CONTRACT
 *   - This component is ADVISORY-ONLY.  It never triggers a refresh,
 *     never calls a broker, never authorises execution.
 *   - The footer always renders the "advisory-only" string; tests pin
 *     that this and the absence of trade/order/execute verbs cannot
 *     regress.
 *   - Missing-file ("status=MISSING") and ERROR payloads render
 *     truthfully with no synthesised healthy fallback.
 */
import type { WatchdogSummaryResponse } from '@/types';

export interface WatchdogStatusPanelProps {
  summary: WatchdogSummaryResponse | null;
}

export function watchdogChipForStatus(
  status?: string,
): { chip: string; color: string; label: string } {
  switch ((status ?? 'UNKNOWN').toUpperCase()) {
    case 'HEALTHY':
      return { chip: 'sp-chip sp-chip-cyan', color: 'var(--sp-cyan)', label: 'HEALTHY' };
    case 'IMPROVED_BUT_STALE':
      return {
        chip: 'sp-chip sp-chip-warn',
        color: 'var(--sp-gold)',
        label: 'IMPROVED · STILL STALE',
      };
    case 'STALE_UNCHANGED':
      return { chip: 'sp-chip sp-chip-rust', color: '#d57b6a', label: 'STALE · UNCHANGED' };
    case 'ERROR':
      return { chip: 'sp-chip sp-chip-rust', color: '#d57b6a', label: 'ERROR' };
    case 'MISSING':
      return {
        chip: 'sp-chip sp-chip-warn',
        color: 'var(--sp-gold)',
        label: 'MISSING · NEVER RAN',
      };
    default:
      return { chip: 'sp-chip', color: 'var(--sp-mist)', label: status ?? 'UNKNOWN' };
  }
}

export function WatchdogStatusPanel({ summary }: WatchdogStatusPanelProps) {
  if (!summary) return null;
  const status = summary.status ?? 'UNKNOWN';
  const palette = watchdogChipForStatus(status);
  const inner = summary.summary ?? null;
  const ageMin = summary.age_minutes;
  const summaryStale = Boolean(summary.stale);
  const finishedAt = inner?.finished_at_utc ?? inner?.generated_at_utc ?? null;
  const staleBefore = inner?.stale_sources_before ?? [];
  const staleAfter = inner?.stale_sources_after ?? [];
  const excluded = inner?.excluded_optional_sources ?? [];
  const improved = Boolean(inner?.freshness_improved);
  const improvementReasons = inner?.improvement_reasons ?? [];
  const retries = inner?.retries_attempted ?? 0;
  const jitterEnabled = Boolean(inner?.jitter_enabled);
  const jitterPct = inner?.backoff_jitter_pct;
  const dependencyCritical = inner?.dependency_critical_sources ?? [];
  // Same-tick recompute fields (added by the watchdog hardening
  // sprint).  Optional on the wire so older summaries still render.
  const innerExt = (inner ?? {}) as WatchdogSummaryResponse['summary'] & {
    parent_recovery_detected?: boolean;
    disagreement_recompute_invoked_in_tick?: boolean;
  };
  const parentRecoveryDetected = Boolean(innerExt?.parent_recovery_detected);
  const recomputeInvoked = Boolean(innerExt?.disagreement_recompute_invoked_in_tick);

  const trackedRows: {
    key: string;
    label: string;
    before: any;
    after: any;
  }[] = [
    {
      key: 'kalshi',
      label: 'Kalshi',
      before: inner?.kalshi_status_before ?? null,
      after: inner?.kalshi_status_after ?? null,
    },
    {
      key: 'gdelt',
      label: 'GDELT',
      before: inner?.gdelt_status_before ?? null,
      after: inner?.gdelt_status_after ?? null,
    },
  ];
  const pmd = inner?.derived_source_dependency_status?.prediction_market_disagreement;
  const pmdStaleParents = pmd?.degraded_parent_stale_parents ?? [];

  return (
    <div
      className="rounded-lg px-4 py-3 space-y-2"
      data-testid="watchdog-status-panel"
      data-watchdog-status={status}
      data-watchdog-present={String(summary.present)}
      data-watchdog-summary-stale={String(summaryStale)}
      data-parent-recovery-detected={String(parentRecoveryDetected)}
      data-disagreement-recompute-invoked={String(recomputeInvoked)}
      style={{
        background: 'rgba(13, 16, 21, 0.45)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className={palette.chip} data-testid="watchdog-status-chip">
          Watchdog · {palette.label}
        </span>
        {!summary.present && (
          <span
            className="text-[10px] font-mono uppercase tracking-widest"
            style={{ color: 'var(--sp-gold)' }}
            data-testid="watchdog-missing-hint"
          >
            Run · python scripts/watchdog_refresh_stale_sources.py --ttl-hours 6
          </span>
        )}
        {summary.present && summaryStale && (
          <span className="sp-chip sp-chip-warn" data-testid="watchdog-summary-stale-chip">
            Summary stale · last write &gt;{' '}
            {summary.summary_stale_after_minutes ?? 60}m ago
          </span>
        )}
      </div>

      {summary.present ? (
        <>
          <div
            className="grid gap-1 md:grid-cols-3 text-xs"
            style={{ color: 'var(--sp-mist)' }}
          >
            <div>
              Last finished:{' '}
              <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
                {finishedAt ?? '—'}
              </span>
            </div>
            <div>
              Summary age:{' '}
              <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
                {typeof ageMin === 'number' ? `${ageMin.toFixed(1)}m` : '—'}
              </span>
            </div>
            <div>
              Retries attempted:{' '}
              <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
                {retries}
              </span>
            </div>
          </div>
          <div
            className="grid gap-1 md:grid-cols-2 text-xs"
            style={{ color: 'var(--sp-mist)' }}
          >
            <div data-testid="watchdog-stale-before">
              Stale before:{' '}
              <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
                {staleBefore.length === 0 ? 'none' : staleBefore.join(', ')}
              </span>
            </div>
            <div data-testid="watchdog-stale-after">
              Stale after:{' '}
              <span
                className="font-mono"
                style={{
                  color:
                    staleAfter.length === 0
                      ? 'var(--sp-cyan)'
                      : 'var(--sp-gold)',
                }}
              >
                {staleAfter.length === 0 ? 'none' : staleAfter.join(', ')}
              </span>
            </div>
            <div data-testid="watchdog-excluded-optional">
              Excluded optional:{' '}
              <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
                {excluded.length === 0 ? 'none' : excluded.join(', ')}
              </span>
            </div>
            <div data-testid="watchdog-dependency-critical">
              Dependency-critical:{' '}
              <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
                {dependencyCritical.length === 0
                  ? 'none'
                  : dependencyCritical.join(', ')}
              </span>
            </div>
          </div>

          {parentRecoveryDetected && (
            <p
              className="text-xs"
              style={{ color: 'var(--sp-cyan)' }}
              data-testid="watchdog-parent-recovery"
            >
              Parent recovery detected this tick.
              {recomputeInvoked
                ? ' Disagreement recompute invoked in the same tick.'
                : ' Disagreement recompute skipped (parents not fully fresh).'}
            </p>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            {trackedRows.map(({ key, label, before, after }) => {
              const fsAfter = after?.freshness_state ?? '';
              const stale = Boolean(after?.is_stale_active);
              return (
                <span
                  key={key}
                  className={`sp-chip ${stale ? 'sp-chip-warn' : ''}`}
                  data-testid={`watchdog-source-chip-${key}`}
                  data-source={key}
                  data-freshness-after={fsAfter ?? ''}
                  data-is-stale-active={String(stale)}
                  data-dependency-critical={String(Boolean(after?.dependency_critical))}
                >
                  {label} · {before?.freshness_state ?? '?'} → {fsAfter || '?'}
                  {after?.dependency_critical ? ' · dep-critical' : ''}
                </span>
              );
            })}
            <span
              className={`sp-chip ${pmd?.is_stale_active ? 'sp-chip-warn' : ''}`}
              data-testid="watchdog-source-chip-prediction_market_disagreement"
              data-freshness-after={pmd?.freshness_state ?? ''}
              data-is-stale-active={String(Boolean(pmd?.is_stale_active))}
            >
              Disagreement · {pmd?.freshness_state ?? '?'}
              {pmdStaleParents.length > 0
                ? ` · parent stale: ${pmdStaleParents.join(', ')}`
                : ''}
            </span>
            <span
              className="sp-chip"
              data-testid="watchdog-source-chip-etherscan"
            >
              Etherscan · excluded optional
            </span>
          </div>

          {improved && improvementReasons.length > 0 && (
            <p
              className="text-xs"
              style={{ color: 'var(--sp-cyan)' }}
              data-testid="watchdog-improvement-reasons"
            >
              Improvement reasons: {improvementReasons.join(' · ')}
            </p>
          )}

          <p
            className="text-[10px]"
            style={{ color: 'var(--sp-mist)' }}
            data-testid="watchdog-jitter-line"
          >
            Jitter:{' '}
            <span className="font-mono" style={{ color: 'var(--sp-bone)' }}>
              {jitterEnabled
                ? `enabled · ±${((jitterPct ?? 0) * 100).toFixed(0)}%`
                : 'disabled'}
            </span>
          </p>
        </>
      ) : (
        <p
          className="text-xs"
          style={{ color: 'var(--sp-mist)' }}
          data-testid="watchdog-never-ran"
        >
          {summary.reason ??
            'No refresh_watchdog_summary.json yet — the 30-minute watchdog task has not produced a summary.'}
        </p>
      )}

      <p
        className="text-[10px]"
        style={{ color: 'var(--sp-mist)' }}
        data-testid="watchdog-advisory-footer"
      >
        Watchdog is advisory-only. It does not trade, call brokers, or unlock execution.
      </p>
    </div>
  );
}

export default WatchdogStatusPanel;
