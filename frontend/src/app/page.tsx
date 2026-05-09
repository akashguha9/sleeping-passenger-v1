'use client';

import { useState, useEffect } from 'react';
import { getSignals, checkHealth } from '@/lib/apiClient';
import type { HealthResponse } from '@/lib/apiClient';
import type { InboxListResponse } from '@/types';
import { MOCK_INBOX_RESPONSE, MOCK_SOURCE_HEALTH } from '@/lib/mockData';
import { BullStateBadge } from '@/components/BullStateBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';
import { SourceHealthPanel } from '@/components/SourceHealthPanel';
import Link from 'next/link';

export default function DashboardPage() {
  const [response, setResponse] = useState<InboxListResponse>(MOCK_INBOX_RESPONSE);
  const [isMock, setIsMock] = useState(true);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getSignals(), checkHealth()]).then(([signals, h]) => {
      setResponse(signals.data);
      setIsMock(signals.isMock);
      setHealth(h);
      setLoading(false);
    });
  }, []);

  const { items, fabric_bull_state, fabric_stats, generated_at } = response;

  const pending = items.filter((i) => i.user_status === 'pending').length;
  const watchlist = items.filter((i) => i.user_status === 'watchlist').length;
  const humanReview = items.filter((i) => i.user_status === 'human_review').length;
  const rejected = items.filter((i) => i.user_status === 'rejected').length;
  const reconciled = items.filter((i) => i.user_status === 'reconciled').length;

  const topSignals = items
    .filter((i) => i.user_status !== 'rejected')
    .sort((a, b) => b.priority_score - a.priority_score)
    .slice(0, 4);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Mock fallback banner */}
      {!loading && isMock && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">BACKEND OFFLINE</span>
          <span className="text-slate-400">
            Showing mock data. Start the FastAPI server:{' '}
            <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Signal intelligence overview — {loading ? '…' : formatTs(generated_at)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      {/* Safety statement + backend status */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg p-4 flex items-center justify-between gap-4">
        <div className="flex-1">
          <p className="text-sm text-slate-400">
            <span className="text-white font-semibold">This system does not place trades.</span>{' '}
            All signals are advisory only. Human decision and manual logging are required for every action.
          </p>
          {!loading && (
            <div className="mt-2 flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full shrink-0 ${health ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span className="text-xs text-slate-500">
                Backend:{' '}
                {health ? (
                  <span className="text-emerald-400 font-mono">
                    connected — v{health.version} · {health.advisory_status} · AI executions: {health.ai_execution_count}
                  </span>
                ) : (
                  <span className="text-amber-400 font-mono">offline — mock data active</span>
                )}
              </span>
            </div>
          )}
        </div>
        <div className="shrink-0 text-right">
          <div className="text-xs text-slate-500">AI Executions</div>
          <div className="text-2xl font-bold font-mono text-emerald-400">0</div>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-500 text-sm">Loading signals…</div>
      ) : (
        <>
          {/* Fabric state + stats */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4 md:col-span-1">
              <div className="text-xs text-slate-500 mb-2">Fabric Bull State</div>
              <BullStateBadge state={fabric_bull_state} size="lg" />
            </div>
            <StatCard label="Total Signals" value={fabric_stats.total_signals} />
            <StatCard label="Source Files" value={fabric_stats.source_files} />
            <StatCard label="Tickers" value={fabric_stats.total_tickers} />
            <StatCard label="Human Review" value={humanReview} highlight />
          </div>

          {/* Status breakdown */}
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-slate-300 mb-4">Inbox Status Breakdown</h2>
            <div className="grid grid-cols-5 gap-3">
              <StatusBar label="Pending" count={pending} total={items.length} color="bg-slate-500" />
              <StatusBar label="Watchlist" count={watchlist} total={items.length} color="bg-blue-500" />
              <StatusBar label="Human Review" count={humanReview} total={items.length} color="bg-amber-500" />
              <StatusBar label="Rejected" count={rejected} total={items.length} color="bg-red-500" />
              <StatusBar label="Reconciled" count={reconciled} total={items.length} color="bg-emerald-500" />
            </div>
          </div>

          {/* Top signals + source health */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-300">Top Signals by Priority</h2>
                <Link href="/signal-inbox" className="text-xs text-slate-500 hover:text-slate-300">
                  View all →
                </Link>
              </div>
              <div className="space-y-2">
                {topSignals.map((s) => (
                  <Link key={s.event_id} href={`/signal-inbox/${s.event_id}`} className="block">
                    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 hover:border-slate-600 transition-colors flex items-center gap-4">
                      <div className="flex items-center gap-2.5 flex-1 min-w-0">
                        <span className="font-bold font-mono text-white w-14 shrink-0">{s.ticker}</span>
                        <BullStateBadge state={s.signal_state} />
                        <span className="text-xs text-slate-500 truncate">{s.entry_type}</span>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <ScoreBar value={s.priority_score} />
                        <span className="text-sm font-mono text-slate-200 w-10 text-right">
                          {s.priority_score.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>

            <div>
              <h2 className="text-sm font-semibold text-slate-300 mb-3">Source Health</h2>
              <SourceHealthPanel sources={MOCK_SOURCE_HEALTH} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold font-mono ${highlight ? 'text-amber-400' : 'text-white'}`}>{value}</div>
    </div>
  );
}

function StatusBar({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between text-xs mb-1.5">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300 font-mono">{count}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-700">
        <div className={`h-2 rounded-full ${color} score-bar`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ScoreBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value > 0.7 ? 'bg-emerald-500' : value > 0.4 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="w-20 h-1.5 rounded-full bg-slate-700">
      <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
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
