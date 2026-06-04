/**
 * Vitest spec for ReliabilityBadge + interpretCalibrationMap.
 * Advisory-only: shows recalibration status, never execution/sizing language.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { ReliabilityBadge } from '@/components/ReliabilityBadge';
import { interpretCalibrationMap } from '@/lib/calibrationMap';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

describe('interpretCalibrationMap', () => {
  it('reports no improvement for identity / missing', () => {
    expect(interpretCalibrationMap(undefined).improved).toBe(false);
    expect(interpretCalibrationMap({ method: 'identity', improved_out_of_sample: false }).improved).toBe(false);
  });

  it('computes ECE improvement percent', () => {
    const v = interpretCalibrationMap({
      method: 'isotonic', improved_out_of_sample: true,
      raw_test_ece: 0.4, cal_test_ece: 0.1,
    });
    expect(v.improved).toBe(true);
    expect(Math.round(v.eceImprovementPct ?? 0)).toBe(75);
  });
});

describe('ReliabilityBadge', () => {
  it('renders improved recalibration with advisory wording', () => {
    render(<ReliabilityBadge map={{ method: 'platt', improved_out_of_sample: true, raw_test_ece: 0.3, cal_test_ece: 0.15 }} />);
    const el = screen.getByTestId('reliability-badge');
    expect(el.getAttribute('data-recalibration-improved')).toBe('true');
    expect(el.getAttribute('data-advisory-only')).toBe('true');
    expect(el.getAttribute('data-execution-permission')).toBe('false');
    expect(/do not enable sizing/i.test(el.textContent ?? '')).toBe(true);
  });

  it('never emits execution language', () => {
    const { container } = render(<ReliabilityBadge map={{ method: 'identity', improved_out_of_sample: false }} />);
    expect(/\b(buy|sell|execute|broker|order)\b/i.test(container.textContent ?? '')).toBe(false);
  });
});
