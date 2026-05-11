'use client';

import { useState } from 'react';
import { searchSecurities, getSecurityDetail, getSecurityCoverage } from '@/lib/apiClient';
import type {
  GlobalSecurity,
  SecurityDetailResponse,
  SecurityCoverageResponse,
  SecuritySearchResponse,
} from '@/types';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

function InvariantRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5 rounded bg-slate-900/60">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs font-semibold font-mono text-emerald-400">{value}</span>
    </div>
  );
}

function CmdBlock({ label, cmd }: { label: string; cmd: string }) {
  return (
    <div className="space-y-0.5">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="bg-slate-900 border border-slate-700/60 rounded px-3 py-2 font-mono text-xs text-amber-300 break-all">
        {cmd}
      </div>
    </div>
  );
}

function SecurityCard({ sec }: { sec: GlobalSecurity }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-2">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-base font-bold font-mono text-white">{sec.canonical_symbol}</span>
        {sec.asset_type && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 font-mono">
            {sec.asset_type}
          </span>
        )}
        {!sec.active && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/40 border border-red-700/40 text-red-400 font-mono">
            INACTIVE
          </span>
        )}
        {sec.exchange_code && (
          <span className="text-xs text-slate-400">{sec.exchange_code}</span>
        )}
        {sec.country && (
          <span className="text-xs text-slate-500 uppercase">{sec.country}</span>
        )}
      </div>
      {sec.name && <div className="text-sm text-slate-300">{sec.name}</div>}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        {sec.currency && (
          <div>
            <div className="text-slate-500">Currency</div>
            <div className="font-mono text-slate-200">{sec.currency}</div>
          </div>
        )}
        {sec.sector && (
          <div>
            <div className="text-slate-500">Sector</div>
            <div className="text-slate-300">{sec.sector}</div>
          </div>
        )}
        {sec.industry && (
          <div>
            <div className="text-slate-500">Industry</div>
            <div className="text-slate-300">{sec.industry}</div>
          </div>
        )}
        {sec.economy_rank != null && (
          <div>
            <div className="text-slate-500">Economy Rank</div>
            <div className="font-mono text-slate-200">#{sec.economy_rank}</div>
          </div>
        )}
        {sec.isin && (
          <div>
            <div className="text-slate-500">ISIN</div>
            <div className="font-mono text-slate-400">{sec.isin}</div>
          </div>
        )}
        {sec.yahoo_symbol && sec.yahoo_symbol !== sec.canonical_symbol && (
          <div>
            <div className="text-slate-500">Yahoo Symbol</div>
            <div className="font-mono text-slate-400">{sec.yahoo_symbol}</div>
          </div>
        )}
        {sec.first_seen_at && (
          <div>
            <div className="text-slate-500">First Seen</div>
            <div className="font-mono text-slate-500 text-xs">{sec.first_seen_at.slice(0, 10)}</div>
          </div>
        )}
        {sec.last_seen_at && (
          <div>
            <div className="text-slate-500">Last Seen</div>
            <div className="font-mono text-slate-500 text-xs">{sec.last_seen_at.slice(0, 10)}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function CoveragePanel({ cov }: { cov: SecurityCoverageResponse }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-3">
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">OHLCV Coverage</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-slate-500">Candle Count</div>
          <div className={`text-lg font-bold font-mono ${cov.candle_count > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
            {cov.candle_count}
          </div>
        </div>
        <div>
          <div className="text-slate-500">In Master</div>
          <div className={`font-mono font-semibold ${cov.in_securities_master ? 'text-emerald-400' : 'text-amber-400'}`}>
            {cov.in_securities_master ? 'YES' : 'NO'}
          </div>
        </div>
        {cov.first_candle_at && (
          <div>
            <div className="text-slate-500">First Candle</div>
            <div className="font-mono text-slate-400">{cov.first_candle_at.slice(0, 10)}</div>
          </div>
        )}
        {cov.last_candle_at && (
          <div>
            <div className="text-slate-500">Last Candle</div>
            <div className="font-mono text-slate-400">{cov.last_candle_at.slice(0, 10)}</div>
          </div>
        )}
      </div>
      {cov.aliases.length > 0 && (
        <div className="text-xs">
          <div className="text-slate-500 mb-1">Known Aliases</div>
          <div className="flex flex-wrap gap-1.5">
            {cov.aliases.map((a) => (
              <span key={a} className="px-2 py-0.5 rounded bg-slate-700 font-mono text-slate-300">
                {a}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="space-y-2 pt-1">
        <CmdBlock label="Discover" cmd={cov.discovery_command} />
        <CmdBlock label="Backfill OHLCV" cmd={cov.backfill_command} />
      </div>
    </div>
  );
}

function ResolutionBadge({ path }: { path: string }) {
  const colors: Record<string, string> = {
    direct: 'bg-emerald-900/30 border-emerald-700/40 text-emerald-400',
    alias: 'bg-amber-900/30 border-amber-700/40 text-amber-400',
    unknown: 'bg-red-900/30 border-red-700/40 text-red-400',
  };
  return (
    <span className={`text-xs font-mono px-1.5 py-0.5 rounded border ${colors[path] ?? colors.unknown}`}>
      {path.toUpperCase()}
    </span>
  );
}

export default function SecuritiesPage() {
  const [symbolInput, setSymbolInput] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [backendOffline, setBackendOffline] = useState(false);
  const [detail, setDetail] = useState<SecurityDetailResponse | null>(null);
  const [coverage, setCoverage] = useState<SecurityCoverageResponse | null>(null);
  const [searchResults, setSearchResults] = useState<SecuritySearchResponse | null>(null);

  async function handleLookup() {
    const sym = symbolInput.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    setBackendOffline(false);
    setDetail(null);
    setCoverage(null);

    const [det, cov] = await Promise.all([
      getSecurityDetail(sym),
      getSecurityCoverage(sym),
    ]);

    if (!det && !cov) {
      setBackendOffline(true);
    } else {
      setDetail(det);
      setCoverage(cov);
    }
    setLoading(false);
  }

  async function handleSearch() {
    const q = searchInput.trim();
    if (!q) return;
    setSearchLoading(true);
    const res = await searchSecurities(q, 30);
    setSearchResults(res);
    setSearchLoading(false);
  }

  function handleKeyDown(e: React.KeyboardEvent, fn: () => void) {
    if (e.key === 'Enter') fn();
  }

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Securities</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Global securities master — advisory-only, read-only, no execution
          </p>
        </div>
        <div className="flex items-center gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      {/* Safety banner */}
      <div className="bg-slate-900 border border-red-900/40 rounded-lg px-4 py-3">
        <p className="text-sm text-slate-400">
          <span className="text-white font-semibold">Advisory-only. No execution. Human review required.</span>{' '}
          This panel reads the local global_securities SQLite table and resolves symbol aliases.
          It does <span className="text-red-400 font-semibold">not</span> place orders,
          connect to any broker, or produce buy/sell instructions.
        </p>
      </div>

      {/* Invariants */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-2">
        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Execution Invariants</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <InvariantRow label="Advisory" value="ADVISORY_ONLY" />
          <InvariantRow label="Execution gate" value="LOCKED" />
          <InvariantRow label="Human review" value="REQUIRED" />
          <InvariantRow label="AI execution count" value="0" />
          <InvariantRow label="Broker API called" value="false" />
          <InvariantRow label="Broker order ID" value="NONE" />
        </div>
      </div>

      {/* Symbol lookup */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-3">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Symbol Lookup</div>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">Symbol</label>
            <input
              type="text"
              placeholder="SBIN.NS · 2002.TW · RELIANCE.NS"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              onKeyDown={(e) => handleKeyDown(e, handleLookup)}
              className="w-64 bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500 font-mono"
            />
          </div>
          <button
            onClick={handleLookup}
            disabled={loading || !symbolInput.trim()}
            className="px-4 py-1.5 rounded bg-slate-700 text-sm text-white font-medium hover:bg-slate-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? 'Loading…' : 'Look up'}
          </button>
          {(detail || coverage) && (
            <button
              onClick={() => { setDetail(null); setCoverage(null); }}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              clear
            </button>
          )}
        </div>
        <p className="text-xs text-slate-600">
          Try: <span className="font-mono">SBIN.NS</span> ·{' '}
          <span className="font-mono">SBI.NSE</span> (alias) ·{' '}
          <span className="font-mono">2002.TW</span> ·{' '}
          <span className="font-mono">RELIANCE.NS</span> ·{' '}
          <span className="font-mono">UNKNOWN_XYZ</span>
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

      {/* Lookup results */}
      {!loading && detail && (
        <div className="space-y-3">
          {/* Resolution header */}
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-lg font-bold font-mono text-white">{detail.canonical_symbol}</span>
            {detail.canonical_symbol !== detail.symbol && (
              <span className="text-xs text-slate-500">
                (input: <span className="font-mono">{detail.symbol}</span>)
              </span>
            )}
            <ResolutionBadge path={detail.resolution?.resolution_path ?? 'unknown'} />
            {detail.resolution?.alias_used && (
              <span className="text-xs text-slate-500">
                alias: <span className="font-mono text-amber-300">{detail.resolution.alias_used}</span>
              </span>
            )}
            {!detail.found && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/30 border border-red-700/40 text-red-400 font-mono">
                NOT IN MASTER
              </span>
            )}
          </div>

          {/* Unknown symbol */}
          {!detail.found && (
            <div className="bg-slate-900 border border-amber-800/40 rounded-lg px-4 py-4 space-y-3">
              <div className="text-sm text-amber-300 font-semibold">UNKNOWN_SYMBOL</div>
              <p className="text-xs text-slate-400">
                {detail.resolution?.message ??
                  `Symbol '${detail.symbol}' not found in global_securities or alias table.`}
              </p>
              <div className="space-y-2">
                {detail.discovery_command && (
                  <CmdBlock label="Run discovery first:" cmd={detail.discovery_command} />
                )}
                {detail.backfill_command && (
                  <CmdBlock label="Then backfill OHLCV:" cmd={detail.backfill_command} />
                )}
              </div>
            </div>
          )}

          {/* Security card */}
          {detail.found && detail.security && <SecurityCard sec={detail.security} />}

          {/* Coverage */}
          {coverage && <CoveragePanel cov={coverage} />}
        </div>
      )}

      {/* Search */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg px-4 py-3 space-y-3">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Search Securities Master</div>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">Query (symbol, name, exchange)</label>
            <input
              type="text"
              placeholder="India · NSE · TSMC · Brazil · .NS"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => handleKeyDown(e, handleSearch)}
              className="w-64 bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searchLoading || !searchInput.trim()}
            className="px-4 py-1.5 rounded bg-slate-700 text-sm text-white font-medium hover:bg-slate-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {searchLoading ? 'Searching…' : 'Search'}
          </button>
          {searchResults && (
            <button
              onClick={() => setSearchResults(null)}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              clear
            </button>
          )}
        </div>
        <p className="text-xs text-slate-600">
          The securities master is populated by running:{' '}
          <span className="font-mono">python scripts/global_security_master_discovery.py --seed-from-config --write</span>
        </p>
      </div>

      {/* Search results */}
      {!searchLoading && searchResults && (
        <div className="space-y-2">
          <div className="text-xs text-slate-500">
            {searchResults.count} result{searchResults.count !== 1 ? 's' : ''} for{' '}
            <span className="font-mono text-slate-400">"{searchResults.query}"</span>
          </div>
          {searchResults.count === 0 && (
            <div className="text-sm text-slate-500 py-6 text-center">
              No securities found. Run discovery to populate the master:{' '}
              <span className="font-mono">python scripts/global_security_master_discovery.py --seed-from-config --write</span>
            </div>
          )}
          {searchResults.results.map((sec) => (
            <SecurityCard key={sec.canonical_symbol} sec={sec} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !detail && !coverage && !searchResults && (
        <div className="text-center py-16 space-y-2">
          <p className="text-slate-500 text-sm">
            Enter a symbol to look up, or search the securities master.
          </p>
          <p className="text-xs text-slate-600">
            Populate the master first:{' '}
            <span className="font-mono">
              python scripts/global_security_master_discovery.py --seed-from-config --write
            </span>
          </p>
        </div>
      )}
    </div>
  );
}
