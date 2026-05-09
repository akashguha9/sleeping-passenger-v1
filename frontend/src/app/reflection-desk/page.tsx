'use client';

import { useState } from 'react';
import { MOCK_INBOX_ITEMS, MOCK_REFLECTIONS, MOCK_AI_SUMMARIES } from '@/lib/mockData';
import { ReflectionChatPanel } from '@/components/ReflectionChatPanel';
import { BullStateBadge } from '@/components/BullStateBadge';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

export default function ReflectionDeskPage() {
  const [selectedId, setSelectedId] = useState<string>(MOCK_INBOX_ITEMS[0].event_id);

  const selected = MOCK_INBOX_ITEMS.find((i) => i.event_id === selectedId) ?? MOCK_INBOX_ITEMS[0];
  const reflections = MOCK_REFLECTIONS.filter((r) => r.event_id === selectedId);
  const aiSummaries = MOCK_AI_SUMMARIES.filter((s) => s.event_id === selectedId);

  const signalsWithActivity = MOCK_INBOX_ITEMS.filter(
    (i) => MOCK_REFLECTIONS.some((r) => r.event_id === i.event_id) ||
            MOCK_AI_SUMMARIES.some((s) => s.event_id === i.event_id)
  );

  return (
    <div className="max-w-6xl mx-auto space-y-5">
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
        Reflections and AI summaries are discussion context only. They do not constitute recommendations or authorizations to execute. AI execution count: <span className="font-mono font-bold text-emerald-400">0</span>.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        {/* Signal list */}
        <div className="lg:col-span-1">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Signals</h2>
          <div className="space-y-1.5">
            {MOCK_INBOX_ITEMS.map((item) => {
              const hasActivity =
                MOCK_REFLECTIONS.some((r) => r.event_id === item.event_id) ||
                MOCK_AI_SUMMARIES.some((s) => s.event_id === item.event_id);
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
                    <span className="font-bold font-mono text-sm text-white">{item.ticker}</span>
                    {hasActivity && <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />}
                  </div>
                  <BullStateBadge state={item.signal_state} />
                </button>
              );
            })}
          </div>

          <div className="mt-4 p-3 bg-slate-800/40 rounded border border-slate-700/40 text-xs text-slate-500">
            {signalsWithActivity.length} of {MOCK_INBOX_ITEMS.length} signals have activity.
          </div>
        </div>

        {/* Chat panel */}
        <div className="lg:col-span-3">
          <div className="mb-3 flex items-center gap-3">
            <span className="font-bold font-mono text-white">{selected.ticker}</span>
            <BullStateBadge state={selected.signal_state} size="md" />
            <AdvisoryOnlyBadge />
          </div>
          <ReflectionChatPanel
            eventId={selectedId}
            reflections={reflections}
            aiSummaries={aiSummaries}
          />
        </div>
      </div>
    </div>
  );
}
