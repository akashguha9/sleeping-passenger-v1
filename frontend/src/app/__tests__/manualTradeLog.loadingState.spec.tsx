/**
 * Vitest spec for the Manual Trade Log "Previously Logged" panel loading
 * lifecycle.
 *
 * Regression guard for the screenshotted bug where the right-side
 * "PREVIOUSLY LOGGED" panel was stuck forever on "Loading…". The panel
 * MUST resolve to a finite state — empty, offline, or the trade list —
 * whether the backend returns [], returns null (offline), or the wrapper
 * rejects outright.
 *
 * Record-keeping surface only — no broker/execution path is touched.
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

vi.mock('@/lib/apiClient', () => ({
  getManualTrades: vi.fn(),
  getReconciliationQueue: vi.fn(),
  getSourceHealthSummary: vi.fn().mockResolvedValue(null),
  getSourceHealth: vi.fn().mockResolvedValue(null),
  getLiveSourcesStatus: vi.fn().mockResolvedValue(null),
  getDbStatus: vi.fn().mockResolvedValue(null),
  checkHealth: vi.fn().mockResolvedValue(null),
  postManualTrade: vi.fn().mockResolvedValue({ trade_id: 'MT_X' }),
  hasStoredApiToken: vi.fn().mockReturnValue(false),
  setStoredApiToken: vi.fn(),
  clearStoredApiToken: vi.fn(),
  getStoredApiToken: vi.fn().mockReturnValue(null),
  ApiHttpError: class ApiHttpError extends Error {
    status: number;
    reason?: string;
    constructor(status: number, message: string, reason?: string) {
      super(message);
      this.status = status;
      this.reason = reason;
    }
  },
  ApiTokenRequiredError: class ApiTokenRequiredError extends Error {
    status: number;
    constructor(status = 401) {
      super('token');
      this.status = status;
    }
  },
}));

import { getManualTrades, getReconciliationQueue } from '@/lib/apiClient';
import ManualTradeLogPage from '@/app/manual-trade-log/page';

const mockTrades = getManualTrades as unknown as ReturnType<typeof vi.fn>;
const mockQueue = getReconciliationQueue as unknown as ReturnType<typeof vi.fn>;

function emptyResponse() {
  return {
    operation: 'list_manual_trades',
    trade_count: 0,
    trades: [],
    advisory_status: 'ADVISORY_ONLY',
    execution_mode: 'HUMAN_ONLY',
    ai_execution_count: 0,
    human_review_required: true,
    broker_api_called: false,
    generated_at: '2026-06-05T00:00:00Z',
  };
}

describe('ManualTradeLogPage — Previously Logged loading lifecycle', () => {
  beforeEach(() => {
    mockTrades.mockReset();
    mockQueue.mockReset();
    mockQueue.mockResolvedValue(null);
  });

  it('shows the EMPTY state (not Loading) when the DB has no trades', async () => {
    mockTrades.mockResolvedValue(emptyResponse());
    render(<ManualTradeLogPage />);

    await waitFor(() =>
      expect(screen.getByText('No manual trades logged yet.')).toBeInTheDocument(),
    );
    // The panel's own "Loading…" placeholder must be gone.
    expect(screen.queryByText(/^Loading…$/)).not.toBeInTheDocument();
  });

  it('shows the OFFLINE state when the wrapper returns null', async () => {
    mockTrades.mockResolvedValue(null);
    render(<ManualTradeLogPage />);

    await waitFor(() =>
      expect(screen.getByText('Backend offline')).toBeInTheDocument(),
    );
    expect(screen.queryByText(/^Loading…$/)).not.toBeInTheDocument();
  });

  it('clears the spinner even if the wrapper REJECTS (defence in depth)', async () => {
    mockTrades.mockRejectedValue(new Error('unexpected'));
    render(<ManualTradeLogPage />);

    // .catch() sets result=null → offline empty state; .finally() clears loading.
    await waitFor(() =>
      expect(screen.queryByText(/^Loading…$/)).not.toBeInTheDocument(),
    );
    expect(screen.getByText('Backend offline')).toBeInTheDocument();
  });
});
