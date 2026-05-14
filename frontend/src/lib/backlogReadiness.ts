/**
 * Backlog-readiness deriver.
 *
 * Mirrors the thresholds in `scripts/pre_real_money_preflight.py`:
 *
 *     UNRECONCILED_WARN_THRESHOLD        = 10
 *     UNRECONCILED_BLOCK_THRESHOLD       = 25
 *     UNRECONCILED_FULL_REVIEW_THRESHOLD = 50
 *
 * Pure function — no DOM, no fetch, no side effects.  Test-friendly so a
 * Vitest spec can pin the readiness state transitions exactly.
 *
 * The readiness state returned here is *advisory*.  It never authorises
 * trades; it tells the operator what the preflight would conclude.  The
 * Signal Reactor cannot override a BLOCKED state — backlog block is
 * primary.
 */
export type BacklogReadinessState =
  | 'CLEAR'
  | 'WARN'
  | 'BLOCKED'
  | 'FULL_REVIEW_REQUIRED'
  | 'UNKNOWN';

export interface BacklogReadinessInput {
  unreconciled_count: number | null | undefined;
  average_journal_completeness?: number | null;
  oldest_unreconciled_age_days?: number | null;
}

export interface BacklogReadinessResult {
  state: BacklogReadinessState;
  /** Short label suitable for a chip. */
  label: string;
  /** Long-form one-sentence operator copy. */
  detail: string;
  /** 0 (clear) … 3 (full review). */
  severity: 0 | 1 | 2 | 3;
  /** Thresholds we compared against — handy for tooltips. */
  warn_threshold: number;
  block_threshold: number;
  full_review_threshold: number;
  /**
   * Whether the pre-real-money preflight would currently BLOCK on this
   * backlog alone.  Reactor diagnostics cannot unset this.
   */
  preflight_blocked_by_backlog: boolean;
}

export const UNRECONCILED_WARN_THRESHOLD = 10;
export const UNRECONCILED_BLOCK_THRESHOLD = 25;
export const UNRECONCILED_FULL_REVIEW_THRESHOLD = 50;

export function deriveBacklogReadiness(
  input: BacklogReadinessInput,
): BacklogReadinessResult {
  const base = {
    warn_threshold: UNRECONCILED_WARN_THRESHOLD,
    block_threshold: UNRECONCILED_BLOCK_THRESHOLD,
    full_review_threshold: UNRECONCILED_FULL_REVIEW_THRESHOLD,
  };

  const n = input.unreconciled_count;
  if (n === null || n === undefined || Number.isNaN(n)) {
    return {
      ...base,
      state: 'UNKNOWN',
      label: 'BACKLOG_UNKNOWN',
      detail:
        'Reconciliation queue not available — backend may be offline. Start the API to see real backlog state.',
      severity: 1,
      preflight_blocked_by_backlog: false,
    };
  }

  if (n >= UNRECONCILED_FULL_REVIEW_THRESHOLD) {
    return {
      ...base,
      state: 'FULL_REVIEW_REQUIRED',
      label: 'FULL_REVIEW_REQUIRED',
      detail:
        `Unreconciled backlog is ${n}, at or above the full-review threshold (${UNRECONCILED_FULL_REVIEW_THRESHOLD}). Preflight is BLOCKED. A full sweep of pending trades is required before real-money readiness can advance.`,
      severity: 3,
      preflight_blocked_by_backlog: true,
    };
  }
  if (n >= UNRECONCILED_BLOCK_THRESHOLD) {
    return {
      ...base,
      state: 'BLOCKED',
      label: 'BACKLOG_BLOCKED',
      detail:
        `Unreconciled backlog is ${n}, at or above the block threshold (${UNRECONCILED_BLOCK_THRESHOLD}). Preflight is BLOCKED. Reactor diagnostics cannot override a backlog block.`,
      severity: 3,
      preflight_blocked_by_backlog: true,
    };
  }
  if (n >= UNRECONCILED_WARN_THRESHOLD) {
    return {
      ...base,
      state: 'WARN',
      label: 'BACKLOG_WARN',
      detail:
        `Unreconciled backlog is ${n}, at or above the warn threshold (${UNRECONCILED_WARN_THRESHOLD}). Preflight will warn but not block yet.`,
      severity: 2,
      preflight_blocked_by_backlog: false,
    };
  }
  return {
    ...base,
    state: 'CLEAR',
    label: 'BACKLOG_CLEAR',
    detail: `Unreconciled backlog is ${n} — below the warn threshold (${UNRECONCILED_WARN_THRESHOLD}).`,
    severity: 0,
    preflight_blocked_by_backlog: false,
  };
}
