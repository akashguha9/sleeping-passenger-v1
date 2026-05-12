export function NoExecutionBanner() {
  return (
    <div
      className="px-8 py-2 flex items-center justify-between gap-4"
      style={{
        background: 'rgba(13, 16, 21, 0.7)',
        borderBottom: '1px solid var(--sp-line)',
      }}
    >
      <div className="flex items-center gap-3">
        <span
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-gold)' }}
        >
          Advisory System
        </span>
        <span className="text-xs" style={{ color: 'var(--sp-mist)' }}>
          This system does not place trades. All outputs advisory only — human decision and manual logging required.
        </span>
      </div>
      <div className="flex items-center gap-4 shrink-0">
        <span className="text-xs font-mono" style={{ color: 'var(--sp-mist)' }}>
          AI executions:{' '}
          <span className="font-bold" style={{ color: 'var(--sp-cyan)' }}>0</span>
        </span>
        <span className="sp-chip sp-chip-rust">
          Execution_Gate · Locked
        </span>
      </div>
    </div>
  );
}
