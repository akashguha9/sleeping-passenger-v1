'use client';

/**
 * Advisory-only verdict card for the market-physics simulator
 * (`POST /simulator/evaluate`).
 *
 * Renders the full decision breakdown — ladder state, gates, tyre grip,
 * crash risk, aero efficiency, dirty air, meal box, driver permission —
 * because the simulator never emits a naked Buy / No-Buy. Reading this
 * card does not constitute permission to trade: execution_gate is LOCKED
 * everywhere and there is no order path in this system.
 */

export interface SimulatorDecision {
  ticker: string;
  theme: string;
  circuit: string;
  final_state: string;
  final_candidate_score: number;
  decision_reason: string;
  signal_compound: string;
  signal_grip: number;
  crash_risk: number;
  crash_density: number;
  downforce: number;
  drag: number;
  aero_efficiency: number;
  dirty_air: number;
  driver_permission: number;
  driver_status: string;
  meal_box_status?: { complete?: boolean; missing_items?: string[] };
  gate_results?: Record<string, boolean>;
}

interface Props {
  decision?: SimulatorDecision | null;
}

// Conservative palette: even the best state reads as "review", never "go".
const STATE_STYLE: Record<string, { fg: string; bg: string; label: string }> = {
  reject: { fg: 'text-slate-400', bg: 'bg-slate-900/40', label: 'REJECT' },
  archive: { fg: 'text-slate-300', bg: 'bg-slate-800/40', label: 'ARCHIVE' },
  watchlist: { fg: 'text-sky-300', bg: 'bg-sky-950/30', label: 'WATCHLIST' },
  active_watch: { fg: 'text-amber-300', bg: 'bg-amber-950/30', label: 'ACTIVE WATCH' },
  buy_candidate: { fg: 'text-emerald-300', bg: 'bg-emerald-950/30', label: 'BUY CANDIDATE (REVIEW)' },
  high_conviction_candidate: { fg: 'text-emerald-200', bg: 'bg-emerald-950/40', label: 'HIGH CONVICTION (REVIEW)' },
  pit_stop: { fg: 'text-orange-300', bg: 'bg-orange-950/40', label: 'PIT STOP' },
  black_flag: { fg: 'text-red-300', bg: 'bg-red-950/40', label: 'BLACK FLAG' },
};

function pct(value: number): string {
  return `${Math.round(value)}%`;
}

function frac(value: number): string {
  return value.toFixed(2);
}

export function SimulatorVerdictCard({ decision }: Props) {
  if (!decision) {
    return (
      <div
        data-testid="simulator-verdict-card"
        className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm text-slate-400"
      >
        No simulator verdict yet. Run an evaluation to see the full breakdown.
      </div>
    );
  }

  const style = STATE_STYLE[decision.final_state] ?? {
    fg: 'text-slate-300',
    bg: 'bg-slate-800/40',
    label: decision.final_state.toUpperCase(),
  };
  const mealBoxComplete = decision.meal_box_status?.complete === true;
  const missing = decision.meal_box_status?.missing_items ?? [];
  const failedGates = Object.entries(decision.gate_results ?? {})
    .filter(([, passed]) => !passed)
    .map(([name]) => name);

  return (
    <div
      data-testid="simulator-verdict-card"
      data-execution-permission="false"
      className={`rounded-lg border border-slate-700/40 p-4 ${style.bg}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <span className="font-mono text-lg text-slate-100">{decision.ticker}</span>
          <span className="ml-2 text-xs text-slate-400">{decision.theme}</span>
          <span className="ml-2 text-xs text-slate-500">circuit: {decision.circuit}</span>
        </div>
        <span
          data-testid="simulator-final-state"
          className={`rounded px-2 py-1 text-xs font-semibold ${style.fg}`}
        >
          {style.label}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-slate-300 sm:grid-cols-4">
        <div>Score: <span className="font-mono">{decision.final_candidate_score.toFixed(1)}/100</span></div>
        <div>Tyre: <span className="font-mono">{decision.signal_compound}</span></div>
        <div>Grip: <span className="font-mono">{pct(decision.signal_grip)}</span></div>
        <div>Crash risk: <span className="font-mono">{frac(decision.crash_risk)}</span></div>
        <div>Crash density: <span className="font-mono">{frac(decision.crash_density)}</span></div>
        <div>Downforce: <span className="font-mono">{frac(decision.downforce)}</span></div>
        <div>Drag: <span className="font-mono">{frac(decision.drag)}</span></div>
        <div>Aero eff.: <span className="font-mono">{frac(decision.aero_efficiency)}</span></div>
        <div>Dirty air: <span className="font-mono">{frac(decision.dirty_air)}</span></div>
        <div>Driver: <span className="font-mono">{decision.driver_status} ({frac(decision.driver_permission)})</span></div>
        <div data-testid="simulator-meal-box">
          Meal box:{' '}
          <span className="font-mono">
            {mealBoxComplete ? 'complete' : `missing ${missing.join(', ') || 'items'}`}
          </span>
        </div>
      </div>

      {failedGates.length > 0 && (
        <div data-testid="simulator-failed-gates" className="mt-2 text-xs text-amber-300">
          Gates holding promotion: {failedGates.join(', ')}
        </div>
      )}

      <p className="mt-3 text-xs leading-relaxed text-slate-400">{decision.decision_reason}</p>

      <p className="mt-2 text-[10px] uppercase tracking-wide text-slate-500">
        Advisory only · Execution gate locked · No orders placed · Human decision required
      </p>
    </div>
  );
}

export default SimulatorVerdictCard;
