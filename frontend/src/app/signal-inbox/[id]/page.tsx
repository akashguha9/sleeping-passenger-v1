'use client';

import { useParams } from 'next/navigation';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { getSignalDetail, postDecision } from '@/lib/apiClient';
import type { SignalDetailResponse } from '@/types';
import { getMockSignalDetail } from '@/lib/mockData';
import { BullStateBadge } from '@/components/BullStateBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { SignalScorePanel } from '@/components/SignalScorePanel';
import { EvidenceTimeline } from '@/components/EvidenceTimeline';
import { ReflectionChatPanel } from '@/components/ReflectionChatPanel';
import { ManualTradeLogForm } from '@/components/ManualTradeLogForm';
import { NextHumanActionBadge } from '@/components/NextHumanActionBadge';
import { GateDetailsPanel } from '@/components/GateDetailsPanel';
import { ReactorDiagnosticsPanel } from '@/components/ReactorDiagnosticsPanel';
import { deriveNextHumanAction } from '@/lib/nextHumanAction';

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-slate-400',
  watchlist: 'text-blue-400',
  human_review: 'text-amber-400',
  rejected: 'text-red-400',
  reconciled: 'text-emerald-400',
};

export default function SignalDetailPage() {
  const params = useParams();
  const eventId = decodeURIComponent(String(params.id));

  const [detail, setDetail] = useState<SignalDetailResponse>(getMockSignalDetail(eventId));
  const [isMock, setIsMock] = useState(true);
  const [loading, setLoading] = useState(true);
  const [markedStatus, setMarkedStatus] = useState('');
  const [marking, setMarking] = useState(false);
  const [markError, setMarkError] = useState('');

  useEffect(() => {
    getSignalDetail(eventId).then(({ data, isMock: mock }) => {
      setDetail(data);
      setIsMock(mock);
      setMarkedStatus(data.signal.user_status);
      setLoading(false);
    });
  }, [eventId]);

  async function handleMark(status: string) {
    if (isMock) {
      setMarkError('Backend offline — cannot save signal status.');
      return;
    }
    setMarking(true);
    setMarkError('');
    try {
      await postDecision(eventId, status);
      setMarkedStatus(status);
    } catch {
      setMarkError('Failed to update signal status.');
    } finally {
      setMarking(false);
    }
  }

  const { signal, reflections, ai_summaries, manual_trades } = detail;
  const displayStatus = markedStatus || signal.user_status;

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Mock fallback banner */}
      {!loading && isMock && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">BACKEND OFFLINE</span>
          <span className="text-slate-400">
            Showing mock data.{' '}
            <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Link href="/signal-inbox" className="hover:text-slate-300">Signal Inbox</Link>
        <span>/</span>
        <span className="text-slate-300 font-mono">{loading ? '…' : signal.ticker}</span>
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-500 text-sm">Loading signal…</div>
      ) : (
        <>
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h1 className="text-2xl font-bold font-mono text-white">{signal.ticker}</h1>
                <BullStateBadge state={signal.signal_state} size="lg" />
                <span className={`text-sm font-medium ${STATUS_COLORS[displayStatus] ?? 'text-slate-400'}`}>
                  {displayStatus.replace('_', ' ')}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <AdvisoryOnlyBadge size="md" />
                <HumanOnlyBadge size="md" />
                <span className="text-xs text-slate-600">HUMAN_REVIEW_REQUIRED</span>
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-xs text-slate-500">Observed</div>
              <div className="text-sm text-slate-300">{formatTs(signal.observed_at)}</div>
            </div>
          </div>

          {/* Safety note */}
          <div className="bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-xs text-slate-400">
            This view is{' '}
            <span className="text-amber-400 font-semibold">ADVISORY_ONLY</span>. Viewing this signal does not constitute a recommendation, trigger, or authorization to execute any trade. AI execution count:{' '}
            <span className="text-emerald-400 font-mono font-bold">0</span>.
          </div>

          {/* Reactor diagnostics — advisory-only; never grants permission. */}
          <ReactorDiagnosticsPanel
            diagnostics={{
              reactor_state: signal.reactor_state,
              decision_grade_energy: signal.decision_grade_energy,
              echo_risk_score: signal.echo_risk_score,
              meltdown_risk_score: signal.meltdown_risk_score,
              fusion_validity: signal.fusion_validity,
              fission_branch_clarity: signal.fission_branch_clarity,
              operator_heat_score: signal.operator_heat_score,
              gallardo_block: signal.gallardo_block,
              reactor_recommendation: signal.reactor_recommendation,
              reactor_available: signal.reactor_available,
            }}
          />

          {/* Next human action panel */}
          {(() => {
            const action = deriveNextHumanAction(signal);
            return (
              <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5 space-y-4">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-3 flex-wrap">
                    <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">
                      Next human action
                    </h3>
                    <NextHumanActionBadge
                      action={action.action}
                      label={action.label}
                      size="md"
                    />
                  </div>
                  <span className="text-[10px] text-slate-500 font-mono">
                    severity {action.severity_rank}/4
                  </span>
                </div>
                <p className="text-sm text-slate-300 leading-snug">
                  <span className="text-slate-500">Reason:</span> {action.reason}
                </p>
                <GateDetailsPanel
                  details={action.gate_details}
                  advisoryStatus={signal.advisory_status}
                  variant="table"
                />
                <p className="text-[11px] text-slate-500 leading-snug">
                  This is not execution permission. Manual human decision required. No
                  broker, wallet, or auto-trading path exists in this view.
                </p>
              </div>
            );
          })()}

          {/* Main grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Left column */}
            <div className="space-y-5">
              <SignalScorePanel signal={signal} />

              {/* Source files */}
              <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Sources</h3>
                <div className="space-y-1">
                  {signal.source_file.split(',').map((f) => (
                    <div key={f} className="text-xs font-mono text-slate-400">{f.trim()}</div>
                  ))}
                </div>
              </div>

              {/* Mark signal */}
              <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Mark Signal</h3>
                <p className="text-xs text-slate-600 mb-3">ADVISORY_ONLY — status change requires human decision.</p>
                {markError && (
                  <p className="text-xs text-amber-400 mb-2">{markError}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  {['pending', 'watchlist', 'human_review', 'rejected'].map((s) => (
                    <button
                      key={s}
                      onClick={() => handleMark(s)}
                      disabled={marking || displayStatus === s}
                      className={`px-2.5 py-1.5 text-xs rounded transition-colors font-medium ${
                        displayStatus === s
                          ? 'bg-slate-600 text-white cursor-default'
                          : 'bg-slate-700 hover:bg-slate-600 text-slate-300 disabled:opacity-50'
                      }`}
                    >
                      {s.replace('_', ' ')}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Right column (2/3) */}
            <div className="lg:col-span-2 space-y-5">
              <EvidenceTimeline signal={signal} reflections={reflections} aiSummaries={ai_summaries} />
              <ReflectionChatPanel eventId={eventId} reflections={reflections} aiSummaries={ai_summaries} />

              {/* Manual trades on this signal */}
              {manual_trades.length > 0 && (
                <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
                  <div className="flex items-center gap-2 mb-3">
                    <h3 className="text-sm font-semibold text-slate-300">Logged Trades</h3>
                    <HumanOnlyBadge />
                  </div>
                  {manual_trades.map((t) => (
                    <div key={t.trade_id} className="text-xs font-mono text-slate-400 bg-slate-900/40 rounded p-3 border border-slate-700/40">
                      <div className="flex items-center gap-3 mb-1">
                        <span className="font-bold text-slate-200">{t.ticker}</span>
                        <span className={t.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'}>
                          {t.side === 'BUY' ? 'LONG' : 'SHORT'}
                        </span>
                        <span>×{t.quantity}</span>
                        <span>@ ${t.price}</span>
                        <span className="ml-auto text-slate-600">{t.trade_id}</span>
                      </div>
                      <p className="text-slate-500 font-sans">{t.thesis}</p>
                      <div className="flex gap-3 mt-1.5 text-slate-600">
                        <span>Broker API: NOT CALLED</span>
                        <span>AI executions: 0</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <ManualTradeLogForm defaultEventId={eventId} defaultTicker={signal.ticker} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}
