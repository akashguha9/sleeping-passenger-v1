import { interpretCalibration, type ScoreCalibration } from '@/lib/scoreCalibration';

interface Props {
  calibration: ScoreCalibration | null | undefined;
}

const TONE_STYLE: Record<string, { color: string; border: string; bg: string }> = {
  danger: { color: '#f87171', border: 'rgba(248,113,113,0.4)', bg: 'rgba(248,113,113,0.08)' },
  caution: { color: '#fbbf24', border: 'rgba(251,191,36,0.4)', bg: 'rgba(251,191,36,0.08)' },
  info: { color: '#60a5fa', border: 'rgba(96,165,250,0.4)', bg: 'rgba(96,165,250,0.08)' },
  ok: { color: '#34d399', border: 'rgba(52,211,153,0.4)', bg: 'rgba(52,211,153,0.08)' },
};

/**
 * Renders the honest calibration status next to the signal scores so a
 * precise-looking number is never shown as if it were validated. Advisory
 * wording only — no execution language, no sizing instruction.
 */
export function ScoreCalibrationBadge({ calibration }: Props) {
  const view = interpretCalibration(calibration);
  const style = TONE_STYLE[view.tone] ?? TONE_STYLE.danger;
  return (
    <div
      data-testid="score-calibration-badge"
      data-calibration-status={view.status}
      data-should-drive-sizing={view.shouldDriveSizing ? 'true' : 'false'}
      data-advisory-only="true"
      data-execution-permission="false"
      className="rounded-md px-2.5 py-1.5 text-[11px] font-mono"
      style={{ color: style.color, border: `1px solid ${style.border}`, background: style.bg }}
    >
      <span className="font-semibold uppercase tracking-widest">
        Score calibration: {view.label}
      </span>
      {typeof calibration?.sample_size === 'number' && (
        <span className="ml-2 opacity-80">n={calibration.sample_size}</span>
      )}
      {!view.shouldDriveSizing && (
        <span className="ml-2 font-semibold">· Do not size from this score</span>
      )}
      <p className="mt-1 leading-snug opacity-90">{view.warning}</p>
    </div>
  );
}
