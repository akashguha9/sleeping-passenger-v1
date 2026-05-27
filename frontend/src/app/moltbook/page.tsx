'use client';

import { useState, useEffect } from 'react';
import { getMoltbook } from '@/lib/apiClient';
import type { MoltbookEntry } from '@/types';
import { MOCK_MOLTBOOK_ENTRIES } from '@/lib/mockData';
import { MoltbookEntryCard } from '@/components/MoltbookEntryCard';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

const MISTAKE_CATEGORIES = [
  'good_signal_bad_timing',
  'bad_signal_lucky_profit',
  'good_signal_good_execution',
  'bad_signal_correct_rejection',
  'missed_signal',
  'overtraded_signal',
  'chaos_ignored',
  'false_confirmation',
  'late_entry',
  'early_exit',
  'no_trade_correct',
  'no_trade_missed_opportunity',
  'trade_loss',
  'manual_exit_loss',
  'stop_loss_breach',
];

export default function MoltbookPage() {
  const [entries, setEntries] = useState<MoltbookEntry[]>(MOCK_MOLTBOOK_ENTRIES);
  const [isMock, setIsMock] = useState(true);
  const [loading, setLoading] = useState(true);
  const [showRaw, setShowRaw] = useState(false);
  const [rawTotal, setRawTotal] = useState<number>(MOCK_MOLTBOOK_ENTRIES.length);
  const [visible, setVisible] = useState<number>(MOCK_MOLTBOOK_ENTRIES.length);
  const [hiddenDuplicates, setHiddenDuplicates] = useState<number>(0);
  const [hiddenTestDemo, setHiddenTestDemo] = useState<number>(0);
  const [hiddenIneligible, setHiddenIneligible] = useState<number>(0);
  const [hiddenUnconfirmed, setHiddenUnconfirmed] = useState<number>(0);
  const [hiddenCrossSource, setHiddenCrossSource] = useState<number>(0);
  const [defaultViewNotice, setDefaultViewNotice] = useState<string>(
    'Moltbook default view hides duplicates, test/demo fixtures, and unconfirmed closed-trade rows.',
  );

  useEffect(() => {
    setLoading(true);
    getMoltbook({ includeRaw: showRaw }).then(({ data, isMock: mock }) => {
      setEntries(data.items);
      setIsMock(mock);
      setRawTotal(data.raw_total_entries ?? data.items.length);
      setVisible(data.visible_entries ?? data.items.length);
      setHiddenDuplicates(data.hidden_duplicates ?? 0);
      setHiddenTestDemo(data.hidden_test_demo ?? 0);
      setHiddenIneligible(data.hidden_ineligible ?? 0);
      setHiddenUnconfirmed(data.hidden_unconfirmed ?? 0);
      setHiddenCrossSource(data.hidden_cross_source_duplicates ?? 0);
      if (data.default_view_notice) {
        setDefaultViewNotice(data.default_view_notice);
      }
      setLoading(false);
    });
  }, [showRaw]);

  // Category distribution: derive from visible canonical entries only so
  // duplicates / test-demo / ineligible rows can never inflate the
  // operator-facing histogram.
  const visibleEntriesForCategories = showRaw
    ? entries.filter((e) => {
        const raw = e as unknown as Record<string, unknown>;
        return !Number(raw.hidden_from_default_view ?? 0);
      })
    : entries;
  const categoryCounts = MISTAKE_CATEGORIES.reduce<Record<string, number>>((acc, cat) => {
    acc[cat] = visibleEntriesForCategories.filter((e) => e.mistake_type === cat).length;
    return acc;
  }, {});

  const totalHidden =
    hiddenDuplicates + hiddenTestDemo + hiddenIneligible + hiddenUnconfirmed;

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {!loading && isMock && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">BACKEND OFFLINE</span>
          <span className="text-slate-400">
            Showing mock data.{' '}
            <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Moltbook</h1>
          <p className="text-sm text-slate-500 mt-0.5">Self-correction and mistake learning layer</p>
        </div>
        <AdvisoryOnlyBadge size="md" />
      </div>

      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4 text-xs text-slate-400">
        Moltbook shows <span className="text-slate-200 font-semibold">finalized trade outcomes only</span>:
        stop-loss, trailing stop, take-profit, partial TP, closed wins/losses, manual exits, and breakeven exits.
        All entries are <span className="text-amber-400 font-semibold">ADVISORY_ONLY</span>. AI execution count is always{' '}
        <span className="text-emerald-400 font-mono font-bold">0</span>.
      </div>

      <div className="bg-slate-900/60 border border-slate-700/40 rounded-lg px-4 py-2.5 text-xs text-slate-400">
        {defaultViewNotice}
      </div>

      {!loading && totalHidden > 0 && (
        <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg px-4 py-2.5 flex items-start justify-between gap-3 text-xs">
          <div className="text-slate-400">
            Duplicate/test/unconfirmed entries hidden from default operator view.{' '}
            <span className="text-slate-300 font-mono">
              raw={rawTotal} visible={visible} dup={hiddenDuplicates} cross_src={hiddenCrossSource}{' '}
              test={hiddenTestDemo} unconfirmed={hiddenUnconfirmed} ineligible={hiddenIneligible}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setShowRaw((prev) => !prev)}
            className="shrink-0 text-amber-400 hover:text-amber-300 underline-offset-2 hover:underline"
          >
            {showRaw ? 'hide raw/debug entries' : 'show raw/debug entries'}
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-center py-16 text-slate-500 text-sm">Loading moltbook…</div>
      ) : (
        <>
          {/* Category summary (visible canonical entries only) */}
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-slate-300 mb-3">Mistake Category Distribution</h2>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(categoryCounts)
                .filter(([, count]) => count > 0)
                .map(([cat, count]) => (
                  <div
                    key={cat}
                    className="flex items-center justify-between px-3 py-2 rounded bg-slate-900/40 border border-slate-700/30"
                  >
                    <span className="text-xs text-slate-400 font-mono">{cat.replace(/_/g, ' ')}</span>
                    <span className="text-xs font-mono font-bold text-white">{count}</span>
                  </div>
                ))}
            </div>
            {Object.values(categoryCounts).every((c) => c === 0) && (
              <p className="text-xs text-slate-500 text-center py-4">No entries recorded yet.</p>
            )}
          </div>

          {/* Entries */}
          <div>
            <h2 className="text-sm font-semibold text-slate-300 mb-3">
              Entries ({entries.length})
              {showRaw && (
                <span className="ml-2 text-amber-400 font-mono">raw mode</span>
              )}
            </h2>
            {entries.length === 0 ? (
              <div className="text-center py-12 text-slate-500 text-sm">No Moltbook entries yet.</div>
            ) : (
              <div className="space-y-4">
                {entries.map((entry) => (
                  <MoltbookEntryCard key={entry.entry_id} entry={entry} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
