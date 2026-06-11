'use client';

/**
 * Transparent Score Panel — the Cartier-Foundation "glass structure":
 * the final research verdict shown as visible positive contributors and
 * penalties, never a naked number. Museum aesthetics here are cognition,
 * not decoration: the decomposition IS the trust mechanism.
 *
 * Advisory-only: verdict classes are research classifications, never
 * instructions; nothing on this panel can place an order.
 */

export interface StrategyDecision {
  ticker: string;
  decision_class: string;
  final_opportunity_score: number;
  band: string;
  hard_rules_triggered: string[];
  positive_contributors: Record<string, number>;
  penalties: Record<string, number>;
  decision_reason: string;
}

interface Props {
  decision?: StrategyDecision | null;
}

const CLASS_STYLE: Record<string, string> = {
  BUY: 'text-emerald-300',
  WATCHLIST: 'text-sky-300',
  REJECT: 'text-slate-400',
  AVOID: 'text-red-300',
  SHORT_RISK: 'text-red-300',
  NEEDS_MORE_EVIDENCE: 'text-amber-300',
  EVENT_DRIVEN_ONLY: 'text-amber-200',
  THRESHOLD_NOT_CROSSED: 'text-amber-300',
};

export function TransparentScorePanel({ decision }: Props) {
  if (!decision) {
    return (
      <div
        data-testid="transparent-score-panel"
        className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm text-slate-400"
      >
        No strategy verdict yet — run an evaluation to see the glass
        structure: every contributor and penalty, never a naked score.
      </div>
    );
  }

  const contributors = Object.entries(decision.positive_contributors).sort(
    ([, a], [, b]) => b - a,
  );
  const penalties = Object.entries(decision.penalties).filter(([, v]) => v > 0);

  return (
    <div
      data-testid="transparent-score-panel"
      data-execution-permission="false"
      className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm"
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-slate-100">{decision.ticker}</span>
        <span
          data-testid="strategy-class"
          className={`font-semibold ${CLASS_STYLE[decision.decision_class] ?? 'text-slate-300'}`}
        >
          {decision.decision_class} (research class) ·{' '}
          {decision.final_opportunity_score.toFixed(2)}/10
        </span>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <div className="text-xs font-semibold text-emerald-300/80">
            Positive contributors
          </div>
          <ul className="mt-1 space-y-0.5 text-xs text-slate-300">
            {contributors.map(([name, value]) => (
              <li key={name} className="flex justify-between">
                <span>{name.replace(/_/g, ' ')}</span>
                <span className="font-mono">+{(value * 10).toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-xs font-semibold text-red-300/80">Penalties</div>
          {penalties.length === 0 ? (
            <div className="mt-1 text-xs text-slate-500">none</div>
          ) : (
            <ul className="mt-1 space-y-0.5 text-xs text-slate-300">
              {penalties.map(([name, value]) => (
                <li key={name} className="flex justify-between">
                  <span>{name.replace(/_/g, ' ')}</span>
                  <span className="font-mono">−{value.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {decision.hard_rules_triggered.length > 0 && (
        <div
          data-testid="strategy-hard-rules"
          className="mt-3 rounded border border-red-900/40 bg-red-950/20 p-2 text-xs text-red-200"
        >
          Hard rules (caps override scores):{' '}
          {decision.hard_rules_triggered.join('; ')}
        </div>
      )}

      <p className="mt-3 text-xs text-slate-400">{decision.decision_reason}</p>
      <p className="mt-2 text-[10px] uppercase tracking-wide text-slate-500">
        Advisory only · Research classification, not an instruction · No
        orders placed
      </p>
    </div>
  );
}

export default TransparentScorePanel;
