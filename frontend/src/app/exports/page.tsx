'use client';

import { MOCK_INBOX_ITEMS, MOCK_MANUAL_TRADES, MOCK_RECONCILIATIONS, MOCK_MOLTBOOK_ENTRIES } from '@/lib/mockData';
import { getCsvExportUrl } from '@/lib/apiClient';
import { API_BASE } from '@/lib/config';
import { ExportButton } from '@/components/ExportButton';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';

const BACKEND_CSV_EXPORTS = [
  { type: 'signal-inbox' as const, label: 'Signal Inbox' },
  { type: 'reflections' as const, label: 'Reflections' },
  { type: 'manual-trades' as const, label: 'Manual Trades' },
  { type: 'reconciliation' as const, label: 'Reconciliations' },
  { type: 'moltbook' as const, label: 'Moltbook' },
  { type: 'source-health' as const, label: 'Source Health' },
];

export default function ExportsPage() {
  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Exports</h1>
          <p className="text-sm text-slate-500 mt-0.5">Download signal data and trade records</p>
        </div>
        <AdvisoryOnlyBadge size="md" />
      </div>

      <div className="bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-xs text-slate-400">
        All exports are advisory-only records. Exports do not contain broker credentials, execution instructions,
        or any automated trigger. AI executions:{' '}
        <span className="text-emerald-400 font-mono font-bold">0</span>.
      </div>

      {/* Backend CSV downloads */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-slate-300">Backend CSV Downloads</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Live data from FastAPI server at{' '}
            <span className="font-mono">{API_BASE}</span>. Requires backend to be running.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {BACKEND_CSV_EXPORTS.map(({ type, label }) => (
            <a
              key={type}
              href={getCsvExportUrl(type)}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors"
            >
              <span>↓</span>
              <span>{label}</span>
              <span className="text-xs text-slate-500 uppercase">csv</span>
            </a>
          ))}
        </div>
      </div>

      {/* Mock data exports (offline fallback) */}
      <div className="space-y-4">
        <p className="text-xs text-slate-500 px-1">
          Mock data exports — available offline, reflect scaffold data only.
        </p>

        <ExportGroup
          title="Signal Inbox"
          description={`${MOCK_INBOX_ITEMS.length} signals from the current fabric window`}
          exports={[
            {
              label: 'Export Signal Inbox',
              filename: 'signal_inbox',
              format: 'json' as const,
              getData: () => MOCK_INBOX_ITEMS,
            },
            {
              label: 'Export Signal Inbox',
              filename: 'signal_inbox',
              format: 'csv' as const,
              getData: () => MOCK_INBOX_ITEMS.map((i) => ({
                event_id: i.event_id,
                ticker: i.ticker,
                signal_state: i.signal_state,
                entry_type: i.entry_type,
                priority_score: i.priority_score,
                persistence_score: i.persistence_score,
                blocker_pressure_score: i.blocker_pressure_score,
                kill_rate_score: i.kill_rate_score,
                user_status: i.user_status,
                observed_at: i.observed_at,
                advisory_status: i.advisory_status,
                ai_execution_count: i.ai_execution_count,
              })),
            },
          ]}
        />

        <ExportGroup
          title="Manual Trade Log"
          description={`${MOCK_MANUAL_TRADES.length} manually logged trades (HUMAN_ONLY)`}
          exports={[
            {
              label: 'Export Trade Log',
              filename: 'manual_trade_log',
              format: 'json' as const,
              getData: () => MOCK_MANUAL_TRADES,
            },
            {
              label: 'Export Trade Log',
              filename: 'manual_trade_log',
              format: 'csv' as const,
              getData: () => MOCK_MANUAL_TRADES.map((t) => ({
                trade_id: t.trade_id,
                event_id: t.event_id,
                ticker: t.ticker,
                side: t.side,
                quantity: t.quantity,
                price: t.price,
                executed_at: t.executed_at,
                thesis: t.thesis,
                broker_order_id: t.broker_order_id,
                broker_api_called: t.broker_api_called,
                ai_execution_count: t.ai_execution_count,
              })),
            },
          ]}
        />

        <ExportGroup
          title="Reconciliations"
          description={`${MOCK_RECONCILIATIONS.length} trade reconciliation records`}
          exports={[
            {
              label: 'Export Reconciliations',
              filename: 'reconciliations',
              format: 'json' as const,
              getData: () => MOCK_RECONCILIATIONS,
            },
            {
              label: 'Export Reconciliations',
              filename: 'reconciliations',
              format: 'csv' as const,
              getData: () => MOCK_RECONCILIATIONS.map((r) => ({
                reconciliation_id: r.reconciliation_id,
                trade_id: r.trade_id,
                event_id: r.event_id,
                reconciled_at: r.reconciled_at,
                actual_fill_price: r.actual_fill_price,
                actual_quantity: r.actual_quantity,
                pnl_estimate: r.pnl_estimate,
                outcome_status: r.outcome_status,
                outcome_notes: r.outcome_notes,
                ai_execution_count: r.ai_execution_count,
              })),
            },
          ]}
        />

        <ExportGroup
          title="Moltbook"
          description={`${MOCK_MOLTBOOK_ENTRIES.length} self-correction learning entries`}
          exports={[
            {
              label: 'Export Moltbook',
              filename: 'moltbook_entries',
              format: 'json' as const,
              getData: () => MOCK_MOLTBOOK_ENTRIES,
            },
            {
              label: 'Export Moltbook',
              filename: 'moltbook_entries',
              format: 'csv' as const,
              getData: () => MOCK_MOLTBOOK_ENTRIES.map((e) => ({
                entry_id: e.entry_id,
                ticker: e.ticker,
                mistake_type: e.mistake_type,
                lesson_learned: e.lesson_learned,
                bias_detected: e.bias_detected,
                logged_at: e.logged_at,
              })),
            },
          ]}
        />
      </div>
    </div>
  );
}

interface ExportItem {
  label: string;
  filename: string;
  format: 'json' | 'csv';
  getData: () => unknown;
}

function ExportGroup({ title, description, exports }: { title: string; description: string; exports: ExportItem[] }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-slate-300">{title}</h2>
        <p className="text-xs text-slate-500 mt-0.5">{description}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {exports.map((ex) => (
          <ExportButton
            key={`${ex.filename}-${ex.format}`}
            label={ex.label}
            filename={ex.filename}
            getData={ex.getData}
            format={ex.format}
          />
        ))}
      </div>
    </div>
  );
}
