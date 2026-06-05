'use client';

import { useState, useEffect, useMemo } from 'react';
import { getSignals, getSignalsDiagnostics } from '@/lib/apiClient';
import type {
  InboxDiagnosticsResponse,
  InboxListResponse,
  UserStatus,
} from '@/types';
import { MOCK_INBOX_RESPONSE } from '@/lib/mockData';
import { SignalCard } from '@/components/SignalCard';
import { BullStateBadge } from '@/components/BullStateBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { ScoreCalibrationBadge } from '@/components/ScoreCalibrationBadge';
import { SourceHealthWarnings } from '@/components/SourceHealthWarnings';
import {
  ALL_ACTIONS,
  ACTION_LABELS,
  deriveNextHumanAction,
  type NextHumanAction,
} from '@/lib/nextHumanAction';

const STATUSES: { value: UserStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'watchlist', label: 'Watchlist' },
  { value: 'human_review', label: 'Human Review' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'reconciled', label: 'Reconciled' },
];

const ACTION_FILTERS: { value: NextHumanAction | 'all'; label: string }[] = [
  { value: 'all', label: 'All Actions' },
  ...ALL_ACTIONS.map((a) => ({ value: a, label: ACTION_LABELS[a] })),
];

const BULL_STATES = ['HURACÁN', 'AVENTADOR', 'MURCIÉLAGO', 'DIABLO', 'GALLARDO', 'ISLERO', 'MIURA'];
const SORT_OPTIONS = [
  { value: 'severity', label: 'Next Action Severity' },
  { value: 'priority', label: 'Priority Score' },
  { value: 'persistence', label: 'Persistence' },
  { value: 'observed', label: 'Observed At' },
  { value: 'kill_rate', label: 'Kill Rate' },
];

export default function SignalInboxPage() {
  const [response, setResponse] = useState<InboxListResponse>(MOCK_INBOX_RESPONSE);
  const [diagnostics, setDiagnostics] = useState<InboxDiagnosticsResponse | null>(null);
  const [isMock, setIsMock] = useState(true);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<UserStatus | 'all'>('all');
  const [stateFilter, setStateFilter] = useState<string>('all');
  const [actionFilter, setActionFilter] = useState<NextHumanAction | 'all'>('all');
  const [sortBy, setSortBy] = useState('severity');

  useEffect(() => {
    Promise.all([getSignals(50, 72), getSignalsDiagnostics(72)]).then(
      ([signalsRes, diag]) => {
        setResponse(signalsRes.data);
        setIsMock(signalsRes.isMock);
        setDiagnostics(diag);
        setLoading(false);
      },
    ).catch(() => {
      // Defence-in-depth: the API helpers already fall back to mock/null on
      // network/timeout errors; this guarantees we leave the loading state
      // even if an unexpected error ever escapes.
      setLoading(false);
    });
  }, []);

  const { items, fabric_bull_state } = response;
  const signalSource = response.signal_source ?? (isMock ? 'mock' : 'unknown');
  const freshnessHours = response.freshness_window_hours ?? 72;

  // Pre-compute next_human_action once per item so filter/sort/render share results.
  const enriched = useMemo(
    () =>
      items.map((item) => ({
        item,
        action: deriveNextHumanAction(item),
      })),
    [items],
  );

  // Action-bucket counts derived from deduplicated items.
  const actionCounts = useMemo(() => {
    const c: Record<NextHumanAction, number> = {
      IGNORE: 0,
      HAVE_A_LOOK: 0,
      WATCHLIST: 0,
      HUMAN_REVIEW: 0,
      MANUAL_CANDIDATE: 0,
    };
    for (const { action } of enriched) c[action.action] += 1;
    return c;
  }, [enriched]);

  const filtered = useMemo(
    () =>
      enriched
        .filter(({ item }) => statusFilter === 'all' || item.user_status === statusFilter)
        .filter(({ item }) => stateFilter === 'all' || item.signal_state === stateFilter)
        .filter(({ action }) => actionFilter === 'all' || action.action === actionFilter)
        .sort((a, b) => {
          if (sortBy === 'severity') return b.action.severity_rank - a.action.severity_rank;
          if (sortBy === 'priority') return b.item.priority_score - a.item.priority_score;
          if (sortBy === 'persistence') return b.item.persistence_score - a.item.persistence_score;
          if (sortBy === 'kill_rate') return b.item.kill_rate_score - a.item.kill_rate_score;
          return new Date(b.item.observed_at).getTime() - new Date(a.item.observed_at).getTime();
        }),
    [enriched, statusFilter, stateFilter, actionFilter, sortBy],
  );

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {/* Mock fallback banner — explicit, never silent */}
      {!loading && isMock && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">MOCK_FALLBACK</span>
          <span className="text-slate-400">
            Backend unreachable. Showing static demo cards (RTX / ZIM / etc. are
            NOT real signals). Start the API:{' '}
            <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {/* Bridge / source banner — when backend is live */}
      {!loading && !isMock && (
        <div className="bg-slate-900 border border-slate-700/60 rounded-lg px-4 py-2.5 text-xs text-slate-400 flex flex-wrap items-center gap-3">
          <span className={`font-mono font-semibold ${
            signalSource === 'live_events'
              ? 'text-emerald-400'
              : signalSource === 'legacy_fabric'
                ? 'text-sky-400'
                : 'text-slate-300'
          }`}>
            SIGNAL_SOURCE={signalSource}
          </span>
          <span>
            window={freshnessHours}h · {items.length} promoted candidate{items.length === 1 ? '' : 's'}
          </span>
          {diagnostics?.newest_fresh_event_at && (
            <span className="text-slate-500">
              newest fresh event: {formatTs(diagnostics.newest_fresh_event_at)}
            </span>
          )}
          {diagnostics?.latest_signal_event_at && (
            <span className="text-slate-500">
              latest signal_event: {formatTs(diagnostics.latest_signal_event_at)}
            </span>
          )}
        </div>
      )}

      {/* Score calibration — scores must never be shown as validated unless
          there is enough reconciled-outcome evidence. */}
      {!loading && <ScoreCalibrationBadge calibration={response.score_calibration} />}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Signal Inbox</h1>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-sm text-slate-500">Fabric state:</span>
            {loading ? (
              <span className="text-sm text-slate-600">…</span>
            ) : (
              <>
                <BullStateBadge state={fabric_bull_state} size="md" />
                <span className="text-sm text-slate-500">· {items.length} signals</span>
              </>
            )}
          </div>
        </div>
        <AdvisoryOnlyBadge size="md" />
      </div>

      <SourceHealthWarnings compact />

      {/* HUMAN_REVIEW_REQUIRED notice */}
      <div className="bg-amber-950/20 border border-amber-900/40 rounded-lg px-4 py-2.5 text-xs text-amber-400">
        <span className="font-semibold">HUMAN_REVIEW_REQUIRED</span> — Each signal below now carries a derived next-human-action classification. The classification is advisory-only and does not authorize execution. Review each card before logging any manual decision.
      </div>

      {/* Filters */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4 space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-slate-500 shrink-0">Action:</span>
          <div className="flex gap-1 flex-wrap">
            {ACTION_FILTERS.map((a) => {
              const count =
                a.value === 'all'
                  ? items.length
                  : (actionCounts[a.value as NextHumanAction] ?? 0);
              return (
                <button
                  key={a.value}
                  onClick={() => setActionFilter(a.value)}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    actionFilter === a.value
                      ? 'bg-slate-600 text-white'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700'
                  }`}
                >
                  {a.label}{' '}
                  <span className="font-mono text-[10px] text-slate-500">({count})</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-slate-500">Status:</span>
            <div className="flex gap-1 flex-wrap">
              {STATUSES.map((s) => (
                <button
                  key={s.value}
                  onClick={() => setStatusFilter(s.value)}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    statusFilter === s.value
                      ? 'bg-slate-600 text-white'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div className="h-4 w-px bg-slate-700 hidden md:block" />

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">State:</span>
            <select
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
            >
              <option value="all">All States</option>
              {BULL_STATES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div className="h-4 w-px bg-slate-700 hidden md:block" />

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Sort:</span>
            <select
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          <span className="ml-auto text-xs text-slate-500">{filtered.length} shown</span>
        </div>
      </div>

      {/* Signal cards */}
      {loading ? (
        <div className="text-center py-12 text-slate-500 text-sm">Loading signals…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 space-y-2">
          {items.length === 0 && !isMock ? (
            <>
              <p className="text-slate-400 text-sm">
                No fresh promoted signals yet in the last {freshnessHours}h.
              </p>
              <p className="text-xs text-slate-600">
                Run live ingestion to populate{' '}
                <span className="font-mono text-slate-400">signal_events</span>:
              </p>
              <pre className="text-[11px] text-slate-500 font-mono mx-auto inline-block text-left">
{`python scripts/run_live_sources_phase1.py --write
python scripts/run_live_sources_phase2.py --source newsapi --write`}
              </pre>
            </>
          ) : (
            <p className="text-slate-500 text-sm">
              No signals match the current filters.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map(({ item }) => (
            <SignalCard key={item.event_id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts;
  }
}
