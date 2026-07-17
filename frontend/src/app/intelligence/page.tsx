'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  getEurekaHealth,
  getDecisionTwins,
  postDailyShadowRun,
} from '@/lib/apiClient';
import type {
  EurekaHealthResponse,
  DecisionTwinsResponse,
  DailyShadowRunResponse,
} from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { NoExecutionBanner } from '@/components/NoExecutionBanner';

const VOTE_TONE: Record<string, string> = {
  WATCH: 'text-emerald-400',
  OUTCOME_REVIEW: 'text-sky-400',
  WAIT: 'text-amber-400',
  AVOID: 'text-orange-400',
  RISK_BLOCK: 'text-red-400',
};

// A small, honest demo candidate set so the operator can run the loop without
// wiring live discovery first. Everything is a what-if; nothing is a position.
const DEMO_CANDIDATES = [
  {
    ticker: 'RELIANCE.NS', market: 'IN', data_cutoff: '2026-07-15', price: 1400,
    prev_close: 1390, returns: [0.01, -0.02, 0.015, -0.01, 0.02, -0.03, 0.01, 0.0, -0.012, 0.02, -0.04, 0.02],
    volumes: Array(12).fill(1_000_000), volatility: 0.028, spread_bps: 8, adv_usd: 50_000_000,
    source_count: 3, narrative_sources: ['a', 'b', 'c'], freshness_status: 'FRESH',
  },
  {
    ticker: 'SMALLCO.NS', market: 'IN', data_cutoff: '2026-07-15', price: 100, prev_close: 99,
    returns: [0.02, -0.05, 0.06, -0.04, 0.05, -0.07, 0.03], volumes: Array(7).fill(500_000),
    volatility: 0.05, spread_bps: 20, adv_usd: 1_500_000, source_count: 1,
    narrative_sources: ['x'], freshness_status: 'AGING',
  },
  { ticker: 'PENNY.NS', data_cutoff: '2026-07-15', source_count: 0, freshness_status: 'UNKNOWN' },
];

export default function IntelligencePage() {
  const [health, setHealth] = useState<EurekaHealthResponse | null>(null);
  const [twins, setTwins] = useState<DecisionTwinsResponse | null>(null);
  const [run, setRun] = useState<DailyShadowRunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(() => {
    Promise.all([getEurekaHealth(), getDecisionTwins(20)])
      .then(([h, t]) => {
        setHealth(h);
        setTwins(t);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runLoop = useCallback(async () => {
    setRunning(true);
    try {
      const res = await postDailyShadowRun({
        session_date: new Date().toISOString().slice(0, 10),
        candidates: DEMO_CANDIDATES,
      });
      setRun(res);
      load();
    } catch {
      setRun(null);
    } finally {
      setRunning(false);
    }
  }, [load]);

  const backendOffline = !loading && health === null;

  return (
    <div className="max-w-5xl mx-auto space-y-5" data-testid="intelligence-loop">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Intelligence Loop</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Closed-loop shadow run — freeze falsifiable predictions, resolve them later without leakage, learn.
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
        Shadow mode: every prediction is <span className="text-slate-200 font-medium">recorded, never acted on</span>.
        Outputs are <span className="font-mono text-slate-300">SIMULATED_ONLY</span>, resolved later against real
        prices without look-ahead. <span className="font-mono text-slate-300">execution_gate=LOCKED</span>;
        no human action is required to accumulate evidence.
      </div>

      {loading && (
        <div className="text-sm text-slate-500 py-8 text-center" data-testid="intel-loading">
          Loading intelligence loop…
        </div>
      )}

      {backendOffline && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 text-xs">
          <span className="text-amber-400 font-semibold">BACKEND OFFLINE</span>{' '}
          <span className="text-slate-400">
            Start the API: <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {!loading && !backendOffline && (
        <>
          {/* Empirical Readiness vs Empirical Score — the key honest distinction */}
          {health && (
            <section className="bg-slate-900 border border-slate-700 rounded-lg p-4 space-y-3" data-testid="eureka-health">
              <h2 className="text-sm font-semibold text-slate-200">Closed-loop health</h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <Stat label="Empirical Readiness" value={`${health.empirical_readiness_score}/10`} tone="text-emerald-300" />
                <Stat label="Empirical Score" value={`${health.empirical_score}/10`} tone="text-orange-400" />
                <Stat label="Twins frozen" value={String(health.twins_frozen)} />
                <Stat label="Predictions resolved" value={String(health.predictions_resolved)} />
              </div>
              <p className="text-[11px] text-slate-500">{health.empirical_note}</p>
              <p className="text-[11px] text-slate-500">
                Loop closed: <span className={health.loop_closed ? 'text-emerald-400' : 'text-slate-400'}>
                  {health.loop_closed ? 'yes' : 'not yet'}</span>
                {health.mean_brier !== null && <> · mean Brier {health.mean_brier}</>}
              </p>
            </section>
          )}

          <section className="bg-slate-900 border border-slate-700 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-200">Run a shadow day</h2>
              <button
                onClick={runLoop}
                disabled={running}
                className="bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white text-sm rounded px-4 py-1.5"
                data-testid="run-shadow"
              >
                {running ? 'Running…' : 'Run shadow day'}
              </button>
            </div>
            <p className="text-[11px] text-slate-500">
              Cheaply rejects weak candidates, allocates deeper analysis to high-value uncertainty, and freezes a
              Decision Twin per surviving candidate. No trade is placed.
            </p>
          </section>

          {run && run.ok && (
            <section className="bg-slate-900 border border-indigo-800/50 rounded-lg p-4 space-y-3" data-testid="shadow-result" data-execution-permission="false">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <Stat label="Considered" value={String(run.candidates_considered)} />
                <Stat label="Rejected cheaply" value={String(run.rejected_cheaply)} tone="text-slate-400" />
                <Stat label="Twins frozen" value={String(run.twins_created)} tone="text-indigo-300" />
                <Stat label="Predictions frozen" value={String(run.predictions_frozen)} tone="text-emerald-300" />
              </div>

              <div>
                <p className="text-slate-500 text-[11px] mb-1">Attention queue (ranked by priority)</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-slate-500 text-left border-b border-slate-800">
                        <th className="py-1 pr-3">Candidate</th>
                        <th className="py-1 pr-3">State</th>
                        <th className="py-1 pr-3">Depth</th>
                        <th className="py-1 pr-3">Regime</th>
                        <th className="py-1 pr-3">Process</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.attention_queue.map((q) => (
                        <tr key={q.candidate} className="border-b border-slate-800/50">
                          <td className="py-1 pr-3 font-mono text-slate-200">{q.candidate}</td>
                          <td className={`py-1 pr-3 font-semibold ${VOTE_TONE[q.advisory_state] ?? 'text-slate-300'}`}>
                            {q.advisory_state}
                          </td>
                          <td className="py-1 pr-3 text-slate-400">{q.depth}</td>
                          <td className="py-1 pr-3 font-mono text-[10px] text-slate-500">{q.regime}</td>
                          <td className="py-1 pr-3 text-slate-300">{q.process_quality ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {run.top_research_actions.length > 0 && (
                <div className="text-xs">
                  <p className="text-slate-500 mb-1">Most valuable next research action</p>
                  <ul className="space-y-1">
                    {run.top_research_actions.map((a, i) => (
                      <li key={i} className="text-sky-300 font-mono text-[11px]">
                        {a.candidate}: acquire <span className="font-semibold">{a.action}</span> (net VoI {a.net_voi})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {run.no_research_needed.length > 0 && (
                <p className="text-[11px] text-slate-500">
                  No research worthwhile for: {run.no_research_needed.join(', ')}
                </p>
              )}
            </section>
          )}

          {twins && twins.twins.length > 0 && (
            <section className="bg-slate-900 border border-slate-700 rounded-lg p-4 space-y-2" data-testid="twins-list">
              <h2 className="text-sm font-semibold text-slate-200">Recent Decision Twins (immutable)</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 text-left border-b border-slate-800">
                      <th className="py-1 pr-3">Candidate</th>
                      <th className="py-1 pr-3">Cutoff</th>
                      <th className="py-1 pr-3">State</th>
                      <th className="py-1 pr-3">Regime</th>
                      <th className="py-1 pr-3">Integrity hash</th>
                    </tr>
                  </thead>
                  <tbody>
                    {twins.twins.map((t) => (
                      <tr key={t.twin_id} className="border-b border-slate-800/50">
                        <td className="py-1 pr-3 font-mono text-slate-200">{t.candidate_id}</td>
                        <td className="py-1 pr-3 text-slate-400">{t.info_cutoff}</td>
                        <td className={`py-1 pr-3 font-semibold ${VOTE_TONE[t.advisory_state] ?? 'text-slate-300'}`}>
                          {t.advisory_state}
                        </td>
                        <td className="py-1 pr-3 font-mono text-[10px] text-slate-500">{t.regime_key}</td>
                        <td className="py-1 pr-3 font-mono text-[10px] text-slate-600">{t.immutability_hash.slice(0, 12)}…</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-sm font-medium ${tone ?? 'text-slate-200'}`}>{value}</div>
    </div>
  );
}
