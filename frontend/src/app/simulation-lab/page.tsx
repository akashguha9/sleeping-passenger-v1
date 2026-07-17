'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  getSimulationHealth,
  getSimulationEngines,
  getSimulationScenarios,
  getSimulationRuns,
  postSimulationRun,
} from '@/lib/apiClient';
import type {
  SimHealthResponse,
  SimEnginesResponse,
  SimScenariosResponse,
  SimRunsResponse,
  SimCouncilResult,
  SimLensResult,
} from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { NoExecutionBanner } from '@/components/NoExecutionBanner';

// A small, honest demo observation so the operator can run the council without
// wiring live data first. Everything here is a what-if input, never a position.
const DEMO_RETURNS = [0.01, -0.02, 0.015, -0.005, 0.02, -0.03, 0.01, 0.005, -0.01, 0.025, -0.04, 0.02];

const VOTE_TONE: Record<string, string> = {
  WATCH: 'text-emerald-400 border-emerald-800/60',
  OUTCOME_REVIEW: 'text-sky-400 border-sky-800/60',
  WAIT: 'text-amber-400 border-amber-800/60',
  AVOID: 'text-orange-400 border-orange-800/60',
  RISK_BLOCK: 'text-red-400 border-red-800/60',
};

const EVIDENCE_TONE: Record<string, string> = {
  MEASURED: 'text-emerald-400',
  EMPIRICALLY_CALIBRATED: 'text-emerald-300',
  BACKTEST_DERIVED: 'text-sky-400',
  MODEL_INFERRED: 'text-amber-400',
  PROXY_DERIVED: 'text-orange-400',
  SIMULATED_ONLY: 'text-slate-400',
  INSUFFICIENT_DATA: 'text-red-400',
  ENGINE_UNAVAILABLE: 'text-red-400',
};

function tone(map: Record<string, string>, key: string): string {
  return map[key] ?? 'text-slate-400 border-slate-700';
}

function pct(n: number): string {
  return `${Math.round((n ?? 0) * 100)}%`;
}

export default function SimulationLabPage() {
  const [health, setHealth] = useState<SimHealthResponse | null>(null);
  const [engines, setEngines] = useState<SimEnginesResponse | null>(null);
  const [scenarios, setScenarios] = useState<SimScenariosResponse | null>(null);
  const [runs, setRuns] = useState<SimRunsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const [ticker, setTicker] = useState('RELIANCE.NS');
  const [market, setMarket] = useState('IN');
  const [seed, setSeed] = useState(42);
  const [result, setResult] = useState<SimCouncilResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([
      getSimulationHealth(),
      getSimulationEngines(),
      getSimulationScenarios(),
      getSimulationRuns(20),
    ])
      .then(([h, e, s, r]) => {
        setHealth(h);
        setEngines(e);
        setScenarios(s);
        setRuns(r);
      })
      .catch(() => {
        // Wrappers already resolve to null on error; this only guards a
        // rejected Promise.all so the spinner always clears.
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runCouncil = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    try {
      const res = await postSimulationRun({
        ticker,
        market,
        seed,
        observation: {
          ticker,
          market,
          data_cutoff: new Date().toISOString().slice(0, 10),
          returns: DEMO_RETURNS,
          volatility: 0.022,
          spread_bps: 8,
          adv_usd: 8_000_000,
          sector: 'DEMO',
          narrative_sources: ['sec', 'news1'],
          source_count: 2,
          freshness_status: 'FRESH',
          catalysts: [{ id: 'earnings', magnitude: 0.3 }],
        },
      });
      setResult(res);
      getSimulationRuns(20).then(setRuns);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'run failed');
    } finally {
      setRunning(false);
    }
  }, [ticker, market, seed]);

  const backendOffline = !loading && health === null;

  return (
    <div className="max-w-5xl mx-auto space-y-5" data-testid="simulation-lab">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Simulation Lab</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Six-lens advisory simulation council — physics, chemistry, biology, racing, chess, poker.
          </p>
        </div>
        <AdvisoryOnlyBadge size="sm" />
      </div>

      <div data-testid="advisory-banner">
        <NoExecutionBanner />
      </div>

      <div
        className="bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-xs text-slate-400"
        data-simulated-only="true"
      >
        Everything on this page is a <span className="text-slate-200 font-medium">what-if simulation</span>.
        Outputs are <span className="font-mono text-slate-300">SIMULATED_ONLY</span> and never measured
        accuracy, never a recommendation to transact, and never fed to calibration. A human interprets
        every result; <span className="font-mono text-slate-300">execution_gate=LOCKED</span>.
      </div>

      {loading && (
        <div className="text-sm text-slate-500 py-8 text-center" data-testid="sim-loading">
          Loading simulation lab…
        </div>
      )}

      {backendOffline && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">BACKEND OFFLINE</span>
          <span className="text-slate-400">
            Start the API: <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {!loading && !backendOffline && (
        <>
          {/* Run panel ------------------------------------------------ */}
          <section className="bg-slate-900 border border-slate-700 rounded-lg p-4 space-y-3">
            <h2 className="text-sm font-semibold text-slate-200">Run a what-if council</h2>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-slate-400">
                Ticker
                <input
                  className="mt-1 block bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-100 text-sm font-mono"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value)}
                  aria-label="Ticker"
                />
              </label>
              <label className="text-xs text-slate-400">
                Market
                <select
                  className="mt-1 block bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-100 text-sm"
                  value={market}
                  onChange={(e) => setMarket(e.target.value)}
                  aria-label="Market"
                >
                  <option value="IN">India</option>
                  <option value="US">US</option>
                </select>
              </label>
              <label className="text-xs text-slate-400">
                Seed
                <input
                  type="number"
                  className="mt-1 block bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-100 text-sm font-mono w-24"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value) || 0)}
                  aria-label="Seed"
                />
              </label>
              <button
                onClick={runCouncil}
                disabled={running}
                className="bg-sky-700 hover:bg-sky-600 disabled:opacity-50 text-white text-sm rounded px-4 py-1.5"
                data-testid="run-council"
              >
                {running ? 'Simulating…' : 'Run simulation'}
              </button>
            </div>
            {runError && <p className="text-xs text-red-400">Simulation error: {runError}</p>}
            <p className="text-[11px] text-slate-500">
              Deterministic: the same ticker + seed + data cutoff always reproduces the same result.
            </p>
          </section>

          {result && <CouncilResultView result={result} />}

          {/* Engine registry ----------------------------------------- */}
          {engines && (
            <section className="bg-slate-900 border border-slate-700 rounded-lg p-4 space-y-2">
              <h2 className="text-sm font-semibold text-slate-200">
                Engine &amp; capability registry ({engines.summary.engine_count})
              </h2>
              <p className="text-[11px] text-slate-500">{engines.summary.honesty_note}</p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 text-left border-b border-slate-800">
                      <th className="py-1 pr-3">Engine</th>
                      <th className="py-1 pr-3">Domain</th>
                      <th className="py-1 pr-3">Integration</th>
                      <th className="py-1 pr-3">Transplanted into</th>
                    </tr>
                  </thead>
                  <tbody>
                    {engines.engines.map((e) => (
                      <tr key={e.engine} className="border-b border-slate-800/50">
                        <td className="py-1 pr-3 text-slate-200">{e.engine}</td>
                        <td className="py-1 pr-3 text-slate-400">{e.domain}</td>
                        <td className="py-1 pr-3 font-mono text-[11px] text-slate-300">
                          {e.integration_mode}
                        </td>
                        <td className="py-1 pr-3 text-slate-400">{e.transplanted_into || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Recent runs --------------------------------------------- */}
          {runs && runs.runs.length > 0 && (
            <section className="bg-slate-900 border border-slate-700 rounded-lg p-4 space-y-2">
              <h2 className="text-sm font-semibold text-slate-200">Recent simulations</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 text-left border-b border-slate-800">
                      <th className="py-1 pr-3">Ticker</th>
                      <th className="py-1 pr-3">Vote</th>
                      <th className="py-1 pr-3">Disagreement</th>
                      <th className="py-1 pr-3">Evidence</th>
                      <th className="py-1 pr-3">Usefulness</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.runs.map((r) => (
                      <tr key={r.run_id} className="border-b border-slate-800/50">
                        <td className="py-1 pr-3 font-mono text-slate-200">{r.ticker}</td>
                        <td className={`py-1 pr-3 font-semibold ${tone(VOTE_TONE, r.aggregate_vote)}`}>
                          {r.aggregate_vote}
                        </td>
                        <td className="py-1 pr-3 text-slate-400">{r.disagreement_class}</td>
                        <td className={`py-1 pr-3 ${tone(EVIDENCE_TONE, r.evidence_label)}`}>
                          {r.evidence_label}
                        </td>
                        <td className="py-1 pr-3 text-slate-300">{r.usefulness_score}/10</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {scenarios && (
            <section className="bg-slate-900 border border-slate-700 rounded-lg p-4">
              <h2 className="text-sm font-semibold text-slate-200 mb-1">
                Scenario library ({scenarios.count})
              </h2>
              <p className="text-[11px] text-slate-500">
                Reusable India/US market + operational stress scenarios with deterministic replay.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function CouncilResultView({ result }: { result: SimCouncilResult }) {
  return (
    <section
      className="bg-slate-900 border border-slate-700 rounded-lg p-4 space-y-4"
      data-testid="council-result"
      data-execution-permission="false"
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-slate-200">
          Council verdict — {result.ticker}
        </h2>
        <span className={`text-sm font-semibold px-2 py-0.5 border rounded ${tone(VOTE_TONE, result.aggregate_vote)}`}>
          {result.aggregate_vote}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <Stat label="Disagreement" value={result.disagreement_class} />
        <Stat label="Evidence" value={result.evidence_label} tone={tone(EVIDENCE_TONE, result.evidence_label)} />
        <Stat label="Robustness" value={pct(result.robustness)} />
        <Stat label="Fragility" value={pct(result.fragility)} />
        <Stat label="Confidence" value={pct(result.aggregate_confidence)} />
        <Stat label="Usefulness" value={`${result.usefulness_score}/10`} />
        <Stat
          label="Simulated only"
          value={result.simulation_only ? 'yes' : 'partly'}
          tone="text-slate-300"
        />
        <Stat
          label="Risk block"
          value={result.risk_block_engaged ? 'ENGAGED' : 'no'}
          tone={result.risk_block_engaged ? 'text-red-400' : 'text-slate-300'}
        />
      </div>

      {result.risk_block_engaged && (
        <div className="bg-red-950/40 border border-red-800/60 rounded px-3 py-2 text-xs text-red-300">
          <span className="font-semibold">RISK BLOCK overrides the aggregate score:</span>{' '}
          {result.risk_block_reason}
        </div>
      )}

      {/* Six lenses */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {result.lens_results.map((lr) => (
          <LensCard key={lr.lens} lr={lr} />
        ))}
      </div>

      {/* Warnings */}
      {result.tail_warnings.length > 0 && (
        <div className="text-xs">
          <p className="text-slate-500 mb-1">Tail-risk warnings (preserved through aggregation)</p>
          <ul className="space-y-1">
            {result.tail_warnings.map((w, i) => (
              <li key={i} className="text-orange-300">• {w}</li>
            ))}
          </ul>
        </div>
      )}
      {result.minority_warnings.length > 0 && (
        <div className="text-xs">
          <p className="text-slate-500 mb-1">Minority views (never buried)</p>
          <ul className="space-y-1">
            {result.minority_warnings.map((w, i) => (
              <li key={i} className="text-amber-300">• {w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Explainable aggregation */}
      <details className="text-xs">
        <summary className="text-slate-400 cursor-pointer">Why this verdict? (weights &amp; penalties)</summary>
        <ul className="mt-2 space-y-1 text-slate-400">
          {result.aggregation_explanation.map((line, i) => (
            <li key={i} className="font-mono text-[11px]">{line}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function LensCard({ lr }: { lr: SimLensResult }) {
  return (
    <div className="bg-slate-950 border border-slate-800 rounded p-2.5 text-xs space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-slate-200">{lr.lens}</span>
        <span className={`font-semibold ${tone(VOTE_TONE, lr.advisory_vote)}`}>{lr.advisory_vote}</span>
      </div>
      <p className="text-slate-400 leading-snug">{lr.state_interpretation}</p>
      <div className="flex items-center justify-between text-[11px] text-slate-500">
        <span className={tone(EVIDENCE_TONE, lr.evidence_label)}>{lr.evidence_label}</span>
        <span>conf {pct(lr.confidence)}</span>
      </div>
      {lr.tail_warning && <p className="text-orange-400 text-[11px]">⚠ {lr.tail_warning}</p>}
    </div>
  );
}

function Stat({ label, value, tone: t }: { label: string; value: string; tone?: string }) {
  return (
    <div className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-sm font-medium ${t ?? 'text-slate-200'}`}>{value}</div>
    </div>
  );
}
