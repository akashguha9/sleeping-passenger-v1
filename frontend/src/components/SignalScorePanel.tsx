import type { InboxItem } from '@/types';

interface Props {
  signal: InboxItem;
}

export function SignalScorePanel({ signal }: Props) {
  const scores = [
    { label: 'Priority Score', value: signal.priority_score, invert: false },
    { label: 'Persistence Score', value: signal.persistence_score, invert: false },
    { label: 'Blocker Pressure', value: signal.blocker_pressure_score, invert: true },
    { label: 'Kill Rate', value: signal.kill_rate_score, invert: true },
  ];

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-4">Score Panel</h3>
      <div className="space-y-4">
        {scores.map(({ label, value, invert }) => {
          const pct = Math.round(value * 100);
          const color = invert
            ? value > 0.6 ? 'bg-red-500' : value > 0.3 ? 'bg-yellow-500' : 'bg-emerald-500'
            : value > 0.7 ? 'bg-emerald-500' : value > 0.4 ? 'bg-yellow-500' : 'bg-red-500';
          return (
            <div key={label}>
              <div className="flex justify-between text-xs mb-1.5">
                <span className="text-slate-400">{label}</span>
                <span className="text-white font-mono font-semibold">{value.toFixed(3)}</span>
              </div>
              <div className="h-2 rounded-full bg-slate-700">
                <div className={`h-2 rounded-full ${color} score-bar transition-all`} style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>

      {signal.blocker_attribution !== 'NONE' && (
        <div className="mt-4 p-3 rounded bg-slate-900/60 border border-slate-700/40">
          <div className="text-xs text-slate-500 mb-1">Active Blocker</div>
          <div className="text-sm font-mono text-red-400">{signal.blocker_attribution}</div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="p-2 rounded bg-slate-900/40 border border-slate-700/30">
          <span className="text-slate-500 block mb-0.5">Entry Type</span>
          <span className="text-slate-200 font-mono">{signal.entry_type}</span>
        </div>
        <div className="p-2 rounded bg-slate-900/40 border border-slate-700/30">
          <span className="text-slate-500 block mb-0.5">AI Executions</span>
          <span className="text-emerald-400 font-mono font-bold">0</span>
        </div>
      </div>
    </div>
  );
}
