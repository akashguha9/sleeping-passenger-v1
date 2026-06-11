'use client';

/**
 * Contradiction Card — the Belgium room: "market says X, data says Y."
 *
 * Renders the unified verdict's cross-engine contradictions and the
 * conservative-wins resolution. Disagreement is information: the card
 * exists so the operator can never act on whichever engine happens to
 * agree with them. Advisory-only; nothing here places an order.
 */

export interface UnifiedVerdict {
  final_state: string;
  state_before_unification: string;
  unified_score_10: number;
  contradiction_hold: boolean;
  engines_present: string[];
  engine_states: Record<string, string>;
  contradictions: {
    kind: string;
    severity: number;
    left: string;
    right: string;
    resolution: string;
  }[];
  strategy_credibility?: number | null;
  strategy_upgrade_blocked?: boolean;
  rationale: string[];
}

interface Props {
  verdict?: UnifiedVerdict | null;
}

export function ContradictionCard({ verdict }: Props) {
  if (!verdict) {
    return (
      <div
        data-testid="contradiction-card"
        className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm text-slate-400"
      >
        No unified verdict yet — run an evaluation with engine sections to
        see cross-engine reconciliation.
      </div>
    );
  }

  const demoted = verdict.final_state !== verdict.state_before_unification;

  return (
    <div
      data-testid="contradiction-card"
      data-execution-permission="false"
      className={`rounded-lg border p-4 text-sm ${
        verdict.contradiction_hold
          ? 'border-amber-900/50 bg-amber-950/20'
          : 'border-slate-700/40 bg-slate-900/40'
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="font-semibold text-slate-100">Unified Verdict</span>
        <span
          data-testid="unified-state"
          className={verdict.contradiction_hold ? 'text-amber-300' : 'text-slate-300'}
        >
          {demoted
            ? `${verdict.state_before_unification} → ${verdict.final_state}`
            : verdict.final_state}
          {verdict.contradiction_hold && ' · CONTRADICTION HOLD'}
        </span>
      </div>

      <div className="mt-2 text-xs text-slate-400">
        Engines:{' '}
        {Object.entries(verdict.engine_states)
          .map(([engine, state]) => `${engine}=${state}`)
          .join(' · ')}
        {typeof verdict.strategy_credibility === 'number' && (
          <span data-testid="strategy-credibility">
            {' '}· strategy credibility{' '}
            {verdict.strategy_credibility.toFixed(2)}
            {verdict.strategy_upgrade_blocked && ' (upgrade blocked)'}
          </span>
        )}
      </div>

      {verdict.contradictions.length > 0 && (
        <ul data-testid="contradiction-list" className="mt-3 space-y-2">
          {verdict.contradictions.map((c) => (
            <li
              key={c.kind + c.left}
              className="rounded border border-amber-900/40 bg-slate-950/40 p-2 text-xs"
            >
              <div className="font-mono text-amber-200">{c.kind}</div>
              <div className="mt-1 text-slate-300">
                {c.left} <span className="text-amber-300">⇄</span> {c.right}
              </div>
              <div className="mt-1 text-slate-500">{c.resolution}</div>
            </li>
          ))}
        </ul>
      )}

      <ul className="mt-2 list-disc pl-5 text-xs text-slate-400">
        {verdict.rationale.slice(0, 3).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      <p className="mt-3 text-[10px] uppercase tracking-wide text-slate-500">
        Most conservative engine wins · Disagreement is information ·
        Advisory only · No orders placed
      </p>
    </div>
  );
}

export default ContradictionCard;
