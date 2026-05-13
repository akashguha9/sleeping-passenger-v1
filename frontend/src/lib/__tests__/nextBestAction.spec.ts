/**
 * Vitest-ready specs for `nextBestAction.ts`.
 *
 * These are NOT run today -- `frontend/package.json` does not ship Vitest
 * (see docs/E2E_TEST_PLAN.md for the install plan). The file is committed
 * so that the next operator who wires Vitest can run `npm test` and
 * immediately have meaningful coverage.
 *
 * To run, after the E2E_TEST_PLAN install commands:
 *
 *   cd frontend
 *   npx vitest run src/lib/__tests__/nextBestAction.spec.ts
 *
 * The harness must inject `vi`, `describe`, `it`, `expect` globals; the
 * imports below are intentionally untyped to avoid a hard dependency on
 * @types/vitest before it is installed.
 */
import { deriveNextBestAction } from '@/lib/nextBestAction';
import type { HealthResponse } from '@/lib/apiClient';

// @ts-ignore - vitest globals exist at test time, not at lint time today.
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const HEALTHY: HealthResponse = {
  status: 'ok',
  advisory_status: 'ADVISORY_ONLY',
  execution_mode: 'HUMAN_ONLY',
  ai_execution_count: 0,
  human_review_required: true,
  version: '1.0.0',
  db_available: true,
};

describe('deriveNextBestAction', () => {
  it('directs the operator to start the backend when mock fallback is active', () => {
    const r = deriveNextBestAction({
      isMock: true,
      health: null,
      signalCount: 0,
      openHumanWorkCount: 0,
    });
    expect(r.action).toBe('START_BACKEND');
    expect(r.cta).toMatch(/api_server/);
    expect(r.severity).toBeGreaterThanOrEqual(2);
  });

  it('flags db unavailability with high severity', () => {
    const r = deriveNextBestAction({
      isMock: false,
      health: { ...HEALTHY, db_available: false },
      signalCount: 5,
      openHumanWorkCount: 0,
    });
    expect(r.action).toBe('START_BACKEND');
    expect(r.severity).toBe(3);
    expect(r.headline.toLowerCase()).toContain('db');
  });

  it('asks the operator to close open decisions before chasing new ones', () => {
    const r = deriveNextBestAction({
      isMock: false,
      health: HEALTHY,
      signalCount: 10,
      openHumanWorkCount: 3,
    });
    expect(r.action).toBe('RECONCILE_OPEN_TRADES');
    expect(r.headline).toMatch(/3 open decisions/);
  });

  it('asks the operator to run ingestion when inbox is empty', () => {
    const r = deriveNextBestAction({
      isMock: false,
      health: HEALTHY,
      signalCount: 0,
      openHumanWorkCount: 0,
    });
    expect(r.action).toBe('RUN_INGESTION');
  });

  it('lands on review-inbox when system is healthy and the inbox has work', () => {
    const r = deriveNextBestAction({
      isMock: false,
      health: HEALTHY,
      signalCount: 7,
      openHumanWorkCount: 0,
    });
    expect(r.action).toBe('REVIEW_INBOX');
    expect(r.severity).toBe(0);
    expect(r.headline).toMatch(/Review 7 signals/);
  });

  it('never produces advisory-weakening copy', () => {
    const states: Array<Parameters<typeof deriveNextBestAction>[0]> = [
      { isMock: true, health: null, signalCount: 0, openHumanWorkCount: 0 },
      { isMock: false, health: HEALTHY, signalCount: 0, openHumanWorkCount: 0 },
      { isMock: false, health: HEALTHY, signalCount: 5, openHumanWorkCount: 2 },
      { isMock: false, health: HEALTHY, signalCount: 8, openHumanWorkCount: 0 },
    ];
    for (const s of states) {
      const r = deriveNextBestAction(s);
      const blob = `${r.headline} ${r.detail} ${r.cta ?? ''}`.toLowerCase();
      // The advisory contract is non-negotiable: nothing the dashboard
      // suggests may imply automated execution.
      expect(blob).not.toMatch(/place order/);
      expect(blob).not.toMatch(/execute trade/);
      expect(blob).not.toMatch(/broker (api|order)/);
      expect(blob).not.toMatch(/auto[- ]trade/);
    }
  });
});
