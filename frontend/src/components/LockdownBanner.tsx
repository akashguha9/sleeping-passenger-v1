'use client';

/**
 * Emergency lockdown banner (Pass 3).
 *
 * When the backend runs with MVP_LOCKDOWN_MODE=1, /health reports
 * `lockdown_mode: true` and every mutating route returns 423 Locked.
 * This banner makes that state impossible to miss in the UI.
 *
 * Renders nothing while loading, on fetch failure, or when lockdown is
 * off — it must never block normal use or invent state it cannot verify.
 */
import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';

export function LockdownBanner() {
  const [lockdown, setLockdown] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (!cancelled && body && body.lockdown_mode === true) {
          setLockdown(true);
        }
      })
      .catch(() => {
        /* backend offline — other components surface that state */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!lockdown) return null;
  return (
    <div
      className="bg-rose-950 border-b border-rose-700 px-4 py-2 text-xs font-mono text-rose-200"
      data-testid="lockdown-banner"
      role="alert"
    >
      EMERGENCY LOCKDOWN MODE — the backend is read-only
      (MVP_LOCKDOWN_MODE=1). All journal writes, imports, exports and
      reconciliation are disabled until the owner lifts lockdown. See
      docs/INCIDENT_LOCKDOWN.md.
    </div>
  );
}
