'use client';

import { useState } from 'react';
import { MOCK_INBOX_RESPONSE } from '@/lib/mockData';
import { SignalCard } from '@/components/SignalCard';
import { BullStateBadge } from '@/components/BullStateBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import type { UserStatus } from '@/types';

const STATUSES: { value: UserStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'watchlist', label: 'Watchlist' },
  { value: 'human_review', label: 'Human Review' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'reconciled', label: 'Reconciled' },
];

const BULL_STATES = ['HURACÁN', 'AVENTADOR', 'MURCIÉLAGO', 'DIABLO', 'GALLARDO', 'ISLERO', 'MIURA'];
const SORT_OPTIONS = [
  { value: 'priority', label: 'Priority Score' },
  { value: 'persistence', label: 'Persistence' },
  { value: 'observed', label: 'Observed At' },
];

export default function SignalInboxPage() {
  const { items, fabric_bull_state } = MOCK_INBOX_RESPONSE;
  const [statusFilter, setStatusFilter] = useState<UserStatus | 'all'>('all');
  const [stateFilter, setStateFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState('priority');

  const filtered = items
    .filter((i) => statusFilter === 'all' || i.user_status === statusFilter)
    .filter((i) => stateFilter === 'all' || i.signal_state === stateFilter)
    .sort((a, b) => {
      if (sortBy === 'priority') return b.priority_score - a.priority_score;
      if (sortBy === 'persistence') return b.persistence_score - a.persistence_score;
      return new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime();
    });

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Signal Inbox</h1>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-sm text-slate-500">Fabric state:</span>
            <BullStateBadge state={fabric_bull_state} size="md" />
            <span className="text-sm text-slate-500">· {items.length} signals</span>
          </div>
        </div>
        <AdvisoryOnlyBadge size="md" />
      </div>

      {/* HUMAN_REVIEW_REQUIRED notice */}
      <div className="bg-amber-950/20 border border-amber-900/40 rounded-lg px-4 py-2.5 text-xs text-amber-400">
        <span className="font-semibold">HUMAN_REVIEW_REQUIRED</span> — All signals below are advisory intelligence. No signal authorizes execution. Review each carefully before logging any manual trade.
      </div>

      {/* Filters */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
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

      {/* Signal cards */}
      {filtered.length === 0 ? (
        <div className="text-center py-12 text-slate-500 text-sm">No signals match the current filters.</div>
      ) : (
        <div className="space-y-3">
          {filtered.map((item) => (
            <SignalCard key={item.event_id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
