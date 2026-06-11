'use client';

import { useState } from 'react';
import { postSimulatorEvaluate } from '@/lib/apiClient';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import ConsentPanel, { type ConsentLedger } from '@/components/ConsentPanel';
import ContradictionCard, {
  type UnifiedVerdict,
} from '@/components/ContradictionCard';
import SimulatorVerdictCard, {
  type SimulatorDecision,
} from '@/components/SimulatorVerdictCard';

/**
 * Market-physics simulator workbench (advisory-only).
 *
 * Select a fixture candidate (or paste a payload), run it through
 * POST /simulator/evaluate, and inspect the full verdict: ladder state,
 * failed gates, crash wall, driver license, scrutineering inspection, and
 * calibration mode. Nothing on this page can place, size, or route an
 * order — the backend has no execution path.
 */

interface SimulatorResult {
  decision?: SimulatorDecision & {
    reason_codes?: string[];
    suspicion_score?: number;
    humility_index?: number;
  };
  breakdown?: {
    crash?: {
      worst_crash_combination?: string[];
      crash_density?: number;
      safe_to_enter_conditions?: string[];
    };
    driver?: { license_level?: string; status?: string; danger_points?: number };
    scrutineering?: {
      passed?: boolean;
      suspicion_score?: number;
      violations?: { check: string; explanation: string }[];
    };
  };
  consent_ledger?: ConsentLedger;
  unified_verdict?: UnifiedVerdict;
  advisory_status?: string;
}

// Deterministic demo fixtures — research inputs, not recommendations.
const FIXTURES: Record<string, Record<string, unknown>> = {
  'Strong mid-cap (graph-resolved exposure)': {
    ticker: 'GRIDCO',
    theme: 'ai_grid_buildout',
    opportunity_quality: 0.85,
    hard_evidence_score: 0.8,
    confirmation_level: 0.6,
    circuit: { market_cap_usd: 5_000_000_000 },
    narrative: {
      mention_count: 30,
      origin_count: 10,
      independent_origin_count: 9,
      source_quality: 0.8,
      narrative_velocity: 0.4,
      narrative_acceleration: 0.2,
    },
    signals: [
      { signal_type: 'backlog', raw_strength: 80, signal_age_hours: 100, source_quality: 0.9 },
      { signal_type: 'earnings_beat', raw_strength: 70, signal_age_hours: 48 },
    ],
    risk_factors: { high_valuation: 0.3, rising_rates: 0.35 },
    meal_box: {
      thesis: 'Grid equipment backlog inflecting on AI demand',
      evidence: 'Backlog up 40% YoY in latest filings',
      catalyst: 'Policy vote and Q3 earnings within 30 days',
      invalidation: 'Exit if backlog growth drops below 10% or bill fails',
    },
    driver: { license_level: 'pro_am', thesis_logging_quality: 0.9, invalidation_compliance: 0.9 },
  },
  'Too good to be true (fails scrutineering)': {
    ticker: 'SMOOTHCO',
    theme: 'ai_grid_buildout',
    opportunity_quality: 0.9,
    hard_evidence_score: 0.9,
    confirmation_level: 0.95,
    circuit: { market_cap_usd: 100_000_000 },
    narrative: { mention_count: 2, origin_count: 1, independent_origin_count: 1, source_quality: 0.9, narrative_velocity: 0.9, narrative_acceleration: 0.5 },
    theme_assessment: { policy_fit: 0.9, macro_fit: 0.9, sector_momentum: 0.9, liquidity_support: 0.9, valuation_heat: 0.1, crowding: 0.1, regulatory_friction: 0.1 },
    exposure: { revenue_exposure: 0.9, margin_sensitivity: 0.9, backlog_linkage: 0.9, customer_linkage: 0.9, geographic_fit: 0.9, policy_fit: 0.9, supply_chain_position: 0.9 },
    aero: { evidence: { filing_evidence: 0.9, cash_flow_quality: 0.9, backlog_evidence: 0.9, insider_alignment: 0.9, primary_source_confirmation: 0.9 } },
    risk_factors: {},
    meal_box: { thesis: 'Everything is perfect on every axis', catalyst: 'Any day now, certainly soon' },
    driver: { license_level: 'learner' },
  },
  'Stale hype (worn soft tyres)': {
    ticker: 'VIRALCO',
    theme: 'meme_momentum',
    opportunity_quality: 0.7,
    hard_evidence_score: 0.2,
    confirmation_level: 0.3,
    circuit: { market_cap_usd: 800_000_000 },
    narrative: { mention_count: 60, origin_count: 3, independent_origin_count: 2, source_quality: 0.3, narrative_velocity: 0.7, narrative_acceleration: 0.4 },
    signals: [{ signal_type: 'viral_article', raw_strength: 95, signal_age_hours: 300 }],
    risk_factors: { social_hype: 0.8, low_volume: 0.6, stale_signal: 0.7 },
    meal_box: { thesis: 'Viral attention will keep pushing the price up' },
    driver: { license_level: 'rookie' },
  },
};

export default function SimulatorPage() {
  const [fixtureName, setFixtureName] = useState<string>(Object.keys(FIXTURES)[0]);
  const [result, setResult] = useState<SimulatorResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runEvaluation() {
    setRunning(true);
    setError(null);
    try {
      const response = (await postSimulatorEvaluate(
        FIXTURES[fixtureName],
      )) as SimulatorResult;
      setResult(response);
    } catch (err) {
      setError(
        'Backend unavailable — start the local API server to run evaluations. ' +
          'No mock verdict is shown: a simulated verdict must never look real.',
      );
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  const scrutineering = result?.breakdown?.scrutineering;
  const crash = result?.breakdown?.crash;
  const driver = result?.breakdown?.driver;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-100">
          Market-Physics Simulator
        </h1>
        <AdvisoryOnlyBadge />
      </div>

      <p className="text-sm text-slate-400">
        Run a research candidate through tyre decay, crash permutations,
        scrutineering, and the gate ladder. Output is a journal verdict for
        human review — this system has no order path and cannot trade.
      </p>

      <div
        data-testid="simulator-fixture-controls"
        className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-700/40 bg-slate-900/40 p-4"
      >
        <label className="text-sm text-slate-300" htmlFor="fixture-select">
          Candidate fixture
        </label>
        <select
          id="fixture-select"
          data-testid="simulator-fixture-select"
          className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-slate-200"
          value={fixtureName}
          onChange={(event) => setFixtureName(event.target.value)}
        >
          {Object.keys(FIXTURES).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="simulator-run-button"
          onClick={runEvaluation}
          disabled={running}
          className="rounded bg-sky-800 px-3 py-1 text-sm text-slate-100 hover:bg-sky-700 disabled:opacity-50"
        >
          {running ? 'Evaluating…' : 'Run evaluation (advisory)'}
        </button>
      </div>

      {error && (
        <div
          data-testid="simulator-error"
          className="rounded border border-amber-900/50 bg-amber-950/30 p-3 text-sm text-amber-300"
        >
          {error}
        </div>
      )}

      <SimulatorVerdictCard decision={result?.decision ?? null} />

      {result && <ConsentPanel ledger={result.consent_ledger ?? null} />}

      {result?.unified_verdict && (
        <ContradictionCard verdict={result.unified_verdict} />
      )}

      {scrutineering && (
        <div
          data-testid="simulator-scrutineering-panel"
          className={`rounded-lg border p-4 text-sm ${
            scrutineering.passed
              ? 'border-slate-700/40 bg-slate-900/40 text-slate-300'
              : 'border-red-900/50 bg-red-950/30 text-red-200'
          }`}
        >
          <div className="font-semibold">
            Scrutineering bay:{' '}
            {scrutineering.passed
              ? 'passed technical inspection'
              : 'FAILED — verdict provisional, capped at watchlist'}
            {typeof scrutineering.suspicion_score === 'number' &&
              ` (suspicion ${scrutineering.suspicion_score.toFixed(2)})`}
          </div>
          <ul className="mt-2 list-disc pl-5 text-xs">
            {(scrutineering.violations ?? []).map((violation) => (
              <li key={violation.check}>
                <span className="font-mono">{violation.check}</span>:{' '}
                {violation.explanation}
              </li>
            ))}
          </ul>
        </div>
      )}

      {crash && (
        <div
          data-testid="simulator-crash-panel"
          className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm text-slate-300"
        >
          <div className="font-semibold">Crash wall</div>
          <div className="mt-1 text-xs">
            Worst combination:{' '}
            <span className="font-mono">
              {(crash.worst_crash_combination ?? []).join(' + ') || 'none'}
            </span>
          </div>
          <ul className="mt-2 list-disc pl-5 text-xs">
            {(crash.safe_to_enter_conditions ?? []).map((condition) => (
              <li key={condition}>{condition}</li>
            ))}
          </ul>
        </div>
      )}

      {driver && (
        <div
          data-testid="simulator-driver-panel"
          className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-4 text-sm text-slate-300"
        >
          <div className="font-semibold">Driver license</div>
          <div className="mt-1 text-xs">
            Level: <span className="font-mono">{driver.license_level}</span> ·
            Status: <span className="font-mono">{driver.status}</span> ·
            Danger points:{' '}
            <span className="font-mono">
              {typeof driver.danger_points === 'number'
                ? driver.danger_points.toFixed(1)
                : '—'}
            </span>
          </div>
        </div>
      )}

      <div
        data-testid="simulator-calibration-warning"
        className="rounded-lg border border-amber-900/40 bg-amber-950/20 p-3 text-xs text-amber-200/80"
      >
        Calibration warning: simulator weights, half-lives, and crash betas
        are doctrine-derived defaults, not yet empirically fitted. Treat
        every verdict as an uncalibrated research lens. Recommendations from
        the calibration report are never auto-applied.
      </div>

      <p className="text-[10px] uppercase tracking-wide text-slate-500">
        Advisory only · Execution gate locked · No orders placed · No broker
        connection exists · Human decision required
      </p>
    </div>
  );
}
