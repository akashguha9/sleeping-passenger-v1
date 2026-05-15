'use client';

import type { ReactNode } from 'react';

/**
 * Sprint 9C — Reusable, intentional empty-state surface.
 *
 * Use this component anywhere the MVP legitimately has nothing to show
 * yet (no reactor snapshots, no reconciled outcomes, no paper-trade
 * outcomes, no refresh metadata, no token configured, …).  The card
 * stays *advisory-only* — no buttons that imply trade authorisation,
 * no fake data, no execution language.
 */

export type AdvisoryEmptyStateVariant =
  | 'no_data'
  | 'pending_calibration'
  | 'no_reconciled'
  | 'no_paper_outcomes'
  | 'no_refresh_metadata'
  | 'optional_source_missing'
  | 'planned_adapter'
  | 'token_not_set'
  | 'api_failure'
  | 'no_template_yet';

interface Props {
  variant: AdvisoryEmptyStateVariant;
  title?: string;
  message?: string;
  /** Optional command the operator can run. Rendered in a code block. */
  command?: string;
  /** Optional next-step hint sentence (rendered below the message). */
  hint?: string;
  /** Optional secondary content (e.g. a small list of suggested actions). */
  children?: ReactNode;
}

const PRESETS: Record<
  AdvisoryEmptyStateVariant,
  { title: string; message: string; hint?: string }
> = {
  no_data: {
    title: 'No data yet',
    message:
      'No manual or paper journal entries yet. Learning completeness activates once entries exist.',
    hint: 'Log a manual or paper trade to begin building the journal.',
  },
  pending_calibration: {
    title: 'No reactor-at-decision snapshots',
    message:
      'No reactor-at-decision snapshots captured yet. Calibration capacity is wired, but no evidence exists yet.',
    hint: 'Capture the reactor snapshot fields when logging a trade.',
  },
  no_reconciled: {
    title: 'No reconciled outcomes',
    message:
      'No reconciled outcomes yet. Outcome calibration remains very_low confidence.',
    hint: 'Reconcile a logged trade once the outcome is known.',
  },
  no_paper_outcomes: {
    title: 'No paper outcomes',
    message:
      'No paper outcomes imported yet. Paper calibration remains unavailable.',
    hint: 'Update the outcome columns in the paper-trade ledger CSV, then re-import.',
  },
  no_refresh_metadata: {
    title: 'No refresh attempt recorded yet',
    message:
      'No refresh attempt recorded yet. Run the local refresh script or register the scheduled task.',
  },
  optional_source_missing: {
    title: 'Optional source not configured',
    message:
      'Optional source not configured. This is not a core-source failure.',
  },
  planned_adapter: {
    title: 'Planned source adapter',
    message: 'Planned source adapter. Not counted as failure.',
  },
  token_not_set: {
    title: 'Local API token not set',
    message:
      'Write endpoints may require MVP_API_TOKEN. Set token for this browser session for protected local mode. This token does not authorize trade execution.',
  },
  api_failure: {
    title: 'Could not load status',
    message:
      'Could not load status. No execution action is available from this system.',
  },
  no_template_yet: {
    title: 'No paper-trade template yet',
    message:
      'Export a paper-trade template before maintaining the Excel ledger.',
    hint: 'Run python scripts/export_paper_trade_template.py to create one.',
  },
};

export function AdvisoryEmptyState({
  variant,
  title,
  message,
  command,
  hint,
  children,
}: Props) {
  const preset = PRESETS[variant];
  const t = title ?? preset.title;
  const m = message ?? preset.message;
  const h = hint ?? preset.hint;

  return (
    <div
      className="rounded border border-slate-800 bg-slate-950/60 p-4 space-y-2"
      data-testid="advisory-empty-state"
      data-variant={variant}
      data-advisory-only="true"
      data-execution-permission="false"
      data-broker-api-called="false"
    >
      <div className="flex items-center justify-between">
        <h3
          className="text-sm font-mono uppercase tracking-wider text-slate-300"
          data-testid="empty-title"
        >
          {t}
        </h3>
        <span className="text-[10px] uppercase font-mono text-slate-500">
          advisory-only
        </span>
      </div>
      <p className="text-xs text-slate-400 leading-snug" data-testid="empty-message">
        {m}
      </p>
      {h && (
        <p
          className="text-[11px] text-slate-500 leading-snug"
          data-testid="empty-hint"
        >
          {h}
        </p>
      )}
      {command && (
        <pre
          className="text-[11px] font-mono px-2 py-1.5 rounded bg-slate-900 border border-slate-800 text-slate-200 whitespace-pre-wrap"
          data-testid="empty-command"
        >
          {command}
        </pre>
      )}
      {children}
      <p
        className="text-[10px] text-slate-600 pt-1"
        data-testid="empty-safety-copy"
      >
        No execution action is available from this surface.
      </p>
    </div>
  );
}
