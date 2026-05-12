interface Props {
  size?: 'sm' | 'md';
}

export function HumanOnlyBadge({ size = 'sm' }: Props) {
  const cls = size === 'md' ? 'px-2.5 py-1' : 'px-1.5 py-0.5';
  return (
    <span
      className={`${cls} inline-flex items-center gap-1.5 rounded-full text-[10px] font-mono font-medium uppercase tracking-widest`}
      style={{
        color: 'var(--sp-cyan)',
        border: '1px solid rgba(95, 189, 200, 0.28)',
        background: 'rgba(95, 189, 200, 0.05)',
      }}
    >
      Human_Only
    </span>
  );
}
