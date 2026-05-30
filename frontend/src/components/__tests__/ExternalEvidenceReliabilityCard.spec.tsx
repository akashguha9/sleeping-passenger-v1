/**
 * Vitest spec for the External Evidence Reliability card.
 *
 * The card is advisory-only / paper-only and must:
 *   * render the disabled state safely ("No decision impact."),
 *   * render the paper-calibrated state with per-source reliability,
 *   * always state real-money sizing is PROHIBITED,
 *   * surface COLD_START / EARLY_SAMPLE / PROVISIONAL / MATURE_PAPER_ONLY labels,
 *   * never emit execution language (place order / execute trade / auto trade /
 *     broker connected / buy now / sell now).
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import {
  ExternalEvidenceReliabilityCard,
  ExternalEvidenceReliabilityView,
} from '@/components/ExternalEvidenceReliabilityCard';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const FORBIDDEN = [
  /place order/,
  /execute trade/,
  /auto[- ]trade/,
  /broker (api|order|connected)/,
  /buy now/,
  /sell now/,
  /enter now/,
  /exit now/,
  /ai executes/,
  /ai decides/,
  /guaranteed return/,
];

function paperCalibratedBundle(
  overrides: Partial<ExternalEvidenceReliabilityView> = {},
): ExternalEvidenceReliabilityView {
  return {
    external_evidence_status: 'ACCEPTED_EVIDENCE_ONLY',
    external_evidence_enabled: true,
    external_evidence_decision_impact: 'ADVISORY_CONTEXT_ONLY',
    external_evidence_accepted_count: 3,
    external_evidence_score_delta_raw_uncalibrated: 0.5,
    external_evidence_score_delta_paper_calibrated: 0.12,
    external_evidence_calibration: {
      enabled: true,
      applied_to_score_delta: true,
      mode: 'PAPER_ONLY',
      calibrated_items_count: 3,
      cold_start_items_count: 1,
      mature_items_count: 1,
      real_money_sizing_impact: 'PROHIBITED',
    },
    external_evidence_items: [
      {
        source_name: 'kronos',
        evidence_type: 'CANDLESTICK_FORECAST',
        route_decision: 'WATCH',
        calibration_confidence_band: 'MID',
        calibration_sample_count: 2,
        calibration_help_rate: 0.5,
        calibration_harm_rate: 0.1,
        calibration_false_confidence_rate: 0.0,
        calibration_advisory_weight: 0.25,
        calibration_effective_weight: 0.25,
        calibration_reliability_label: 'COLD_START',
        calibration_operator_message: 'Too few outcomes. Reliability heavily discounted.',
      },
      {
        source_name: 'agents',
        evidence_type: 'AGENT_COMMITTEE',
        route_decision: 'PAPER_TRADE',
        calibration_confidence_band: 'HIGH',
        calibration_sample_count: 35,
        calibration_help_rate: 0.7,
        calibration_harm_rate: 0.05,
        calibration_false_confidence_rate: 0.02,
        calibration_advisory_weight: 0.6,
        calibration_effective_weight: 0.55,
        calibration_reliability_label: 'PROVISIONAL',
        calibration_operator_message: 'Provisional reliability. Paper-only.',
      },
      {
        source_name: 'fincept',
        evidence_type: 'TERMINAL_ANALYTICS',
        route_decision: 'WATCH',
        calibration_confidence_band: 'HIGH',
        calibration_sample_count: 60,
        calibration_help_rate: 0.8,
        calibration_harm_rate: 0.02,
        calibration_false_confidence_rate: 0.01,
        calibration_advisory_weight: 0.85,
        calibration_effective_weight: 0.85,
        calibration_reliability_label: 'MATURE_PAPER_ONLY',
        calibration_operator_message: 'Mature sample, still paper-only. Real-money sizing prohibited.',
      },
    ],
    ...overrides,
  };
}

describe('ExternalEvidenceReliabilityCard', () => {
  // ----------------------------------------------------------------- test 16
  it('renders the disabled state safely with no decision impact', () => {
    const first = render(<ExternalEvidenceReliabilityCard bundle={null} />);
    const card = screen.getByTestId('external-evidence-reliability-card');
    expect(card.getAttribute('data-reliability-state')).toBe('disabled');
    expect(card.getAttribute('data-advisory-only')).toBe('true');
    expect(card.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getByTestId('reliability-disabled').textContent).toMatch(
      /External evidence disabled or unavailable\. No decision impact\./,
    );
    first.unmount();

    const disabledBundle: ExternalEvidenceReliabilityView = {
      external_evidence_status: 'DISABLED',
      external_evidence_enabled: false,
    };
    const { getByTestId } = render(
      <ExternalEvidenceReliabilityCard bundle={disabledBundle} />,
    );
    expect(getByTestId('reliability-disabled')).toBeTruthy();
  });

  // ----------------------------------------------------------------- test 17
  it('renders the paper-calibrated state with per-source reliability', () => {
    render(<ExternalEvidenceReliabilityCard bundle={paperCalibratedBundle()} />);
    const card = screen.getByTestId('external-evidence-reliability-card');
    expect(card.getAttribute('data-reliability-state')).toBe('paper-calibrated');
    expect(card.getAttribute('data-execution-gate')).toBe('LOCKED');
    expect(card.getAttribute('data-broker-api-called')).toBe('false');
    expect(screen.getByTestId('reliability-status-chip').textContent).toMatch(/Paper-calibrated/);
    expect(screen.getByTestId('reliability-delta-raw').textContent).toMatch(/\+0\.500/);
    expect(screen.getByTestId('reliability-delta-calibrated').textContent).toMatch(/\+0\.120/);
    expect(screen.getAllByTestId('reliability-source')).toHaveLength(3);
  });

  // ----------------------------------------------------------------- test 18
  it('always shows real-money sizing prohibited', () => {
    render(<ExternalEvidenceReliabilityCard bundle={paperCalibratedBundle()} />);
    const card = screen.getByTestId('external-evidence-reliability-card');
    expect(card.getAttribute('data-real-money-sizing')).toBe('PROHIBITED');
    expect(screen.getByTestId('reliability-real-money').textContent).toMatch(/PROHIBITED/);
    expect(screen.getByTestId('reliability-safety-banner').textContent).toMatch(
      /Real-money sizing prohibited\. No broker action\./,
    );
  });

  // ----------------------------------------------------------------- test 19
  it('shows cold-start / provisional / mature reliability labels', () => {
    render(<ExternalEvidenceReliabilityCard bundle={paperCalibratedBundle()} />);
    const labels = screen.getAllByTestId('reliability-source-label').map((n: any) => n.textContent);
    expect(labels.join(' | ')).toMatch(/Cold start/);
    expect(labels.join(' | ')).toMatch(/Provisional/);
    expect(labels.join(' | ')).toMatch(/Mature \(paper-only\)/);
  });

  // ----------------------------------------------------------------- test 20
  it('never emits forbidden execution language', () => {
    const { container } = render(
      <ExternalEvidenceReliabilityCard bundle={paperCalibratedBundle()} />,
    );
    const blob = (container.textContent ?? '').toLowerCase();
    for (const pattern of FORBIDDEN) {
      expect(blob).not.toMatch(pattern);
    }
  });

  it('shows calibration-unavailable copy when calibration is not applied', () => {
    const errorSafe = paperCalibratedBundle({
      external_evidence_status: 'ERROR_SAFE',
      external_evidence_calibration: {
        enabled: false,
        applied_to_score_delta: false,
        mode: 'PAPER_ONLY',
        real_money_sizing_impact: 'PROHIBITED',
      },
    });
    render(<ExternalEvidenceReliabilityCard bundle={errorSafe} />);
    expect(screen.getByTestId('reliability-calibration-unavailable').textContent).toMatch(
      /Calibration unavailable\. Conservative paper-only default applied\./,
    );
  });

  // --- Kanté Ceiling Push II (WS-D) -----------------------------------------
  function readinessBundle(
    overrides: Partial<ExternalEvidenceReliabilityView> = {},
  ): ExternalEvidenceReliabilityView {
    return paperCalibratedBundle({
      paper_outcome_readiness: {
        readiness_label: 'COLD_START',
        closed_paper_outcomes_count: 12,
        target_minimum: 50,
        target_preferred: 100,
        calibration_readiness_score: 0.05,
        next_required_action: 'Log closed paper outcomes: 12/30 to leave cold-start.',
      },
      calibration_corpus_quality: {
        corpus_quality_score: 0.18,
        corpus_label: 'WEAK',
        top_blocker: 'insufficient_outcome_volume',
        operator_next_action: 'Continue accumulating closed paper outcomes (12/100).',
        n_closed: 12,
      },
      live_verified_blockers: ['not_enabled', 'no_canonical_rows_written'],
      real_money_readiness_ceiling: 'LOW BY DESIGN',
      ...overrides,
    });
  }

  // ----------------------------------------------------------------- WS-D 1
  it('shows the paper-outcome readiness label and closed count', () => {
    render(<ExternalEvidenceReliabilityCard bundle={readinessBundle()} />);
    expect(screen.getByTestId('reliability-paper-outcome-readiness')).toBeTruthy();
    expect(screen.getByTestId('reliability-paper-outcome-label').textContent).toMatch(
      /COLD_START/,
    );
  });

  // ----------------------------------------------------------------- WS-D 2
  it('shows the 50 / 100 target progress', () => {
    render(<ExternalEvidenceReliabilityCard bundle={readinessBundle()} />);
    const progress = screen.getByTestId('reliability-paper-outcome-progress').textContent ?? '';
    expect(progress).toMatch(/12 \/ 50/);
    expect(progress).toMatch(/12 \/ 100/);
  });

  // ----------------------------------------------------------------- WS-D 3
  it('shows LOW BY DESIGN real-money readiness', () => {
    render(<ExternalEvidenceReliabilityCard bundle={readinessBundle()} />);
    expect(screen.getByTestId('reliability-real-money-readiness').textContent).toMatch(
      /LOW BY DESIGN/,
    );
    expect(screen.getByTestId('reliability-cold-start-message').textContent).toMatch(
      /Calibration cannot leave cold-start until enough closed paper outcomes exist\./,
    );
  });

  // ----------------------------------------------------------------- WS-D 4
  it('has no action buttons', () => {
    const { container } = render(
      <ExternalEvidenceReliabilityCard bundle={readinessBundle()} />,
    );
    expect(container.querySelectorAll('button').length).toBe(0);
    expect(container.querySelectorAll('a').length).toBe(0);
  });

  // ----------------------------------------------------------------- WS-D 5
  it('shows readiness honestly even in the disabled state', () => {
    const disabled: ExternalEvidenceReliabilityView = {
      external_evidence_status: 'DISABLED',
      external_evidence_enabled: false,
      paper_outcome_readiness: {
        readiness_label: 'COLD_START',
        closed_paper_outcomes_count: 0,
        target_minimum: 50,
        target_preferred: 100,
      },
      real_money_readiness_ceiling: 'LOW BY DESIGN',
    };
    render(<ExternalEvidenceReliabilityCard bundle={disabled} />);
    expect(screen.getByTestId('reliability-disabled')).toBeTruthy();
    expect(screen.getByTestId('reliability-real-money-readiness').textContent).toMatch(
      /LOW BY DESIGN/,
    );
  });
});
