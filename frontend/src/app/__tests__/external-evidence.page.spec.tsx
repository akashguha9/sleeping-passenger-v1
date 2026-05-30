/**
 * Vitest spec for the External Evidence Reliability operator page.
 *
 * Pins the Kanté continuation Workstream B contract:
 *   * The ExternalEvidenceReliabilityCard is actually mounted (no longer
 *     orphaned).
 *   * The page-level safety banner is always visible.
 *   * The disabled-state response renders honestly (no decision impact).
 *   * A paper-calibrated response renders per-source reliability.
 *   * No action / trade buttons exist on the page.
 *   * No forbidden execution language appears in any rendered copy.
 */
// @ts-ignore
import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

import ExternalEvidencePage from '@/app/external-evidence/page';

const FORBIDDEN = [
  /place order/,
  /execute trade/,
  /auto[- ]trade/,
  /broker (api|order|connected)/,
  /buy now/,
  /sell now/,
];

function stubFetch(body: Record<string, unknown>) {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response);
  // @ts-ignore
  globalThis.fetch = spy;
  return spy;
}

function disabledResponse() {
  return {
    status: 'DISABLED',
    mode: 'PAPER_ONLY',
    decision_impact: 'NONE',
    real_money_sizing_impact: 'PROHIBITED',
    real_money_weight_allowed: false,
    human_execution_required: true,
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    external_evidence_status: 'DISABLED',
    external_evidence_enabled: false,
    external_evidence_items: [],
  };
}

function paperCalibratedResponse() {
  return {
    status: 'OK',
    mode: 'PAPER_ONLY',
    decision_impact: 'ADVISORY_CONTEXT_ONLY',
    real_money_sizing_impact: 'PROHIBITED',
    real_money_weight_allowed: false,
    human_execution_required: true,
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    external_evidence_status: 'ACCEPTED_EVIDENCE_ONLY',
    external_evidence_enabled: true,
    external_evidence_decision_impact: 'ADVISORY_CONTEXT_ONLY',
    external_evidence_accepted_count: 1,
    external_evidence_score_delta_raw_uncalibrated: 0.2,
    external_evidence_score_delta_paper_calibrated: 0.05,
    external_evidence_calibration: {
      enabled: true,
      applied_to_score_delta: true,
      mode: 'PAPER_ONLY',
      calibrated_items_count: 1,
      cold_start_items_count: 1,
      mature_items_count: 0,
      real_money_sizing_impact: 'PROHIBITED',
    },
    external_evidence_items: [
      {
        source_name: 'kronos',
        evidence_type: 'CANDLESTICK_FORECAST',
        route_decision: 'WATCH',
        calibration_sample_count: 2,
        calibration_reliability_label: 'COLD_START',
        calibration_operator_message: 'Too few outcomes. Reliability discounted.',
      },
    ],
  };
}

describe('ExternalEvidencePage', () => {
  beforeEach(() => {
    // @ts-ignore
    globalThis.fetch = undefined;
  });

  it('mounts the reliability card', async () => {
    stubFetch(disabledResponse());
    render(<ExternalEvidencePage />);
    const card = await screen.findByTestId('external-evidence-reliability-card');
    expect(card).toBeTruthy();
  });

  it('always shows the page-level safety banner', async () => {
    stubFetch(disabledResponse());
    render(<ExternalEvidencePage />);
    const banner = await screen.findByTestId('external-evidence-safety-banner');
    const text = banner.textContent ?? '';
    expect(text).toMatch(/Paper-only reliability/i);
    expect(text).toMatch(/Real-money sizing prohibited/i);
    expect(text).toMatch(/No broker action/i);
  });

  it('renders the disabled state honestly', async () => {
    stubFetch(disabledResponse());
    render(<ExternalEvidencePage />);
    const card = await screen.findByTestId('external-evidence-reliability-card');
    expect(card.getAttribute('data-reliability-state')).toBe('disabled');
    expect(screen.getByTestId('reliability-disabled').textContent).toMatch(
      /No decision impact/,
    );
  });

  it('renders the paper-calibrated state with per-source reliability', async () => {
    stubFetch(paperCalibratedResponse());
    render(<ExternalEvidencePage />);
    const card = await screen.findByTestId('external-evidence-reliability-card');
    await waitFor(() =>
      expect(card.getAttribute('data-reliability-state')).toBe('paper-calibrated'),
    );
    expect(card.getAttribute('data-real-money-sizing')).toBe('PROHIBITED');
    expect(screen.getAllByTestId('reliability-source').length).toBeGreaterThan(0);
  });

  it('has no action / trade buttons', async () => {
    stubFetch(paperCalibratedResponse());
    const { container } = render(<ExternalEvidencePage />);
    await screen.findByTestId('external-evidence-reliability-card');
    expect(container.querySelectorAll('button').length).toBe(0);
    expect(container.querySelectorAll('a[href^="/trade"]').length).toBe(0);
  });

  it('never emits forbidden execution language', async () => {
    stubFetch(paperCalibratedResponse());
    const { container } = render(<ExternalEvidencePage />);
    await screen.findByTestId('external-evidence-reliability-card');
    const blob = (container.textContent ?? '').toLowerCase();
    for (const pattern of FORBIDDEN) {
      expect(blob).not.toMatch(pattern);
    }
  });
});
