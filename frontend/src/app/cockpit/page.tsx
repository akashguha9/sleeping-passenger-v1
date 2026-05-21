'use client';

import { useState, useEffect } from 'react';
import { getDiagnosticsCockpit, type CockpitResponse } from '@/lib/apiClient';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded bg-slate-900/40 border border-slate-700/30">
      <span className="text-xs text-slate-400">{label}</span>
      <span className="text-xs font-mono font-bold text-white">{value}</span>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">{title}</h2>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

export default function CockpitPage() {
  const [data, setData] = useState<CockpitResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDiagnosticsCockpit().then((res) => {
      setData(res);
      setLoading(false);
    });
  }, []);

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Operator Cockpit</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Closed-loop system integrity at a glance
          </p>
        </div>
        <AdvisoryOnlyBadge size="md" />
      </div>

      {/* Advisory-only safety banner — required copy. */}
      <div
        data-testid="advisory-banner"
        className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-3 text-xs text-slate-300"
      >
        <span className="text-amber-400 font-semibold">Advisory diagnostics only.</span>{' '}
        Human execution required. No broker action is performed. AI execution count is always{' '}
        <span className="text-emerald-400 font-mono font-bold">0</span>.
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-500 text-sm">Loading cockpit…</div>
      ) : !data ? (
        <div className="bg-slate-900 border border-slate-700/60 rounded-lg px-4 py-3 text-xs text-slate-400">
          Backend offline — start it with{' '}
          <span className="font-mono text-slate-300">python scripts/api_server.py</span>.
          These panels are advisory diagnostics; nothing is performed when offline.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <Panel title="Closed Loop Health">
            <Stat label="coverage" value={data.closed_loop.closed_loop_coverage} />
            <Stat label="signals without outcomes" value={data.closed_loop.signals_without_outcomes} />
            <Stat label="trades w/o reconciliation" value={data.closed_loop.manual_trades_without_reconciliation} />
            <Stat label="losses w/o Moltbook" value={data.closed_loop.closed_losses_without_moltbook} />
            <Stat label="unresolved repair debt" value={data.closed_loop.unresolved_repair_debt} />
          </Panel>

          <Panel title="Truth Purity">
            <Stat label="purity score" value={data.truth_purity.truth_purity_score} />
            <Stat label="fake rows detected" value={data.truth_purity.fake_rows_detected} />
            <Stat label="release gate" value={data.truth_purity.release_gate_passed ? 'PASS' : 'FAIL'} />
          </Panel>

          <Panel title="Moltbook Learning">
            <Stat label="lesson conversion" value={String(data.learning_efficiency.lesson_conversion_rate ?? '—')} />
            <Stat label="repeat error rate" value={String(data.learning_efficiency.repeat_error_rate ?? '—')} />
            <Stat label="learning efficiency" value={String(data.learning_efficiency.learning_efficiency_score ?? '—')} />
          </Panel>

          <Panel title="Source Independence">
            <Stat label="cohorts" value={data.source_independence.cohort_count} />
            <Stat label="flagged (ant-mill)" value={data.source_independence.flagged_cohorts.length} />
          </Panel>

          <Panel title="Signal Half-Life & Operator Load">
            <p className="text-xs text-slate-400">
              Signals decay unless reinforced; operator overload recommends{' '}
              <span className="text-amber-400 font-semibold">no new risk — reconcile first</span>.
              These are advisory recommendations only.
            </p>
          </Panel>

          <Panel title="Broken Windows">
            <Stat label="repair debt score" value={data.broken_windows.repair_debt_score} />
            <Stat label="release gate impact" value={data.broken_windows.release_gate_impact} />
            <p className="text-xs text-slate-500">{data.broken_windows.recommended_next_repair}</p>
          </Panel>

          <Panel title="Defensive Alpha">
            <Stat label="defensive events" value={data.defensive_alpha.total_defensive_events} />
            <Stat label="fake rows blocked" value={data.defensive_alpha.fake_data_rows_blocked} />
            <Stat label="losses → lessons" value={data.defensive_alpha.closed_losses_captured_as_lessons} />
          </Panel>

          <Panel title="Pre-Real-Money Readiness">
            <Stat label="advisory-only verified" value={data.invariants.advisory_only_verified ? 'YES' : 'NO'} />
            <Stat label="human execution verified" value={data.invariants.human_execution_verified ? 'YES' : 'NO'} />
            <Stat label="broker_api_called == false" value={data.invariants.broker_api_called_false_verified ? 'YES' : 'NO'} />
            <Stat label="ai_execution_count == 0" value={data.invariants.ai_execution_count_zero_verified ? 'YES' : 'NO'} />
          </Panel>
        </div>
      )}
    </div>
  );
}
