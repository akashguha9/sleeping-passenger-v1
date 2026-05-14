/**
 * Vitest-ready specs for `backlogReadiness.ts`.
 *
 * Follows the convention established by `nextBestAction.spec.ts`:
 * committed today, executed once Vitest is installed per
 * `docs/recovery/FRONTEND_TEST_PLAN.md`.
 *
 * To run after the FRONTEND_TEST_PLAN install commands:
 *
 *   cd frontend
 *   npx vitest run src/lib/__tests__/backlogReadiness.spec.ts
 */
import {
  deriveBacklogReadiness,
  UNRECONCILED_WARN_THRESHOLD,
  UNRECONCILED_BLOCK_THRESHOLD,
  UNRECONCILED_FULL_REVIEW_THRESHOLD,
} from '@/lib/backlogReadiness';

// @ts-ignore - vitest globals exist at test time, not at lint time today.
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

describe('deriveBacklogReadiness', () => {
  it('returns UNKNOWN when count is null/undefined', () => {
    const r = deriveBacklogReadiness({ unreconciled_count: null });
    expect(r.state).toBe('UNKNOWN');
    expect(r.preflight_blocked_by_backlog).toBe(false);
  });

  it('returns CLEAR below the warn threshold', () => {
    const r = deriveBacklogReadiness({
      unreconciled_count: UNRECONCILED_WARN_THRESHOLD - 1,
    });
    expect(r.state).toBe('CLEAR');
    expect(r.severity).toBe(0);
    expect(r.preflight_blocked_by_backlog).toBe(false);
  });

  it('returns WARN at warn threshold and below block threshold', () => {
    const r = deriveBacklogReadiness({
      unreconciled_count: UNRECONCILED_WARN_THRESHOLD,
    });
    expect(r.state).toBe('WARN');
    expect(r.severity).toBe(2);
    expect(r.preflight_blocked_by_backlog).toBe(false);
  });

  it('returns BLOCKED at block threshold', () => {
    const r = deriveBacklogReadiness({
      unreconciled_count: UNRECONCILED_BLOCK_THRESHOLD,
    });
    expect(r.state).toBe('BLOCKED');
    expect(r.severity).toBe(3);
    expect(r.preflight_blocked_by_backlog).toBe(true);
  });

  it('returns FULL_REVIEW_REQUIRED at full-review threshold', () => {
    const r = deriveBacklogReadiness({
      unreconciled_count: UNRECONCILED_FULL_REVIEW_THRESHOLD,
    });
    expect(r.state).toBe('FULL_REVIEW_REQUIRED');
    expect(r.severity).toBe(3);
    expect(r.preflight_blocked_by_backlog).toBe(true);
  });

  it('escalates with count: warn → block → full-review', () => {
    const a = deriveBacklogReadiness({ unreconciled_count: 24 });
    const b = deriveBacklogReadiness({ unreconciled_count: 25 });
    const c = deriveBacklogReadiness({ unreconciled_count: 50 });
    expect(a.state).toBe('WARN');
    expect(b.state).toBe('BLOCKED');
    expect(c.state).toBe('FULL_REVIEW_REQUIRED');
  });

  it('never emits execution-permission language in copy', () => {
    const samples = [0, 9, 10, 24, 25, 49, 50, 200];
    for (const n of samples) {
      const r = deriveBacklogReadiness({ unreconciled_count: n });
      const blob = `${r.label} ${r.detail}`.toLowerCase();
      expect(blob).not.toMatch(/place order/);
      expect(blob).not.toMatch(/execute trade/);
      expect(blob).not.toMatch(/broker (api|order|connected)/);
      expect(blob).not.toMatch(/auto[- ]trade/);
      expect(blob).not.toMatch(/permission granted/);
      expect(blob).not.toMatch(/ai[- ]approved/);
      expect(blob).not.toMatch(/trade now/);
    }
  });

  it('BLOCKED detail explicitly states reactor cannot override', () => {
    const r = deriveBacklogReadiness({
      unreconciled_count: UNRECONCILED_BLOCK_THRESHOLD,
    });
    expect(r.detail.toLowerCase()).toMatch(/cannot override/);
  });
});
