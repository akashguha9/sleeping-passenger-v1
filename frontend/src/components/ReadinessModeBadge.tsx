import { interpretReadiness, type RealMoneyReadiness } from '@/lib/realMoneyReadiness';

interface Props {
  readiness: RealMoneyReadiness | null | undefined;
}

const TONE_STYLE: Record<string, { color: string; border: string; bg: string }> = {
  danger: { color: '#f87171', border: 'rgba(248,113,113,0.4)', bg: 'rgba(248,113,113,0.08)' },
  caution: { color: '#fbbf24', border: 'rgba(251,191,36,0.4)', bg: 'rgba(251,191,36,0.08)' },
  info: { color: '#60a5fa', border: 'rgba(96,165,250,0.4)', bg: 'rgba(96,165,250,0.08)' },
  ok: { color: '#34d399', border: 'rgba(52,211,153,0.4)', bg: 'rgba(52,211,153,0.08)' },
};

/**
 * Shows the manual real-money readiness MODE in plain language. Advisory-only:
 * no execution buttons, no buy/sell wording.
 */
export function ReadinessModeBadge({ readiness }: Props) {
  const view = interpretReadiness(readiness);
  const style = TONE_STYLE[view.tone] ?? TONE_STYLE.danger;
  return (
    <div
      data-testid="readiness-mode-badge"
      data-allowed-mode={view.mode}
      data-advisory-only="true"
      data-execution-permission="false"
      className="rounded-lg px-4 py-3 text-xs font-mono"
      style={{ color: style.color, border: `1px solid ${style.border}`, background: style.bg }}
    >
      <div className="flex items-center gap-3">
        <span className="font-semibold uppercase tracking-widest">
          Real-money readiness: {view.label}
        </span>
        {view.score !== null && (
          <span className="opacity-80">score {view.score}/7</span>
        )}
      </div>
      <p className="mt-1 leading-snug opacity-90">{view.plain}</p>
    </div>
  );
}
