/**
 * Regression spec: the Dashboard must never stay stuck on "Loading signals…".
 *
 * Root cause history: every dashboard screen cleared its `loading` flag only
 * inside `Promise.all(...).then(...)`. If a request hung (no fetch timeout)
 * or a helper unexpectedly rejected, `.then` never ran and the tab stayed on
 * "Loading…" forever.
 *
 * The fix is twofold: a per-request timeout in apiFetch (covered by
 * apiClient.timeout.spec.ts) and a `.catch` on the page-level Promise.all.
 * These tests pin the page behaviour: whether the helpers resolve to
 * mock/null OR reject outright, the Dashboard leaves the loading state.
 */
// @ts-ignore
import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { MOCK_INBOX_RESPONSE } from '@/lib/mockData';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

vi.mock('@/lib/apiClient', () => ({
  getSignals: vi.fn(),
  checkHealth: vi.fn(),
  getSourceHealth: vi.fn(),
  getLiveSignals: vi.fn(),
  getSourceHealthSummary: vi.fn(),
}));

import {
  getSignals,
  checkHealth,
  getSourceHealth,
  getLiveSignals,
  getSourceHealthSummary,
} from '@/lib/apiClient';
import DashboardPage from '@/app/page';

describe('Dashboard loading resolution', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getSourceHealthSummary as any).mockResolvedValue(null);
  });

  it('leaves the loading state and shows the offline/mock view when helpers resolve to fallbacks', async () => {
    (getSignals as any).mockResolvedValue({ data: MOCK_INBOX_RESPONSE, isMock: true });
    (checkHealth as any).mockResolvedValue(null);
    (getSourceHealth as any).mockResolvedValue(null);
    (getLiveSignals as any).mockResolvedValue(null);

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.queryByText('Loading signals…')).not.toBeInTheDocument();
    });
    // Offline banner confirms we resolved to a deterministic (mock) state.
    expect(screen.getByText('BACKEND OFFLINE')).toBeInTheDocument();
  });

  it('still leaves the loading state if a helper rejects outright (.catch guard)', async () => {
    (getSignals as any).mockRejectedValue(new Error('boom'));
    (checkHealth as any).mockRejectedValue(new Error('boom'));
    (getSourceHealth as any).mockRejectedValue(new Error('boom'));
    (getLiveSignals as any).mockRejectedValue(new Error('boom'));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.queryByText('Loading signals…')).not.toBeInTheDocument();
    });
  });

  it('always renders the advisory-only / AI-executions-zero governance copy', async () => {
    (getSignals as any).mockResolvedValue({ data: MOCK_INBOX_RESPONSE, isMock: true });
    (checkHealth as any).mockResolvedValue(null);
    (getSourceHealth as any).mockResolvedValue(null);
    (getLiveSignals as any).mockResolvedValue(null);

    render(<DashboardPage />);

    expect(
      screen.getByText(/This system does not place trades\./i),
    ).toBeInTheDocument();
    expect(screen.getByText('AI Executions')).toBeInTheDocument();
    // Let the effect's async state updates settle to avoid act() warnings.
    await waitFor(() => {
      expect(screen.queryByText('Loading signals…')).not.toBeInTheDocument();
    });
  });
});
