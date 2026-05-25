/**
 * TopTruthBar spec — Identity Collapse sprint, Phase 4.
 *
 * Properties under test
 *   * Renders the MOCK MODE chip when backend is offline (apiClient returns null).
 *   * Renders the LIVE BACKEND chip when backend is reachable.
 *   * Always renders the "Advisory only · No execution" footer chip.
 *   * Never emits Buy / Sell / Execute / Place order copy.
 */
// @ts-ignore
import { render, screen, waitFor } from '@testing-library/react';
// @ts-ignore
import { vi } from 'vitest';
import { TopTruthBar } from '@/components/TopTruthBar';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

vi.mock('@/lib/apiClient', () => ({
  checkHealth: vi.fn(),
  getLiveSourcesStatus: vi.fn(),
  getWatchdogSummary: vi.fn(),
}));

import * as apiClient from '@/lib/apiClient';

function _statusResponse() {
  return {
    operation: 'live_sources_status',
    sources: {
      polymarket: { credential_configured: true, freshness_state: 'fresh' },
      gdelt: { credential_configured: true, freshness_state: 'stale' },
      sec_edgar: { credential_configured: false, freshness_state: 'skipped' },
    },
    source_count: 3,
    freshness_distribution: { fresh: 1, stale: 1, skipped: 1 },
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    execution_permission: false,
    can_execute: false,
    human_review_required: true,
  } as any;
}

describe('TopTruthBar', () => {
  it('renders MOCK MODE chip when backend is offline', async () => {
    (apiClient.checkHealth as any).mockResolvedValue(null);
    (apiClient.getLiveSourcesStatus as any).mockResolvedValue(null);
    (apiClient.getWatchdogSummary as any).mockResolvedValue(null);
    render(<TopTruthBar />);
    const chip = await screen.findByTestId('top-truth-bar-mock-chip');
    expect(chip.textContent).toMatch(/MOCK MODE/);
    expect(chip.textContent).toMatch(/Backend offline/);
  });

  it('renders LIVE BACKEND chip when backend is reachable', async () => {
    (apiClient.checkHealth as any).mockResolvedValue({
      status: 'ok',
      advisory_status: 'ADVISORY_ONLY',
      execution_mode: 'HUMAN_ONLY',
      ai_execution_count: 0,
      human_review_required: true,
      version: 'test',
    });
    (apiClient.getLiveSourcesStatus as any).mockResolvedValue(_statusResponse());
    (apiClient.getWatchdogSummary as any).mockResolvedValue({
      present: true,
      status: 'HEALTHY',
      summary: null,
    });
    render(<TopTruthBar />);
    const chip = await screen.findByTestId('top-truth-bar-live-chip');
    expect(chip.textContent).toMatch(/LIVE BACKEND/);
    // Snapshot tile is present too.
    const snapshot = await screen.findByTestId('source-configuration-snapshot');
    expect(snapshot.getAttribute('data-snapshot-state')).toBe('present');
    expect(snapshot.getAttribute('data-total')).toBe('3');
  });

  it('always renders the advisory-only footer chip', async () => {
    (apiClient.checkHealth as any).mockResolvedValue(null);
    (apiClient.getLiveSourcesStatus as any).mockResolvedValue(null);
    (apiClient.getWatchdogSummary as any).mockResolvedValue(null);
    render(<TopTruthBar />);
    const footer = await screen.findByTestId('top-truth-bar-advisory-chip');
    expect(footer.textContent).toMatch(/Advisory only/);
    expect(footer.textContent).toMatch(/No execution/);
  });

  it('never emits execution-style verbs', async () => {
    (apiClient.checkHealth as any).mockResolvedValue(null);
    (apiClient.getLiveSourcesStatus as any).mockResolvedValue(null);
    (apiClient.getWatchdogSummary as any).mockResolvedValue(null);
    const { container } = render(<TopTruthBar />);
    await waitFor(() => {
      expect(screen.getByTestId('top-truth-bar').getAttribute('data-loaded')).toBe('true');
    });
    const text = (container.textContent || '').toLowerCase();
    expect(text).not.toMatch(/\bbuy\b/);
    expect(text).not.toMatch(/\bsell\b/);
    expect(text).not.toMatch(/\bexecute\b/);
    expect(text).not.toMatch(/\bplace order\b/);
  });
});
