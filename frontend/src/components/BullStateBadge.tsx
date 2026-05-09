const STATE_CONFIG: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  'HURACÁN':    { bg: 'bg-emerald-950/50', border: 'border-emerald-700/60', text: 'text-emerald-400', dot: 'bg-emerald-400' },
  'AVENTADOR':  { bg: 'bg-orange-950/50',  border: 'border-orange-700/60',  text: 'text-orange-400',  dot: 'bg-orange-400' },
  'MURCIÉLAGO': { bg: 'bg-purple-950/50',  border: 'border-purple-700/60',  text: 'text-purple-400',  dot: 'bg-purple-400' },
  'DIABLO':     { bg: 'bg-red-950/50',     border: 'border-red-700/60',     text: 'text-red-400',     dot: 'bg-red-400' },
  'GALLARDO':   { bg: 'bg-teal-950/50',    border: 'border-teal-700/60',    text: 'text-teal-400',    dot: 'bg-teal-400' },
  'ISLERO':     { bg: 'bg-yellow-950/50',  border: 'border-yellow-700/60',  text: 'text-yellow-400',  dot: 'bg-yellow-400' },
  'MIURA':      { bg: 'bg-slate-800/50',   border: 'border-slate-600/60',   text: 'text-slate-400',   dot: 'bg-slate-400' },
  'UNKNOWN':    { bg: 'bg-slate-800/50',   border: 'border-slate-600/60',   text: 'text-slate-500',   dot: 'bg-slate-500' },
};

const DEFAULT_CONFIG = STATE_CONFIG['UNKNOWN'];

interface Props {
  state: string;
  size?: 'sm' | 'md' | 'lg';
}

export function BullStateBadge({ state, size = 'sm' }: Props) {
  const cfg = STATE_CONFIG[state] ?? DEFAULT_CONFIG;
  const cls = size === 'lg'
    ? 'px-3 py-1.5 text-sm gap-2'
    : size === 'md'
    ? 'px-2.5 py-1 text-xs gap-1.5'
    : 'px-1.5 py-0.5 text-xs gap-1';

  return (
    <span className={`inline-flex items-center ${cls} rounded border ${cfg.bg} ${cfg.border} ${cfg.text} font-mono font-semibold`}>
      <span className={`${size === 'lg' ? 'w-2 h-2' : 'w-1.5 h-1.5'} rounded-full ${cfg.dot} shrink-0`} />
      {state}
    </span>
  );
}
