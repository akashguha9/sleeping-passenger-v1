'use client';

import type { GateDetails, GateVerdict } from '@/lib/nextHumanAction';

interface Props {
  details: GateDetails;
  advisoryStatus: string;
  variant?: 'inline' | 'table';
}

const VERDICT_CLASS: Record<GateVerdict, string> = {
  OK: 'text-emerald-300 bg-emerald-950/40 border-emerald-900/60',
  WEAK: 'text-amber-300 bg-amber-950/40 border-amber-900/60',
  BLOCK: 'text-red-300 bg-red-950/40 border-red-900/60',
  UNKNOWN: 'text-slate-300 bg-slate-800/60 border-slate-600/60',
  NEUTRAL: 'text-slate-300 bg-slate-800/60 border-slate-700/60',
};

function VerdictPill({ verdict }: { verdict: GateVerdict }) {
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-mono ${VERDICT_CLASS[verdict]}`}
    >
      {verdict}
    </span>
  );
}

interface Row {
  key: string;
  label: string;
  verdict: GateVerdict;
  detail: string;
}

function buildRows(details: GateDetails, advisoryStatus: string): Row[] {
  return [
    {
      key: 'source',
      label: 'Source quality',
      verdict: details.source_quality,
      detail: details.source_quality_label,
    },
    {
      key: 'priority',
      label: 'Priority',
      verdict: details.priority_gate,
      detail: details.priority_label,
    },
    {
      key: 'persistence',
      label: 'Persistence',
      verdict: details.persistence_gate,
      detail: details.persistence_label,
    },
    {
      key: 'kill_rate',
      label: 'Kill rate',
      verdict: details.kill_rate_gate,
      detail: details.kill_rate_label,
    },
    {
      key: 'blocker',
      label: 'Blocker pressure',
      verdict: details.blocker_gate,
      detail: details.blocker_label,
    },
    {
      key: 'freshness',
      label: 'Evidence freshness',
      verdict: details.freshness_gate,
      detail: details.freshness_label,
    },
    {
      key: 'rejection',
      label: 'Rejection dimensions',
      verdict: details.rejection_gate,
      detail: details.rejection_label,
    },
    {
      key: 'advisory',
      label: 'Advisory status',
      verdict: 'NEUTRAL',
      detail: advisoryStatus,
    },
  ];
}

export function GateDetailsPanel({
  details,
  advisoryStatus,
  variant = 'inline',
}: Props) {
  const rows = buildRows(details, advisoryStatus);

  if (variant === 'table') {
    return (
      <div className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-4">
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
          Gate details
        </h4>
        <table className="w-full text-xs">
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-b border-slate-800/60 last:border-0">
                <td className="py-1.5 pr-2 text-slate-500">{row.label}</td>
                <td className="py-1.5 pr-2">
                  <VerdictPill verdict={row.verdict} />
                </td>
                <td className="py-1.5 text-slate-300 font-mono">{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
      {rows.map((row) => (
        <div
          key={row.key}
          className="bg-slate-900/40 border border-slate-700/40 rounded px-2 py-1.5"
        >
          <div className="flex items-center justify-between gap-1 mb-0.5">
            <span className="text-slate-500 uppercase tracking-wide">
              {row.label}
            </span>
            <VerdictPill verdict={row.verdict} />
          </div>
          <div className="text-slate-300 font-mono truncate" title={row.detail}>
            {row.detail}
          </div>
        </div>
      ))}
    </div>
  );
}
