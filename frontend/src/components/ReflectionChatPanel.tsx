'use client';

import { useState } from 'react';
import type { UserReflection, AiSummary } from '@/types';
import { AdvisoryOnlyBadge } from './AdvisoryOnlyBadge';

interface Props {
  eventId: string;
  reflections: UserReflection[];
  aiSummaries: AiSummary[];
}

const CONVICTION_OPTIONS = ['LOW', 'MODERATE', 'HIGH', 'VERY_HIGH'];

export function ReflectionChatPanel({ eventId, reflections, aiSummaries }: Props) {
  const [text, setText] = useState('');
  const [conviction, setConviction] = useState('MODERATE');
  const [saved, setSaved] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSaved(true);
    setText('');
    setTimeout(() => setSaved(false), 3000);
  }

  const allEntries = [
    ...reflections.map((r) => ({ kind: 'reflection' as const, ts: r.reflected_at, data: r })),
    ...aiSummaries.map((s) => ({ kind: 'ai' as const, ts: s.summarized_at, data: s })),
  ].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg flex flex-col">
      <div className="px-5 py-4 border-b border-slate-700/60">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-300">Reflection Desk</h3>
          <AdvisoryOnlyBadge />
        </div>
        <p className="text-xs text-slate-500 mt-1">
          Human notes and AI discussion context for {eventId}. Not a recommendation.
        </p>
      </div>

      {/* Thread */}
      <div className="flex-1 p-4 space-y-3 overflow-y-auto max-h-80">
        {allEntries.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-6">No reflections yet. Add one below.</p>
        ) : (
          allEntries.map((entry, i) => {
            if (entry.kind === 'reflection') {
              const r = entry.data as UserReflection;
              return (
                <div key={i} className="flex gap-2.5">
                  <div className="w-6 h-6 rounded-full bg-purple-800 flex items-center justify-center shrink-0 text-xs text-white mt-0.5">
                    H
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-semibold text-purple-400">Human</span>
                      <span className="text-xs text-slate-600">{r.conviction_level}</span>
                      <span className="text-xs text-slate-600">{formatTs(r.reflected_at)}</span>
                    </div>
                    <p className="text-sm text-slate-200 leading-relaxed">{r.reflection_text}</p>
                  </div>
                </div>
              );
            }
            const s = entry.data as AiSummary;
            return (
              <div key={i} className="flex gap-2.5">
                <div className="w-6 h-6 rounded-full bg-sky-900 flex items-center justify-center shrink-0 text-xs text-sky-300 mt-0.5">
                  AI
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-sky-400">Advisory Context</span>
                    <AdvisoryOnlyBadge />
                    <span className="text-xs text-slate-600">{formatTs(s.summarized_at)}</span>
                  </div>
                  <p className="text-sm text-slate-300 leading-relaxed">{s.summary_text}</p>
                  <p className="text-xs text-slate-600 italic mt-1">{s.advisory_note}</p>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-slate-700/60">
        {saved && (
          <div className="mb-3 text-xs text-emerald-400 bg-emerald-950/40 border border-emerald-900/40 rounded px-3 py-2">
            Reflection logged (mock — connect to backend to persist).
          </div>
        )}
        <textarea
          className="w-full bg-slate-900 border border-slate-700 rounded p-3 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-slate-500"
          rows={3}
          placeholder="Add your human reflection on this signal…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex items-center justify-between mt-2 gap-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">Conviction:</label>
            <select
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none"
              value={conviction}
              onChange={(e) => setConviction(e.target.value)}
            >
              {CONVICTION_OPTIONS.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={!text.trim()}
            className="px-4 py-1.5 rounded bg-purple-700 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium transition-colors"
          >
            Log Reflection
          </button>
        </div>
      </form>
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
