'use client';

import { useState, useEffect, useMemo } from 'react';
import { getLiveSignals } from '@/lib/apiClient';
import type { LiveSignalEvent, LiveSignalSource, LiveSignalsResponse } from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

const SOURCE_OPTIONS: { value: '' | LiveSignalSource; label: string }[] = [
  { value: '', label: 'All Sources' },
  { value: 'polymarket', label: 'Polymarket' },
  { value: 'gdelt', label: 'GDELT' },
  { value: 'sec_edgar', label: 'SEC EDGAR' },
  { value: 'newsapi', label: 'NewsAPI' },
  { value: 'event_registry', label: 'Event Registry' },
  { value: 'etherscan', label: 'Etherscan' },
  { value: 'grok_xai', label: 'Grok/xAI' },
  { value: 'market_data', label: 'Market Data' },
  { value: 'india', label: 'India' },
  { value: 'global_filings', label: 'Global Filings' },
];

const SOURCE_COLORS: Record<string, string> = {
  polymarket: 'text-violet-400 bg-violet-900/30 border-violet-700/40',
  gdelt: 'text-sky-400 bg-sky-900/30 border-sky-700/40',
  sec_edgar: 'text-amber-400 bg-amber-900/30 border-amber-700/40',
  newsapi: 'text-emerald-400 bg-emerald-900/30 border-emerald-700/40',
  event_registry: 'text-teal-400 bg-teal-900/30 border-teal-700/40',
  etherscan: 'text-orange-400 bg-orange-900/30 border-orange-700/40',
  grok_xai: 'text-indigo-400 bg-indigo-900/30 border-indigo-700/40',
  market_data: 'text-blue-400 bg-blue-900/30 border-blue-700/40',
  india: 'text-yellow-500 bg-yellow-900/30 border-yellow-700/40',
  global_filings: 'text-rose-400 bg-rose-900/30 border-rose-700/40',
};

const SOURCE_LABELS: Record<string, string> = {
  polymarket: 'Polymarket',
  gdelt: 'GDELT',
  sec_edgar: 'SEC EDGAR',
  newsapi: 'NewsAPI',
  event_registry: 'Event Registry',
  etherscan: 'Etherscan',
  grok_xai: 'Grok/xAI',
  market_data: 'Market Data',
  india: 'India (NSE/RBI/SEBI)',
  global_filings: 'Global Filings',
};

function getTitle(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  return p.title || p.question as string || ev.event_id;
}

function getSubtitle(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  if (ev.source_name === 'polymarket') {
    const parts: string[] = [];
    if (p.market_id) parts.push(`Market ${p.market_id}`);
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.liquidity != null) parts.push(`Liq: ${Number(p.liquidity).toLocaleString()}`);
    if (p.end_date) parts.push(`Ends: ${p.end_date}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'gdelt') {
    const parts: string[] = [];
    if (p.domain) parts.push(p.domain as string);
    if (p.sourcecountry) parts.push(p.sourcecountry as string);
    if (p.seendate) parts.push(`Seen: ${p.seendate}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'sec_edgar') {
    const parts: string[] = [];
    if (p.form_type) parts.push(p.form_type as string);
    if (p.cik) parts.push(`CIK ${p.cik}`);
    if (p.filing_date) parts.push(`Filed: ${p.filing_date}`);
    if (p.accession_number) parts.push(p.accession_number as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'newsapi') {
    const parts: string[] = [];
    if (p.publisher) parts.push(p.publisher as string);
    if (p.published_at) parts.push(`Published: ${p.published_at}`);
    if (p.url) parts.push(p.url as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'event_registry') {
    const parts: string[] = [];
    if (p.publisher) parts.push(p.publisher as string);
    if (p.date_time) parts.push(`Date: ${p.date_time}`);
    if (p.url) parts.push(p.url as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'etherscan') {
    const parts: string[] = [];
    if (p.hash) parts.push(`Hash: ${(p.hash as string).slice(0, 14)}…`);
    if (p.from_address) parts.push(`From: ${(p.from_address as string).slice(0, 10)}…`);
    if (p.to_address) parts.push(`To: ${(p.to_address as string).slice(0, 10)}…`);
    if (p.block_number) parts.push(`Block: ${p.block_number}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'grok_xai') {
    const parts: string[] = [];
    if (p.narrative_frame) parts.push(`Frame: ${p.narrative_frame as string}`);
    if (p.confidence_score != null) parts.push(`Confidence: ${Number(p.confidence_score).toFixed(2)}`);
    if (p.model_name) parts.push(`Model: ${p.model_name as string}`);
    if (p.created_at) parts.push(`At: ${p.created_at as string}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'market_data') {
    const parts: string[] = [];
    if (p.symbol) parts.push(String(p.symbol));
    if (p.latest_price != null) parts.push(`$${Number(p.latest_price).toFixed(2)}`);
    if (p.price_change_pct != null) {
      const pct = Number(p.price_change_pct);
      parts.push(`${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`);
    }
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.market_confirmation_score != null) parts.push(`Score: ${Number(p.market_confirmation_score).toFixed(2)}`);
    if (p.provider) parts.push(`(${p.provider as string})`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'india') {
    const parts: string[] = [];
    if (p.regulatory_source) parts.push(String(p.regulatory_source).toUpperCase());
    if (p.index_name) parts.push(String(p.index_name));
    if (p.last_price != null) parts.push(`₹${Number(p.last_price).toLocaleString()}`);
    if (p.percent_change != null) {
      const pct = Number(p.percent_change);
      parts.push(`${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`);
    }
    if (p.regulatory_note) parts.push(String(p.regulatory_note));
    return parts.join(' · ');
  }
  if (ev.source_name === 'global_filings') {
    const parts: string[] = [];
    if (p.jurisdiction) parts.push(String(p.jurisdiction));
    if (p.exchange_or_regulator) parts.push(String(p.exchange_or_regulator));
    if (p.disclosure_type) parts.push(String(p.disclosure_type).replace(/_/g, ' '));
    if (p.issuer_name) parts.push(String(p.issuer_name));
    if (p.ticker_or_identifier) parts.push(`[${String(p.ticker_or_identifier)}]`);
    if (p.published_at) parts.push(`Filed: ${String(p.published_at)}`);
    return parts.join(' · ');
  }
  return ev.event_id;
}

function matchesSearch(ev: LiveSignalEvent, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const p = ev.raw_payload;
  return [
    ev.event_id,
    ev.source_name,
    p.title,
    p.market_id,
    p.domain,
    p.cik,
    p.form_type,
    p.accession_number,
    p.sourcecountry,
    p.language,
    p.publisher,
    p.description,
    p.url,
    p.body,
    p.date_time,
    p.hash,
    p.from_address,
    p.to_address,
    p.block_number,
    p.interpreted_topic,
    p.narrative_frame,
    p.summary_text,
    p.source_prompt,
    p.model_name,
    p.symbol,
    p.provider,
    p.period,
    p.interval,
    p.index_name,
    p.regulatory_source,
    p.regulatory_url,
    p.regulatory_note,
    p.issuer_name,
    p.ticker_or_identifier,
    p.jurisdiction,
    p.exchange_or_regulator,
    p.disclosure_type,
    p.summary,
  ]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(q));
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

function SignalEventCard({ ev }: { ev: LiveSignalEvent }) {
  const [expanded, setExpanded] = useState(false);
  const sourceColor = SOURCE_COLORS[ev.source_name] ?? 'text-slate-400 bg-slate-800/40 border-slate-700/40';
  const sourceLabel = SOURCE_LABELS[ev.source_name] ?? ev.source_name;

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-2">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${sourceColor}`}>
            {sourceLabel}
          </span>
          <span className="text-xs text-slate-500 font-mono">{ev.event_id}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-red-900/30 border border-red-800/40 text-red-400">
            EXECUTION LOCKED
          </span>
          <span className="text-xs text-slate-500">{formatTs(ev.fetched_at)}</span>
        </div>
      </div>

      {/* Title */}
      <p className="text-sm text-slate-200 leading-snug">{getTitle(ev)}</p>

      {/* Subtitle */}
      {getSubtitle(ev) && (
        <p className="text-xs text-slate-500">{getSubtitle(ev)}</p>
      )}

      {/* Safety badges */}
      <div className="flex items-center gap-2 flex-wrap pt-0.5">
        <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400 font-mono">
          {ev.advisory_status}
        </span>
        {ev.human_review_required && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900/30 border border-amber-800/40 text-amber-400 font-mono">
            HUMAN_REVIEW_REQUIRED
          </span>
        )}
        <span className="text-xs text-slate-600 font-mono">
          AI executions: {ev.ai_execution_count}
        </span>
      </div>

      {/* Raw payload toggle */}
      <div>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
        >
          {expanded ? '▲ hide payload' : '▼ show raw payload'}
        </button>
        {expanded && (
          <pre className="mt-2 text-xs text-slate-400 bg-slate-900/60 rounded p-3 overflow-x-auto max-h-48 leading-relaxed">
            {JSON.stringify(ev.raw_payload, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

export default function LiveSignalsPage() {
  const [sourceFilter, setSourceFilter] = useState<'' | LiveSignalSource>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [data, setData] = useState<LiveSignalsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [backendOffline, setBackendOffline] = useState(false);

  useEffect(() => {
    setLoading(true);
    getLiveSignals(sourceFilter || undefined, 200).then((result) => {
      if (!result) {
        setBackendOffline(true);
      } else {
        setBackendOffline(false);
        setData(result);
      }
      setLoading(false);
    });
  }, [sourceFilter]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.live_signal_events.filter((ev) => matchesSearch(ev, searchQuery));
  }, [data, searchQuery]);

  const sourceCounts = useMemo(() => {
    if (!data) return {} as Record<string, number>;
    return data.live_signal_events.reduce<Record<string, number>>((acc, ev) => {
      acc[ev.source_name] = (acc[ev.source_name] ?? 0) + 1;
      return acc;
    }, {});
  }, [data]);

  const latestTs = useMemo(() => {
    if (!data || data.live_signal_events.length === 0) return null;
    return data.live_signal_events[0].fetched_at;
  }, [data]);

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Live Signals</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Real-time ingestion from Polymarket, GDELT, SEC EDGAR, NewsAPI, Event Registry, Etherscan, Grok/xAI, Market Data, India (NSE/RBI/SEBI), and Global Filings — advisory only
          </p>
        </div>
        <div className="flex items-center gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      {/* Advisory safety banner */}
      <div className="bg-slate-900 border border-red-900/40 rounded-lg px-4 py-3">
        <p className="text-sm text-slate-400">
          <span className="text-white font-semibold">No execution.</span>{' '}
          All live signals are{' '}
          <span className="font-mono text-amber-400">ADVISORY_ONLY</span> with{' '}
          <span className="font-mono text-amber-400">HUMAN_REVIEW_REQUIRED</span> and{' '}
          <span className="font-mono text-red-400">execution_gate=LOCKED</span>. This system does not
          place trades, connect to brokers, or execute orders of any kind.
        </p>
      </div>

      {/* Backend offline */}
      {backendOffline && !loading && (
        <div className="bg-slate-900 border border-amber-800/60 rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs">
          <span className="text-amber-400 font-semibold shrink-0">BACKEND OFFLINE</span>
          <span className="text-slate-400">
            Could not reach the FastAPI server. Start it with:{' '}
            <span className="font-mono text-slate-300">python scripts/api_server.py</span>
          </span>
        </div>
      )}

      {/* Summary stats */}
      {!loading && data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-1">Total Signals</div>
            <div className="text-2xl font-bold font-mono text-white">{data.count}</div>
          </div>
          {Object.entries(sourceCounts).map(([src, cnt]) => (
            <div key={src} className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-1">{SOURCE_LABELS[src] ?? src}</div>
              <div className="text-2xl font-bold font-mono text-white">{cnt}</div>
            </div>
          ))}
          {latestTs && (
            <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-1">Latest Fetched</div>
              <div className="text-xs font-mono text-slate-300 mt-1">{formatTs(latestTs)}</div>
            </div>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex gap-1">
          {SOURCE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setSourceFilter(opt.value)}
              className={`px-3 py-1.5 text-xs rounded font-medium transition-colors ${
                sourceFilter === opt.value
                  ? 'bg-slate-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-700'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Search title, ticker, domain, CIK…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 min-w-48 bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            clear
          </button>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-center py-20 text-slate-500 text-sm">Loading live signals…</div>
      ) : backendOffline ? (
        <div className="text-center py-20 space-y-2">
          <p className="text-slate-500 text-sm">Backend offline — no live signal data available.</p>
          <p className="text-xs text-slate-600">
            Run the Phase 1 ingestion first:{' '}
            <span className="font-mono">python scripts/live_source_runner.py</span>
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 space-y-2">
          <p className="text-slate-500 text-sm">
            {data && data.count > 0
              ? 'No signals match your filter or search.'
              : 'No live signals ingested yet.'}
          </p>
          {(!data || data.count === 0) && (
            <p className="text-xs text-slate-600">
              Run the Phase 1 ingestion:{' '}
              <span className="font-mono">python scripts/live_source_runner.py</span>
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="text-xs text-slate-600 font-mono">
            {filtered.length} of {data?.count ?? 0} signal{filtered.length !== 1 ? 's' : ''}
          </div>
          <div className="space-y-3">
            {filtered.map((ev) => (
              <SignalEventCard key={ev.event_id} ev={ev} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
