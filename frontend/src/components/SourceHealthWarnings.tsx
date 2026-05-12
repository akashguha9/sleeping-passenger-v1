'use client';

import { useEffect, useState } from 'react';
import { getSourceHealthSummary } from '@/lib/apiClient';
import type { SourceHealthSummaryEntry, SourceHealthSummaryResponse } from '@/types';

interface Props {
  /** If true, render a compact one-line summary (suitable for tight pages). */
  compact?: boolean;
  /** Optional pre-fetched data to avoid duplicate requests. */
  initial?: SourceHealthSummaryResponse | null;
  /** When provided, only warnings for these source_names are shown. */
  onlySources?: string[];
}

/**
 * Frontend-facing source-health warning banner.
 *
 * Consumes `/source-health/summary` (sanitized; never leaks API keys) and
 * surfaces human-readable warnings for credit exhaustion, rate limits,
 * timeouts, placeholders, etc.  Advisory only — does not authorize
 * execution.
 */
export function SourceHealthWarnings({ compact = false, initial = null, onlySources }: Props) {
  const [data, setData] = useState<SourceHealthSummaryResponse | null>(initial);
  const [loading, setLoading] = useState(initial === null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (initial !== null) return;
    let cancelled = false;
    getSourceHealthSummary().then((res) => {
      if (cancelled) return;
      setData(res);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [initial]);

  if (loading || !data) return null;

  // Only surface warnings / errors / placeholders — we skip 'ok' and 'info NO_RUNS'.
  const issues = (data.sources || []).filter((s) => {
    if (onlySources && onlySources.length > 0 && !onlySources.includes(s.source_name)) {
      return false;
    }
    if (s.severity === 'warning' || s.severity === 'error') return true;
    if (s.severity === 'info' && s.category === 'PLACEHOLDER') return true;
    return false;
  });

  if (issues.length === 0) return null;

  const summary = summarize(issues);
  const headline = issues.length === 1 ? issues[0].human_message : summary;

  if (compact) {
    return (
      <div
        className="px-3 py-2 rounded-lg text-xs flex items-center gap-3"
        style={{
          background: 'rgba(214, 168, 90, 0.04)',
          border: '1px solid rgba(214, 168, 90, 0.22)',
          color: 'var(--sp-bone)',
        }}
      >
        <span className="sp-chip sp-chip-warn shrink-0">Source Warning</span>
        <span className="truncate" style={{ color: 'var(--sp-mist)' }}>
          {headline}
        </span>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        background: 'rgba(214, 168, 90, 0.04)',
        border: '1px solid rgba(214, 168, 90, 0.22)',
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left"
        style={{ color: 'var(--sp-bone)' }}
      >
        <span className="sp-chip sp-chip-warn shrink-0">
          {issues.length} Source {issues.length === 1 ? 'Warning' : 'Warnings'}
        </span>
        <span className="text-xs truncate flex-1" style={{ color: 'var(--sp-mist)' }}>
          {headline}
        </span>
        <span className="text-[10px] font-mono uppercase tracking-widest shrink-0" style={{ color: 'var(--sp-mist)' }}>
          {expanded ? '▲ hide' : '▼ details'}
        </span>
      </button>
      {expanded && (
        <div className="px-4 pb-3 pt-1 space-y-2" style={{ borderTop: '1px solid rgba(214, 168, 90, 0.18)' }}>
          {issues.map((s) => (
            <SourceIssueRow key={s.source_name} issue={s} />
          ))}
          <div className="pt-2 text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
            Sanitized · No secrets shown · Advisory_Only
          </div>
        </div>
      )}
    </div>
  );
}

function SourceIssueRow({ issue }: { issue: SourceHealthSummaryEntry }) {
  const accent =
    issue.severity === 'error'
      ? 'var(--sp-rust)'
      : issue.severity === 'warning'
      ? 'var(--sp-gold)'
      : 'var(--sp-cyan)';
  return (
    <div className="flex items-start gap-3 text-xs">
      <span
        className="mt-1 w-1.5 h-1.5 rounded-full shrink-0"
        style={{ background: accent }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-semibold" style={{ color: 'var(--sp-bone)' }}>
            {issue.label}
          </span>
          <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
            {issue.category}
          </span>
          {issue.last_run_at && (
            <span className="text-[10px] font-mono" style={{ color: 'var(--sp-mist)' }}>
              · last run {formatTs(issue.last_run_at)}
            </span>
          )}
        </div>
        <div style={{ color: 'var(--sp-mist)' }}>{issue.human_message}</div>
      </div>
    </div>
  );
}

function summarize(issues: SourceHealthSummaryEntry[]): string {
  const labels = issues.slice(0, 3).map((s) => s.label);
  const tail = issues.length > 3 ? ` +${issues.length - 3} more` : '';
  return `${labels.join(' · ')}${tail}`;
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}
