'use client';

import { useState } from 'react';
import { runLiveRefresh, type LiveRefreshRunResponse } from '@/lib/apiClient';

// Advisory-only operator refresh button — Calibration Corpus + Hosted
// Canary sprint, Phase 4.
//
// Hard rules baked into the copy and component shape:
//   * Never says "Execute", "Trade", "Order", "Buy", "Sell", "Position",
//     or "Broker".  The visible verb is "Refresh", and the subtext makes
//     clear it does not trade.
//   * The button surfaces the structured response (advisory_status,
//     execution_gate, broker_api_called, ai_execution_count, source
//     counts, rows written, last run timestamps) so the operator can
//     see exactly what the backend reported.
//   * When the backend is offline the button shows a degraded warning
//     and explicitly does NOT pretend a refresh ran.

function statusTone(status: string): { label: string; color: string; bg: string } {
  switch (status) {
    case 'SUCCESS':
      return { label: status, color: '#1f7a3a', bg: 'rgba(31,122,58,0.12)' };
    case 'PARTIAL':
      return { label: status, color: '#a85a00', bg: 'rgba(168,90,0,0.12)' };
    case 'FAILED':
      return { label: status, color: '#a82323', bg: 'rgba(168,35,35,0.12)' };
    case 'SKIPPED':
      return { label: status, color: '#3a5478', bg: 'rgba(58,84,120,0.12)' };
    default:
      return { label: status || 'UNKNOWN', color: '#555', bg: 'rgba(0,0,0,0.04)' };
  }
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().replace('T', ' ').replace(/\.\d+Z?$/, 'Z');
  } catch {
    return iso;
  }
}

export function RunRefreshButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LiveRefreshRunResponse | null>(null);
  const [degraded, setDegraded] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setDegraded(null);
    try {
      const data = await runLiveRefresh();
      setResult(data);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'Backend unavailable. No refresh was attempted.';
      setDegraded(msg);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const tone = result ? statusTone(result.refresh_status) : null;

  return (
    <section
      aria-labelledby="run-refresh-heading"
      data-testid="run-refresh-panel"
      className="rounded-lg border p-4"
      style={{ borderColor: 'rgba(200, 154, 74, 0.32)', background: 'rgba(200,154,74,0.04)' }}
    >
      <h2
        id="run-refresh-heading"
        className="text-sm font-mono uppercase tracking-widest"
        style={{ color: 'var(--sp-gold)' }}
      >
        Operator source refresh
      </h2>
      <p className="mt-1 text-xs text-gray-600">
        Refreshes read-only public/configured sources. Does not trade.
        execution_gate=LOCKED.
      </p>

      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        data-testid="run-refresh-button"
        className="mt-3 inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-mono"
        style={{
          color: 'var(--sp-gold)',
          border: '1px solid rgba(200,154,74,0.5)',
          background: loading ? 'rgba(200,154,74,0.06)' : 'rgba(200,154,74,0.10)',
          opacity: loading ? 0.7 : 1,
          cursor: loading ? 'wait' : 'pointer',
        }}
      >
        {loading ? 'Refreshing…' : 'Run advisory-only source refresh'}
      </button>

      {degraded && (
        <p
          data-testid="run-refresh-degraded"
          className="mt-3 rounded border px-2 py-1 text-xs"
          style={{
            color: '#a82323',
            background: 'rgba(168,35,35,0.06)',
            borderColor: 'rgba(168,35,35,0.30)',
          }}
        >
          Backend offline — no refresh attempted. {degraded}
        </p>
      )}

      {result && (
        <div className="mt-3 space-y-2 text-xs font-mono" data-testid="run-refresh-result">
          <div className="flex flex-wrap items-center gap-2">
            {tone && (
              <span
                className="rounded px-2 py-0.5"
                data-testid="run-refresh-status"
                style={{ color: tone.color, background: tone.bg }}
              >
                {tone.label}
              </span>
            )}
            <span
              className="rounded px-2 py-0.5"
              style={{ color: 'var(--sp-gold)', background: 'rgba(200,154,74,0.10)' }}
            >
              {result.advisory_status}
            </span>
            <span
              className="rounded px-2 py-0.5"
              style={{ color: '#3a5478', background: 'rgba(58,84,120,0.10)' }}
            >
              execution_gate={result.execution_gate}
            </span>
            <span
              className="rounded px-2 py-0.5"
              style={{ color: '#3a5478', background: 'rgba(58,84,120,0.10)' }}
            >
              broker_api_called={String(result.broker_api_called)}
            </span>
            <span
              className="rounded px-2 py-0.5"
              style={{ color: '#3a5478', background: 'rgba(58,84,120,0.10)' }}
            >
              ai_execution_count={result.ai_execution_count}
            </span>
          </div>

          <table className="w-full text-left">
            <tbody>
              <tr>
                <td className="pr-3 text-gray-500">attempted</td>
                <td>{result.sources_attempted}</td>
                <td className="pr-3 text-gray-500">succeeded</td>
                <td>{result.sources_succeeded}</td>
              </tr>
              <tr>
                <td className="pr-3 text-gray-500">skipped</td>
                <td>{result.sources_skipped}</td>
                <td className="pr-3 text-gray-500">failed</td>
                <td>{result.sources_failed}</td>
              </tr>
              <tr>
                <td className="pr-3 text-gray-500">rows written</td>
                <td>{result.rows_written}</td>
                <td className="pr-3 text-gray-500">last finished</td>
                <td>{formatTimestamp(result.finished_at_utc)}</td>
              </tr>
              <tr>
                <td className="pr-3 text-gray-500">last started</td>
                <td colSpan={3}>{formatTimestamp(result.started_at_utc)}</td>
              </tr>
            </tbody>
          </table>

          {result.source_results.length > 0 && (
            <ul className="mt-2 space-y-1">
              {result.source_results.map((sr) => {
                const t = statusTone(sr.status);
                return (
                  <li
                    key={sr.source}
                    className="flex items-center gap-2"
                    data-testid={`run-refresh-source-${sr.source}`}
                  >
                    <span
                      className="rounded px-1.5 py-0.5"
                      style={{ color: t.color, background: t.bg }}
                    >
                      {t.label}
                    </span>
                    <span>{sr.source}</span>
                    <span className="text-gray-500">rows={sr.rows_written}</span>
                    {sr.error_redacted && (
                      <span className="text-gray-500">err={sr.error_redacted}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {result.blocking_reasons && result.blocking_reasons.length > 0 && (
            <p className="mt-2 text-amber-700">
              Refresh blocked: {result.blocking_reasons.join('; ')}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
