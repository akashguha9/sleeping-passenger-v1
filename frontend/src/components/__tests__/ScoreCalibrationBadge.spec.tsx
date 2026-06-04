/**
 * Vitest spec for ScoreCalibrationBadge.
 *
 * The badge must prevent false confidence: render the calibration status,
 * tell the operator NOT to size from an uncalibrated/low-sample score, carry
 * advisory data attributes, and never emit execution language.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { ScoreCalibrationBadge } from '@/components/ScoreCalibrationBadge';
import { interpretCalibration } from '@/lib/scoreCalibration';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

describe('interpretCalibration', () => {
  it('treats missing/unknown status as UNCALIBRATED, no sizing', () => {
    const v = interpretCalibration(undefined);
    expect(v.status).toBe('UNCALIBRATED');
    expect(v.shouldDriveSizing).toBe(false);
  });

  it('only drives sizing when CALIBRATED and backend agrees', () => {
    expect(
      interpretCalibration({ calibration_status: 'CALIBRATED', score_should_drive_sizing: true })
        .shouldDriveSizing,
    ).toBe(true);
    // CALIBRATED but backend withholds permission -> still no sizing
    expect(
      interpretCalibration({ calibration_status: 'CALIBRATED', score_should_drive_sizing: false })
        .shouldDriveSizing,
    ).toBe(false);
    // CALIBRATING never drives sizing
    expect(
      interpretCalibration({ calibration_status: 'CALIBRATING', score_should_drive_sizing: true })
        .shouldDriveSizing,
    ).toBe(false);
  });
});

describe('ScoreCalibrationBadge', () => {
  it('renders uncalibrated warning and do-not-size copy', () => {
    render(<ScoreCalibrationBadge calibration={{ calibration_status: 'UNCALIBRATED', sample_size: 0 }} />);
    const el = screen.getByTestId('score-calibration-badge');
    expect(el.getAttribute('data-calibration-status')).toBe('UNCALIBRATED');
    expect(el.getAttribute('data-should-drive-sizing')).toBe('false');
    expect(el.getAttribute('data-advisory-only')).toBe('true');
    expect(el.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getAllByText(/Do not size from this score/i).length).toBeGreaterThan(0);
  });

  it('does not show the do-not-size pill when calibrated and permitted', () => {
    render(
      <ScoreCalibrationBadge
        calibration={{ calibration_status: 'CALIBRATED', sample_size: 60, score_should_drive_sizing: true }}
      />,
    );
    const el = screen.getByTestId('score-calibration-badge');
    expect(el.getAttribute('data-should-drive-sizing')).toBe('true');
    expect(screen.queryByText(/Do not size from this score/i)).toBeNull();
  });

  it('never emits execution / broker language', () => {
    const { container } = render(
      <ScoreCalibrationBadge calibration={{ calibration_status: 'LOW_SAMPLE', sample_size: 4 }} />,
    );
    const text = container.textContent ?? '';
    expect(/buy|sell|execute|broker|order/i.test(text)).toBe(false);
  });
});
