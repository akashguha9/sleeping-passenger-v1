/**
 * Vitest spec for the Intelligence Loop page.
 *
 * Covers the loading lifecycle, the Empirical Readiness vs Empirical Score
 * honesty distinction, the shadow-run flow, and the no-execution contract.
 */
// @ts-ignore
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { vi } from 'vitest';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

vi.mock('@/lib/apiClient', () => ({
  getEurekaHealth: vi.fn(),
  getDecisionTwins: vi.fn(),
  postDailyShadowRun: vi.fn(),
}));

import { getEurekaHealth, getDecisionTwins, postDailyShadowRun } from '@/lib/apiClient';
import IntelligencePage from '@/app/intelligence/page';

const mockHealth = getEurekaHealth as unknown as ReturnType<typeof vi.fn>;
const mockTwins = getDecisionTwins as unknown as ReturnType<typeof vi.fn>;
const mockRun = postDailyShadowRun as unknown as ReturnType<typeof vi.fn>;

const STAMPS = {
  advisory_status: 'ADVISORY_ONLY', execution_gate: 'LOCKED', ai_execution_count: 0,
  broker_api_called: false, human_review_required: true,
};

const HEALTH = {
  ...STAMPS, twins_frozen: 3, predictions_resolved: 0, mean_brier: null,
  empirical_readiness_score: 9.0, empirical_score: 1.0,
  empirical_note: 'Readiness and Score are separate.', loop_closed: true,
};

const TWINS = { ...STAMPS, count: 0, twins: [] };

const RUN = {
  ...STAMPS, ok: true, mode: 'shadow', session_date: '2026-07-15',
  candidates_considered: 3, rejected_cheaply: 1, analysed: 2, twins_created: 2,
  predictions_frozen: 10, outcome_jobs_registered: 10,
  attention_queue: [
    { candidate: 'RELIANCE.NS', advisory_state: 'AVOID', priority: 0.5, depth: 'DEEP', regime: 'LOW|SIDEWAYS|DEEP|FRESH', process_quality: 9.6 },
  ],
  top_research_actions: [{ candidate: 'RELIANCE.NS', action: 'sector_data', net_voi: 0.23 }],
  no_research_needed: [], human_action_required: false, persisted: true,
};

describe('IntelligencePage', () => {
  beforeEach(() => {
    mockHealth.mockReset();
    mockTwins.mockReset();
    mockRun.mockReset();
  });

  it('resolves out of loading and shows the readiness-vs-score distinction', async () => {
    mockHealth.mockResolvedValue(HEALTH);
    mockTwins.mockResolvedValue(TWINS);

    render(<IntelligencePage />);
    await waitFor(() => expect(screen.queryByTestId('intel-loading')).toBeNull());
    const health = screen.getByTestId('eureka-health');
    const text = health.textContent || '';
    expect(text).toContain('9'); // empirical readiness
    expect(text).toContain('1'); // empirical score stays low
  });

  it('runs a shadow day and renders the attention queue without execution language', async () => {
    mockHealth.mockResolvedValue(HEALTH);
    mockTwins.mockResolvedValue(TWINS);
    mockRun.mockResolvedValue(RUN);

    const { container } = render(<IntelligencePage />);
    await waitFor(() => expect(screen.queryByTestId('intel-loading')).toBeNull());
    fireEvent.click(screen.getByTestId('run-shadow'));
    await waitFor(() => expect(screen.getByTestId('shadow-result')).toBeTruthy());

    expect(container.querySelector('[data-execution-permission="false"]')).toBeTruthy();
    const body = container.textContent || '';
    expect(/trade now|place order|execute order|auto-buy|auto-sell|broker trade/i.test(body)).toBe(false);
  });

  it('falls back to a finite offline state when the backend is null', async () => {
    mockHealth.mockResolvedValue(null);
    mockTwins.mockResolvedValue(null);

    render(<IntelligencePage />);
    await waitFor(() => expect(screen.queryByTestId('intel-loading')).toBeNull());
    expect(screen.getByText(/BACKEND OFFLINE/i)).toBeTruthy();
  });
});
