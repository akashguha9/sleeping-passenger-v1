'use client';

import { ACTION_BADGE_CLASS, type NextHumanAction } from '@/lib/nextHumanAction';

interface Props {
  action: NextHumanAction;
  label: string;
  size?: 'sm' | 'md';
}

export function NextHumanActionBadge({ action, label, size = 'sm' }: Props) {
  const cls = ACTION_BADGE_CLASS[action];
  const padding = size === 'md' ? 'px-2.5 py-1 text-xs' : 'px-2 py-0.5 text-[10px]';
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border font-mono font-semibold uppercase tracking-wide ${padding} ${cls}`}
      title="Advisory-only next human action — does not authorize execution"
    >
      <span aria-hidden className="opacity-70">›</span>
      {label}
    </span>
  );
}
