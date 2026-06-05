/**
 * Vitest spec for the Moltbook page loading lifecycle.
 *
 * Regression guard for the screenshotted bug where the page was stuck
 * forever on "Loading moltbook…". The page MUST resolve to a finite state
 * (success / empty / mock-offline) whether the backend returns data, an
 * empty list, or the wrapper rejects outright.
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
  getMoltbook: vi.fn(),
}));

import { getMoltbook } from '@/lib/apiClient';
import MoltbookPage from '@/app/moltbook/page';

const mockGetMoltbook = getMoltbook as unknown as ReturnType<typeof vi.fn>;

describe('MoltbookPage loading lifecycle', () => {
  beforeEach(() => {
    mockGetMoltbook.mockReset();
  });

  it('resolves to the EMPTY state (not Loading) when backend returns []', async () => {
    mockGetMoltbook.mockResolvedValue({
      data: { items: [], item_count: 0 },
      isMock: false,
    });
    render(<MoltbookPage />);

    await waitFor(() =>
      expect(screen.getByText('No Moltbook entries yet.')).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Loading moltbook/i)).not.toBeInTheDocument();
  });

  it('clears the spinner even if the wrapper REJECTS (defence in depth)', async () => {
    mockGetMoltbook.mockRejectedValue(new Error('unexpected'));
    render(<MoltbookPage />);

    // The .catch().finally() must still flip loading off — the page falls
    // back to its seeded mock entries and the offline banner, never stuck.
    await waitFor(() =>
      expect(screen.queryByText(/Loading moltbook/i)).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/BACKEND OFFLINE/i)).toBeInTheDocument();
  });
});
