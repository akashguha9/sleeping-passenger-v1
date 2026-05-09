export function NoExecutionBanner() {
  return (
    <div className="bg-slate-900 border-b border-amber-900/40 px-6 py-2 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className="text-amber-400 text-sm font-semibold">⚠ ADVISORY SYSTEM</span>
        <span className="text-slate-400 text-xs">
          This system does not place trades. All outputs are advisory only. Human decision and manual logging required.
        </span>
      </div>
      <div className="flex items-center gap-4 shrink-0">
        <span className="text-xs font-mono text-slate-500">
          AI executions: <span className="text-emerald-400 font-bold">0</span>
        </span>
        <span className="px-2 py-0.5 text-xs rounded border border-amber-800 text-amber-400 font-mono">
          EXECUTION_GATE: LOCKED
        </span>
      </div>
    </div>
  );
}
