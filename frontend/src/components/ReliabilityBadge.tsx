import { interpretCalibrationMap, type CalibrationMap } from '@/lib/calibrationMap';

interface Props {
  map: CalibrationMap | null | undefined;
}

const TONE_STYLE: Record<string, { color: string; border: string; bg: string }> = {
  ok: { color: '#34d399', border: 'rgba(52,211,153,0.4)', bg: 'rgba(52,211,153,0.08)' },
  info: { color: '#60a5fa', border: 'rgba(96,165,250,0.4)', bg: 'rgba(96,165,250,0.08)' },
};

/**
 * Shows whether the raw scores can be recalibrated into honest probabilities,
 * and by how much out-of-sample ECE improves. Advisory-only — no sizing, no
 * execution language.
 */
export function ReliabilityBadge({ map }: Props) {
  const view = interpretCalibrationMap(map);
  const style = TONE_STYLE[view.tone] ?? TONE_STYLE.info;
  return (
    <div
      data-testid="reliability-badge"
      data-recalibration-improved={view.improved ? 'true' : 'false'}
      data-advisory-only="true"
      data-execution-permission="false"
      className="rounded-lg px-4 py-3 text-xs font-mono"
      style={{ color: style.color, border: `1px solid ${style.border}`, background: style.bg }}
    >
      <div className="flex items-center gap-3">
        <span className="font-semibold uppercase tracking-widest">
          Score recalibration: {view.improved ? view.method : 'none'}
        </span>
        {view.eceImprovementPct !== null && view.improved && (
          <span className="opacity-80">OOS ECE −{view.eceImprovementPct.toFixed(0)}%</span>
        )}
      </div>
      <p className="mt-1 leading-snug opacity-90">{view.plain}</p>
    </div>
  );
}
