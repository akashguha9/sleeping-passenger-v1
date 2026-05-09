import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

const SYSTEM_CONSTANTS = [
  { key: 'advisory_status', value: 'ADVISORY_ONLY', color: 'text-amber-400' },
  { key: 'execution_mode', value: 'HUMAN_ONLY', color: 'text-sky-400' },
  { key: 'ai_execution_count', value: '0 (immutable)', color: 'text-emerald-400' },
  { key: 'execution_gate', value: 'LOCKED', color: 'text-red-400' },
  { key: 'broker_api_called', value: 'false (immutable)', color: 'text-emerald-400' },
  { key: 'broker_order_id', value: 'NONE', color: 'text-slate-400' },
];

export default function SettingsPage() {
  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Settings</h1>
          <p className="text-sm text-slate-500 mt-0.5">System configuration and safety constants</p>
        </div>
        <div className="flex gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      {/* Safety constants (read-only) */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-1">Safety Constants</h2>
        <p className="text-xs text-slate-500 mb-4">These values are immutable and enforced at the API layer. They cannot be changed from this UI.</p>
        <div className="space-y-2">
          {SYSTEM_CONSTANTS.map((c) => (
            <div key={c.key} className="flex items-center justify-between px-3 py-2.5 rounded bg-slate-900/60 border border-slate-700/40">
              <span className="text-xs font-mono text-slate-400">{c.key}</span>
              <span className={`text-xs font-mono font-semibold ${c.color}`}>{c.value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* System info */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-4">System Information</h2>
        <div className="space-y-3 text-sm">
          <InfoRow label="System" value="Signal Intelligence Cockpit v5.7" />
          <InfoRow label="Backend" value="FastAPI — pipeline-v5.7-core" />
          <InfoRow label="Data mode" value="Mock data (Step 1 scaffold)" />
          <InfoRow label="API connection" value="Not connected (Step 2)" />
          <InfoRow label="Broker connection" value="None — not applicable" />
          <InfoRow label="Auto-execution" value="Disabled permanently" />
        </div>
      </div>

      {/* What this system does NOT do */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">What This System Does NOT Do</h2>
        <ul className="space-y-2 text-xs text-slate-400">
          {[
            'Place buy or sell orders on any exchange or broker',
            'Connect to any broker API',
            'Execute trades automatically or semi-automatically',
            'Increment AI execution count above 0',
            'Store API keys or broker credentials',
            'Modify execution policy or governance rules',
            'Send orders, routes, or signals to any external system',
          ].map((item) => (
            <li key={item} className="flex items-start gap-2">
              <span className="text-red-500 shrink-0 mt-0.5">✕</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* What it does do */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">What This System Does</h2>
        <ul className="space-y-2 text-xs text-slate-400">
          {[
            'Display advisory signal intelligence for human review',
            'Allow humans to log trades they have already placed manually',
            'Maintain a self-correction and learning log (Moltbook)',
            'Export advisory data as JSON or CSV for offline analysis',
            'Track human reflections and AI discussion context per signal',
            'Reconcile manually logged trades with actual outcomes',
          ].map((item) => (
            <li key={item} className="flex items-start gap-2">
              <span className="text-emerald-500 shrink-0 mt-0.5">✓</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-slate-700/40 pb-2">
      <span className="text-slate-500 text-xs">{label}</span>
      <span className="text-slate-200 text-xs font-mono">{value}</span>
    </div>
  );
}
