/**
 * Dashboard "Next Best Action" classifier.
 *
 * Distinct from `nextHumanAction.ts` (which acts on a single inbox row).
 * This one looks at the *whole system state* and answers a single question:
 *
 *     "Based on the current backend/mock/DB/inbox state, what should the
 *      operator do RIGHT NOW?"
 *
 * Pure function. No I/O. No randomness. No advisory-contract weakening.
 * Easy to unit test once Vitest is wired (see docs/E2E_TEST_PLAN.md).
 */

import type { HealthResponse } from '@/lib/apiClient';

export type NextBestAction =
  | 'START_BACKEND'
  | 'MOCK_FALLBACK_VISIBLE'
  | 'RUN_INGESTION'
  | 'RECONCILE_OPEN_TRADES'
  | 'REVIEW_INBOX'
  | 'IDLE';

export interface NextBestActionInput {
  /** Whether the dashboard is rendering against mock data (BACKEND OFFLINE). */
  isMock: boolean;
  /** /health response, or null if the API never replied. */
  health: HealthResponse | null;
  /** Count of inbox items currently rendered. */
  signalCount: number;
  /**
   * Count of items the operator has flagged for human review, i.e. decisions
   * that are open and waiting on a manual call. Proxy for "trades currently
   * in flight that you have not closed the loop on" until the backend gives
   * us a real unreconciled-trade count.
   */
  openHumanWorkCount: number;
}

export interface NextBestActionResult {
  action: NextBestAction;
  /** Short imperative phrase rendered as the headline. */
  headline: string;
  /** One- or two-sentence rationale rendered underneath. */
  detail: string;
  /** Suggested command-line or click, if any. Plain text — never a script. */
  cta: string | null;
  /** Severity for visual emphasis. 0=info, 1=neutral, 2=warn, 3=blocked. */
  severity: 0 | 1 | 2 | 3;
}

/**
 * Decide the single next best action.  First match wins, so the order of
 * checks below encodes the priority: backend health > data freshness >
 * open work > idle.
 */
export function deriveNextBestAction(
  input: NextBestActionInput,
): NextBestActionResult {
  // 1. Backend totally offline → start it.  Top priority because nothing
  //    else is trustworthy until /health responds.
  if (input.isMock || input.health === null) {
    return {
      action: 'START_BACKEND',
      headline: 'Start the backend',
      detail:
        'The dashboard is rendering mock data because /health is not reachable. ' +
        'No new signals, no DB writes, and no exports are reliable until the API is up.',
      cta: 'python scripts/api_server.py',
      severity: 2,
    };
  }

  // 2. Backend up but DB not available → user is one wrong move from
  //    losing trade journal continuity.
  if (input.health.db_available === false) {
    return {
      action: 'START_BACKEND',
      headline: 'DB not available',
      detail:
        'The API is up but the SQLite database file is missing or unreadable. ' +
        'Restore from runtime/backups/ or re-init the schema before logging anything.',
      cta: 'python scripts/restore_db.py --backup runtime/backups/<file>',
      severity: 3,
    };
  }

  // 3. Open human work.  Items flagged for human review are decisions the
  //    operator marked as needing their personal call.  Close that loop
  //    before opening new ones; otherwise the inbox grows faster than the
  //    operator can think.
  if (input.openHumanWorkCount > 0) {
    return {
      action: 'RECONCILE_OPEN_TRADES',
      headline: `Close ${input.openHumanWorkCount} open decision${
        input.openHumanWorkCount === 1 ? '' : 's'
      }`,
      detail:
        'You have items flagged for human review. Make the call (decide, ' +
        'log, or reject) before chasing new signals.',
      cta: 'Open Signal Inbox',
      severity: 1,
    };
  }

  // 4. Backend up, no signals.  Probably ingestion has not been run today.
  if (input.signalCount === 0) {
    return {
      action: 'RUN_INGESTION',
      headline: 'Run ingestion',
      detail:
        'The inbox is empty. Source runners produce signals; without them ' +
        'the dashboard has nothing to advise on. Check source health first.',
      cta: 'python scripts/run_live_sources_phase1.py',
      severity: 1,
    };
  }

  // 5. Everything looks healthy → review inbox.
  return {
    action: 'REVIEW_INBOX',
    headline: `Review ${input.signalCount} signal${input.signalCount === 1 ? '' : 's'}`,
    detail:
      'Backend is up, DB is available, and there is fresh work in the inbox. ' +
      'Walk through the highest-priority items.',
    cta: 'Open Signal Inbox',
    severity: 0,
  };
}

/**
 * Convenience: short imperative phrase suitable for a `title=` attribute.
 */
export function nextBestActionShort(input: NextBestActionInput): string {
  return deriveNextBestAction(input).headline;
}
