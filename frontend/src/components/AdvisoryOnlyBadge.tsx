interface Props {
  size?: 'sm' | 'md';
}

export function AdvisoryOnlyBadge({ size = 'sm' }: Props) {
  const cls = size === 'md' ? 'px-2.5 py-1' : 'px-1.5 py-0.5';
  return (
    <span
      className={`${cls} inline-flex items-center gap-1.5 rounded-full text-[10px] font-mono font-medium uppercase tracking-widest`}
      style={{
        color: 'var(--sp-gold)',
        border: '1px solid rgba(200, 154, 74, 0.32)',
        background: 'rgba(200, 154, 74, 0.06)',
      }}
    >
      Advisory_Only
    </span>
  );
}
