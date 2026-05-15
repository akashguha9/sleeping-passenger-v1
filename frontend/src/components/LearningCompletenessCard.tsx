'use client';

import type { LearningCompletenessResponse } from '@/types';

/**
 * Sprint 7C.1 — surfaces the learning-completeness report so the
 * operator can see *which* reconciled trades still have an open learning
 * loop (missing outcome label, missing process label, missing lesson)
 * without dropping to a CLI.
 *
 * Strictly advisory.  This component renders read-only data, never
 * exposes a "mark complete" button, and never implies any trade-execution
 * permission.  Empty states are explicit so an unconfigured local MVP
 * still feels intentional.
 */

interface Props {
  data: LearningCompletenessResponse | null;
  /** When true the card renders only the headline summary (no item list). */
  compact?: boolean;
}

const COPY_NO_DATA =
  'No manual or paper journal entries yet. Learning completeness activates once entries exist.';
const COPY_NO_RECONCILED =
  'Reconciled outcomes will appear here. Until then, learning completeness has nothing to evaluate.';
const COPY_SAFETY =
  'Learning completeness is advisory-only and does not authorize trades.';
const COPY_LOAD_FAIL =
  'Could not load learning completeness status. No execution action is available from this system.';

export function LearningCompletenessCard({ data, compact = false }: Props) {
  if (data === null) {
    return (
      <div
        className="rounded border border-slate-800 bg-slate-950/60 p-4"
        data-testid="learning-completeness-card"
        data-state="load-failed"
        data-advisory-only="true"
        data-execution-permission="false"
      >
        <header className="flex items-center justify-between">
          <h2 className="text-sm font-mono uppercase tracking-wider text-slate-300">
            Learning completeness
          </h2>
          <span className="text-[10px] uppercase font-mono text-rose-300/80">
            unavailable
          </span>
        </header>
        <p className="text-xs text-slate-400 mt-2" data-testid="lc-empty-copy">
          {COPY_LOAD_FAIL}
        </p>
        <p className="text-[10px] text-slate-500 mt-2" data-testid="lc-safety-copy">
          {COPY_SAFETY}
        </p>
      </div>
    );
  }

  const incomplete =
    data.incomplete_count ?? data.learning_incomplete_count ?? 0;
  const complete =
    data.complete_count ?? data.learning_complete_count ?? 0;
  const reconciled = data.reconciled_count ?? 0;
  const dbAvailable = data.db_available !== false;
  const paperCount = data.paper_trade_count;
  const realCount = data.real_manual_trade_count;

  const missingDist = data.missing_field_distribution ?? {};
  const topMissing = Object.entries(missingDist)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  const items = (data.items ?? []).slice(0, compact ? 0 : 5);

  // Empty-state precedence:
  //   1. DB unavailable / no journal entries yet
  //   2. No reconciled trades
  //   3. All reconciled trades are learning-complete
  const emptyState: string | null = (() => {
    if (!dbAvailable) return COPY_NO_DATA;
    if (reconciled === 0) {
      if ((paperCount ?? 0) === 0 && (realCount ?? 0) === 0) return COPY_NO_DATA;
      return COPY_NO_RECONCILED;
    }
    if (incomplete === 0 && complete > 0) {
      return 'All reconciled trades are learning-complete.';
    }
    return null;
  })();

  const bandColour =
    incomplete === 0
      ? 'text-emerald-300'
      : incomplete < 3
      ? 'text-amber-300'
      : 'text-rose-300';

  return (
    <div
      className="rounded border border-slate-800 bg-slate-950/60 p-4 space-y-3"
      data-testid="learning-completeness-card"
      data-state={emptyState ? 'empty' : 'populated'}
      data-incomplete-count={String(incomplete)}
      data-advisory-only="true"
      data-execution-permission="false"
      data-broker-api-called="false"
    >
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-mono uppercase tracking-wider text-slate-300">
          Learning completeness
        </h2>
        <div className="text-right space-y-0.5">
          <div className={`text-xs font-mono ${bandColour}`} data-testid="lc-counts">
            {incomplete} incomplete · {complete} complete · {reconciled} reconciled
          </div>
          {(paperCount !== undefined || realCount !== undefined) && (
            <div
              className="text-[10px] font-mono text-slate-500"
              data-testid="lc-mode-counts"
            >
              {paperCount ?? 0} paper · {realCount ?? 0} real-manual
            </div>
          )}
        </div>
      </header>

      {emptyState ? (
        <p className="text-xs text-slate-400" data-testid="lc-empty-copy">
          {emptyState}
        </p>
      ) : (
        <>
          {topMissing.length > 0 && (
            <div data-testid="lc-missing-fields">
              <p className="text-[11px] font-mono uppercase text-slate-500 mb-1">
                Top missing fields
              </p>
              <ul className="space-y-0.5 text-xs text-slate-300 font-mono">
                {topMissing.map(([field, count]) => (
                  <li
                    key={field}
                    className="flex justify-between"
                    data-testid={`lc-missing-${field}`}
                  >
                    <span>{field}</span>
                    <span className="text-slate-400">{count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {items.length > 0 && (
            <div data-testid="lc-incomplete-items">
              <p className="text-[11px] font-mono uppercase text-slate-500 mb-1">
                Oldest incomplete trades
              </p>
              <ul className="space-y-1 text-xs text-slate-300">
                {items.map((it) => (
                  <li
                    key={it.trade_id || `${it.event_id}-${it.executed_at}`}
                    className="border border-slate-800 rounded p-2"
                  >
                    <div className="font-mono text-slate-200">
                      {it.ticker} · {it.side} · {it.outcome_status || 'no-outcome'}
                    </div>
                    <div className="text-[11px] text-slate-400 mt-0.5">
                      {it.blocked_reason || 'Learning fields missing.'}
                    </div>
                    {it.missing_fields?.length > 0 && (
                      <div className="text-[10px] font-mono text-slate-500 mt-1">
                        missing: {it.missing_fields.join(', ')}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <p className="text-[10px] text-slate-500" data-testid="lc-safety-copy">
        {COPY_SAFETY}
      </p>
    </div>
  );
}
