interface Props {
  size?: 'sm' | 'md';
}

export function AdvisoryOnlyBadge({ size = 'sm' }: Props) {
  const cls = size === 'md'
    ? 'px-2.5 py-1 text-xs'
    : 'px-1.5 py-0.5 text-xs';
  return (
    <span className={`${cls} rounded border border-amber-800/60 bg-amber-950/40 text-amber-400 font-mono font-medium uppercase tracking-wide`}>
      ADVISORY_ONLY
    </span>
  );
}
