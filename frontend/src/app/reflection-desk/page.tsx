'use client';

import { useState, useEffect } from 'react';
import { getSignals, getSignalDetail } from '@/lib/apiClient';
import type { InboxItem, UserReflection, AiSummary } from '@/types';
import { MOCK_INBOX_ITEMS, MOCK_REFLECTIONS, MOCK_AI_SUMMARIES } from '@/lib/mockData';
import { ReflectionChatPanel } from '@/components/ReflectionChatPanel';
import { BullStateBadge } from '@/components/BullStateBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

export default function ReflectionDeskPage() {
  const [items, setItems] = useState<InboxItem[]>(MOCK_INBOX_ITEMS);
  const [isMock, setIsMock] = useState(true);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string>(MOCK_INBOX_ITEMS[0].event_id);
  const [reflections, setReflections] = useState<UserReflection[]>(MOCK_REFLECTIONS);
  const [aiSummaries, setAiSummaries] = useState<AiSummary[]>(MOCK_AI_SUMMARIES);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    getSignals().then(({ data, isMock: mock }) => {
      setItems(data.items);
      setIsMock(mock);
      if (data.items.length > 0) setSelectedId(data.items[0].event_id);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (loading) return;
    setDetailLoading(true);
    getSignalDetail(selectedId).then(({ data }) => {
      setReflections(data.reflections);
      setAiSummaries(data.ai_summaries);
      setDetailLoading(false);
    });
  }, [selectedId, loading]);

  const selected = items.find((i) => i.event_id === selectedId) ?? items[0];

  const signalsWithActivity = items.filter(
    (i) => reflections.some((r) => r.event_id === i.event_id) ||
            aiSummaries.some((s) => s.event_id === i.event_id)
  );

  const visibleReflections = reflections.filter((r) => r.event_id === selectedId);
  const visibleSummaries = aiSummaries.filter((s) => s.event_id === selectedId);

  return (
    <div className="max-w-6xl mx-auto space-y-5">
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
          <h1 className="text-xl font-bold text-white">Reflection Desk</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Human reflection and AI advisory context — HUMAN_REVIEW_REQUIRED
          </p>
        </div>
        <AdvisoryOnlyBadge size="md" />
      </div>

      <div className="bg-amber-950/20 border border-amber-900/40 rounded-lg px-4 py-2.5 text-xs text-amber-400">
        Reflections and AI summaries are discussion context only. They do not constitute recommendations or authorizations to execute. AI execution count:{' '}
        <span className="font-mono font-bold text-emerald-400">0</span>.
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-500 text-sm">Loading signals…</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
          {/* Signal list */}
          <div className="lg:col-span-1">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Signals</h2>
            <div className="space-y-1.5">
              {items.map((item) => {
                const hasActivity =
                  reflections.some((r) => r.event_id === item.event_id) ||
                  aiSummaries.some((s) => s.event_id === item.event_id);
                const ec = item.event_count ?? 1;
                const srcLabel = item.source_name || item.source_file || '';
                return (
                  <button
                    key={item.event_id}
                    onClick={() => setSelectedId(item.event_id)}
                    className={`w-full text-left px-3 py-2 rounded transition-colors ${
                      selectedId === item.event_id
                        ? 'bg-slate-700 border border-slate-600'
                        : 'hover:bg-slate-800 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-bold font-mono text-sm text-white truncate">{item.ticker}</span>
                      {hasActivity && <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <BullStateBadge state={item.signal_state} />
                      {ec > 1 && (
                        <span className="text-[10px] font-mono text-slate-400 bg-slate-800/80 border border-slate-700/60 rounded px-1.5 py-0.5">
                          {ec} supporting events
                        </span>
                      )}
                    </div>
                    {srcLabel && (
                      <div className="text-[10px] text-slate-500 font-mono mt-1 truncate">
                        src={srcLabel}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>

            <div className="mt-4 p-3 bg-slate-800/40 rounded border border-slate-700/40 text-xs text-slate-500">
              {signalsWithActivity.length} of {items.length} signals have activity.
            </div>
          </div>

          {/* Chat panel */}
          <div className="lg:col-span-3">
            {selected && (
              <div className="mb-3 flex items-center gap-3">
                <span className="font-bold font-mono text-white">{selected.ticker}</span>
                <BullStateBadge state={selected.signal_state} size="md" />
                <AdvisoryOnlyBadge />
              </div>
            )}
            {detailLoading ? (
              <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-8 text-center text-slate-500 text-sm">
                Loading reflections…
              </div>
            ) : (
              <ReflectionChatPanel
                eventId={selectedId}
                reflections={visibleReflections}
                aiSummaries={visibleSummaries}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
