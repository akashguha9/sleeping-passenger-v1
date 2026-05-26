'use client';

/**
 * LiveSignalEmptyState — extracted from app/live-signals/page.tsx during
 * the Full Role-Uplift Sprint, Phase 7, to keep the page tightly scoped.
 *
 * SAFETY CONTRACT
 * ---------------
 * Read-only.  Advisory-only.  Renders honest empty-state copy for every
 * source surface.  Never tells the operator to "buy" / "sell" / "execute"
 * / "place an order".  When the backend is unavailable, the panel says
 * so truthfully and offers the local ingestion command as the only
 * remediation path.
 */
import type {
  LiveSignalSource,
  LiveSignalsResponse,
  SourceHealthSummaryEntry,
  SourceHealthSummaryResponse,
} from '@/types';
import { SOURCE_LABELS, formatTs } from '@/components/live-signals/utils';

export interface LiveSignalEmptyStateProps {
  sourceFilter: '' | LiveSignalSource;
  data: LiveSignalsResponse | null;
  health: SourceHealthSummaryResponse | null;
}

export function LiveSignalEmptyState({
  sourceFilter,
  data,
  health,
}: LiveSignalEmptyStateProps) {
  const overallEmpty = (data?.count ?? 0) === 0;
  const label = sourceFilter ? (SOURCE_LABELS[sourceFilter] ?? sourceFilter) : 'live';
  const entry: SourceHealthSummaryEntry | undefined = sourceFilter && health
    ? health.sources.find((s) => s.source_name === sourceFilter)
    : undefined;

  const phase1 = new Set(['polymarket', 'gdelt', 'sec_edgar']);
  const phaseCmd = (src: string) =>
    phase1.has(src)
      ? `python scripts/run_live_sources_phase1.py --source ${src} --dry-run`
      : `python scripts/run_live_sources_phase2.py --source ${src} --dry-run`;

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

  if (!overallEmpty) {
    return (
      <div className="sp-card-soft p-8 text-center text-sm" style={{ color: 'var(--sp-mist)' }}>
        No signals match your filter or search.
      </div>
    );
  }

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

export default LiveSignalEmptyState;
