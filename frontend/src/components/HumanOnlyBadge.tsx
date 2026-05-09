interface Props {
  size?: 'sm' | 'md';
}

export function HumanOnlyBadge({ size = 'sm' }: Props) {
  const cls = size === 'md'
    ? 'px-2.5 py-1 text-xs'
    : 'px-1.5 py-0.5 text-xs';
  return (
    <span className={`${cls} rounded border border-sky-800/60 bg-sky-950/40 text-sky-400 font-mono font-medium uppercase tracking-wide`}>
      HUMAN_ONLY
    </span>
  );
}
