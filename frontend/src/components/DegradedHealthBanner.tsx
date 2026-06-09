'use client';

/**
 * F8: visible degraded-write banner.
 *
 * The backend counts journal DB write failures (manual trade log /
 * reconcile / cancel + source-health writes) and exposes them on
 * /health/full as `db_write_failures_total` + `degraded`.  Before this
 * component, that signal was a buried JSON field no surface ever read —
 * the operator could keep journaling into a broken database without
 * noticing.  This banner polls /health/full and renders a red strip the
 * moment `degraded` is true.  It renders nothing while healthy or when
 * health is unknown (offline / token-gated) — those states are already
 * surfaced by the cockpit's own offline handling.
 */
import { useEffect, useState } from 'react';
import { checkFullHealth, type FullHealthResponse } from '@/lib/apiClient';

const POLL_INTERVAL_MS = 30_000;

export function DegradedHealthBanner() {
  const [health, setHealth] = useState<FullHealthResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const h = await checkFullHealth();
        if (!cancelled) setHealth(h);
      } catch {
        // checkFullHealth already maps failures to null; this guard only
        // protects against partial test mocks / unexpected throw paths.
        if (!cancelled) setHealth(null);
      }
    };
    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (!health?.degraded) return null;

  const failures = health.db_write_failures_total ?? 0;
  return (
    <div
      role="alert"
      data-testid="degraded-health-banner"
      className="bg-red-950/80 border border-red-600 text-red-200 rounded-lg px-4 py-3 mb-4 flex items-center gap-3"
    >
      <span className="text-red-400 font-bold text-lg" aria-hidden>
        ⚠
      </span>
      <div className="text-sm">
        <span className="font-semibold">
          Journal writes are FAILING — {failures} database write
          {failures === 1 ? '' : 's'} lost since startup.
        </span>{' '}
        Recent trades/reconciliations may not be persisted. Check
        logs/api_server.log and the SQLite file before logging anything else.
      </div>
    </div>
  );
}
