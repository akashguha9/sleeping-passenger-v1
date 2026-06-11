'use client';

/**
 * Advisory-only consent & regulatory-fragility panel.
 *
 * Renders the consent ledger attached to a simulator evaluation: layer
 * scores, evidence reliability, multipliers/caps applied, the dark-pattern
 * chain, and the before/after recommendation effect. Detects risk
 * patterns, never legal guilt — and reading it never authorizes a trade.
 */

export interface ConsentLedger {
  evidence_reliability_score: number;
  reliability_band: string;
  layer_scores: Record<string, number>;
  multipliers_applied: Record<string, number>;
  penalties_applied?: Record<string, number>;
  risk_caps_applied: string[];
  simulator_factors_added: Record<string, number>;
  jurisdiction_domains?: Record<string, number>;
  dark_pattern_chain?: {
    score?: number;
    label?: string;
    longest_consecutive_run?: number;
    stages_present?: number;
  };
  detected_terms: string[];
  recommendation_before_consent: string;
  recommendation_after_consent: string;
  score_before_consent: number;
  score_after_consent: number;
  warnings: string[];
  rationale: string[];
  advisory_only_notice: string;
}

interface Props {
  ledger?: ConsentLedger | null;
  revenueQualityLabel?: string;
}

const LAYER_LABELS: Record<string, string> = {
  consent_quality: 'Consent Quality',
  subscription_extraction: 'Subscription Extraction Risk',
  claims_non_payment: 'Claims Non-Payment Risk',
  friction_tax: 'Friction Tax',
  regulatory_fragility: 'Regulatory Fragility',
  narrative_experience_gap: 'Narrative-Experience Gap',
  premium_promise_failure: 'Premium Promise Failure',
  delay_revenue: 'Delay Revenue Risk',
};

export function ConsentPanel({ ledger, revenueQualityLabel }: Props) {
  if (!ledger) {
    return (
      <div
        data-testid="consent-panel"
        className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm text-slate-400"
      >
        No consumer evidence evaluated for this candidate. Consent layer is
        neutral (insufficient data) — absence of evidence is not evidence of
        cleanliness.
      </div>
    );
  }

  const downgraded =
    ledger.recommendation_after_consent !== ledger.recommendation_before_consent ||
    ledger.score_after_consent < ledger.score_before_consent - 0.05;
  const chain = ledger.dark_pattern_chain;

  return (
    <div
      data-testid="consent-panel"
      data-execution-permission="false"
      className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm"
    >
      <div className="flex items-center justify-between">
        <span className="font-semibold text-slate-100">
          Consent &amp; Regulatory Evidence
        </span>
        <span
          data-testid="consent-effect"
          className={downgraded ? 'text-amber-300' : 'text-slate-300'}
        >
          {downgraded
            ? `Effect: ${ledger.recommendation_before_consent} (${ledger.score_before_consent.toFixed(1)}) → ${ledger.recommendation_after_consent} (${ledger.score_after_consent.toFixed(1)})`
            : 'Effect: no material change'}
        </span>
      </div>

      <div className="mt-2 text-xs text-slate-300">
        Evidence reliability:{' '}
        <span className="font-mono" data-testid="consent-reliability">
          {ledger.evidence_reliability_score.toFixed(1)}/10 ({ledger.reliability_band})
        </span>
        {revenueQualityLabel && (
          <span className="ml-3">
            Revenue quality: <span className="font-mono">{revenueQualityLabel}</span>
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-slate-300 sm:grid-cols-4">
        {Object.entries(ledger.layer_scores)
          .filter(([key]) => LAYER_LABELS[key])
          .map(([key, value]) => (
            <div key={key}>
              {LAYER_LABELS[key]}:{' '}
              <span className="font-mono">{value.toFixed(1)}</span>
            </div>
          ))}
      </div>

      {chain && (chain.stages_present ?? 0) > 0 && (
        <div data-testid="consent-chain" className="mt-2 text-xs text-amber-200">
          Dark-pattern chain: {chain.label} — {chain.stages_present} stage(s),
          longest run {chain.longest_consecutive_run}, score{' '}
          {(chain.score ?? 0).toFixed(1)}
        </div>
      )}

      {ledger.risk_caps_applied.length > 0 && (
        <div data-testid="consent-caps" className="mt-2 text-xs text-red-300">
          Caps applied: {ledger.risk_caps_applied.join('; ')}
        </div>
      )}

      {ledger.detected_terms.length > 0 && (
        <div className="mt-2 text-xs text-slate-400">
          Evidence terms:{' '}
          <span className="font-mono">
            {ledger.detected_terms.slice(0, 8).join(', ')}
          </span>
        </div>
      )}

      <ul className="mt-2 list-disc pl-5 text-xs text-slate-400">
        {ledger.rationale.slice(0, 4).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      {ledger.warnings.length > 0 && (
        <div data-testid="consent-warnings" className="mt-2 text-xs text-amber-300/80">
          {ledger.warnings.slice(0, 3).map((warning) => (
            <div key={warning}>⚠ {warning}</div>
          ))}
        </div>
      )}

      <p className="mt-3 text-[10px] uppercase tracking-wide text-slate-500">
        Advisory only · Risk patterns, not legal guilt · No intent inferred ·
        No orders placed
      </p>
    </div>
  );
}

export default ConsentPanel;
