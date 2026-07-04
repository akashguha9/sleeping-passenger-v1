'use client';

// Operational truth surface panel — Feed-the-Loop sprint (2026-07-04).
// One honest, action-grade view: overall state, evidence velocities,
// stop coverage, discovery/canary, rows persisted, latest alerts, and the
// single next operator action.  Copy rules are pinned by tests:
//   N < 50            -> "UNCALIBRATED SCORE — not a calibrated probability"
//   50 <= N < 200     -> "MEASURED BUT NOT DECISION-GRADE CALIBRATED"
//   gate passed       -> "CALIBRATION GATE PASSED" (N>=200, Brier<=0.25, ECE<=0.10)

import { useEffect, useState } from 'react';
import {
  getTruthSurface,
  type TruthSurfaceResponse,
} from '@/lib/apiClient';

const STATE_STYLE: Record<string, { color: string; bg: string }> = {
  HEALTHY: { color: '#34d399', bg: 'rgba(52,211,153,0.08)' },
  DEGRADED: { color: '#fbbf24', bg: 'rgba(251,191,36,0.08)' },
  BLOCKED: { color: '#f87171', bg: 'rgba(248,113,113,0.10)' },
  BROKEN: { color: '#f87171', bg: 'rgba(248,113,113,0.16)' },
};

export function calibrationCopy(surface: TruthSurfaceResponse): string {
  const n = surface.matured_real_outcome_count ?? 0;
  if (surface.calibration_status === 'CALIBRATED') {
    return 'CALIBRATION GATE PASSED';
  }
  if (n < 50) {
    return 'UNCALIBRATED SCORE — not a calibrated probability';
  }
  return 'MEASURED BUT NOT DECISION-GRADE CALIBRATED';
}

function Row({ label, value, warn }: {
  label: string; value: string; warn?: boolean;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5 rounded bg-slate-900/40 border border-slate-700/30">
      <span className="text-xs text-slate-400">{label}</span>
      <span
        className="text-xs font-mono font-bold"
        style={{ color: warn ? '#fbbf24' : '#e2e8f0' }}
      >
        {value}
      </span>
    </div>
  );
}

export function TruthSurfacePanel() {
  const [surface, setSurface] = useState<TruthSurfaceResponse | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await getTruthSurface();
      if (cancelled) return;
      setSurface(data);
      setOffline(data === null);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (offline) {
    return (
      <div
        data-testid="truth-surface-panel"
        className="border rounded-lg p-4"
        style={{ borderColor: '#f87171' }}
      >
        <strong style={{ color: '#f87171' }}>
          TRUTH SURFACE UNREACHABLE
        </strong>{' '}
        — API offline or token required. Treat system state as UNKNOWN, not
        healthy.
      </div>
    );
  }
  if (!surface) {
    return (
      <div data-testid="truth-surface-panel" className="p-4 text-sm">
        Loading truth surface…
      </div>
    );
  }

  const state = String(surface.overall_operational_state ?? 'UNKNOWN');
  const style = STATE_STYLE[state] ?? STATE_STYLE.BROKEN;
  const alerts = surface.latest_alerts ?? [];
  const missing = surface.missing_stop_count ?? 0;
  const unconfirmed = surface.unconfirmed_stop_count ?? 0;
  const expFrac = surface.portfolio_stop_exposure_fraction;
  const rows = surface.rows_persisted_status?.sources ?? {};
  const silentSinks = Object.entries(rows)
    .filter(([, v]) => v?.status !== 'OK')
    .map(([k]) => k);

  return (
    <div
      data-testid="truth-surface-panel"
      className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">
          Operational Truth Surface
        </h2>
        <span
          data-testid="truth-overall-state"
          className="px-2.5 py-1 rounded text-xs font-mono font-bold"
          style={{ color: style.color, background: style.bg }}
        >
          {state}
        </span>
      </div>

      <div
        data-testid="truth-calibration-copy"
        className="text-xs font-mono px-3 py-2 rounded"
        style={{
          color:
            surface.calibration_status === 'CALIBRATED' ? '#34d399' : '#fbbf24',
          background: 'rgba(251,191,36,0.06)',
        }}
      >
        {calibrationCopy(surface)} · N={surface.matured_real_outcome_count ?? 0}
        {surface.brier_real_forward != null
          ? ` · Brier ${surface.brier_real_forward}`
          : ''}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
        <Row
          label="Evidence velocity (7d)"
          value={`${surface.evidence_velocity_7d ?? 0}/day`}
          warn={(surface.evidence_velocity_7d ?? 0) === 0}
        />
        <Row
          label="Maturation velocity (7d)"
          value={`${surface.maturation_velocity_7d ?? 0}/day`}
        />
        <Row
          label="Pending horizon / due"
          value={`${surface.pending_horizon_count ?? 0} / ${surface.due_unmatured_count ?? 0}`}
          warn={(surface.due_unmatured_count ?? 0) > 0}
        />
        <Row
          label="Active holdings"
          value={String(surface.active_holding_count ?? 0)}
        />
        <Row
          label="Stops missing / unconfirmed"
          value={`${missing} / ${unconfirmed}`}
          warn={missing + unconfirmed > 0}
        />
        <Row
          label="Leveraged (no usable stop)"
          value={`${surface.leveraged_position_count ?? 0} (${surface.leveraged_without_stop_count ?? 0})`}
          warn={(surface.leveraged_without_stop_count ?? 0) > 0}
        />
        <Row
          label="Holdings freshness"
          value={
            surface.holdings_freshness_age_minutes != null
              ? `${(surface.holdings_freshness_age_minutes / 1440).toFixed(1)}d (${surface.holdings_truth_status})`
              : String(surface.holdings_truth_status ?? '—')
          }
          warn={surface.holdings_truth_status !== 'OK'}
        />
        <Row
          label="Stop exposure (basis)"
          value={
            expFrac != null ? `${(expFrac * 100).toFixed(1)}%` : 'UNKNOWN'
          }
          warn={expFrac == null}
        />
        <Row
          label="Fresh discovery"
          value={`${surface.fresh_discovery_status ?? '—'} (canary ${surface.provider_canary_status ?? '—'})`}
          warn={surface.fresh_discovery_status !== 'OK'}
        />
        <Row
          label="Rows persisted"
          value={silentSinks.length ? `SILENT: ${silentSinks.join(', ')}` : 'OK'}
          warn={silentSinks.length > 0}
        />
      </div>

      {surface.state_reasons && surface.state_reasons.length > 0 && (
        <ul
          data-testid="truth-state-reasons"
          className="text-xs space-y-1 pl-4 list-disc"
          style={{ color: '#fbbf24' }}
        >
          {surface.state_reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {alerts.length > 0 && (
        <div data-testid="truth-latest-alerts" className="space-y-1">
          <div className="text-xs uppercase tracking-widest text-slate-400">
            Latest alerts
          </div>
          {alerts.slice(0, 5).map((a, i) => (
            <div key={String(a.alert_id ?? i)} className="text-xs font-mono">
              <span
                style={{
                  color: a.severity === 'CRITICAL' ? '#f87171' : '#fbbf24',
                }}
              >
                [{String(a.severity ?? '?')}]
              </span>{' '}
              {String(a.title ?? '')}
            </div>
          ))}
        </div>
      )}

      <div
        data-testid="truth-next-action"
        className="text-xs px-3 py-2 rounded border"
        style={{ borderColor: 'rgba(200,154,74,0.4)', color: '#e2e8f0' }}
      >
        <span className="uppercase tracking-widest text-slate-400 mr-2">
          Next operator action
        </span>
        {surface.next_required_operator_action ?? '—'}
      </div>
    </div>
  );
}
