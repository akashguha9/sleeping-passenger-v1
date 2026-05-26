import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { RunRefreshButton } from '../RunRefreshButton';

// Calibration Corpus + Hosted Canary sprint, Phase 4.

const mockRun = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  runLiveRefresh: () => mockRun(),
}));

// Action-verb forms that the button label must NEVER use.  The
// disclaiming subtext ("Does not trade") and the stamp string
// ("execution_gate=LOCKED") are exempt by design — those phrases EXIST
// to reinforce the safety boundary.
const FORBIDDEN_BUTTON_TOKENS = [
  'execute', 'trade now', 'order', 'buy', 'sell', 'place ', 'broker',
];

function assertButtonNeverPromisesExecution(button: HTMLElement): void {
  const text = (button.textContent ?? '').toLowerCase();
  for (const token of FORBIDDEN_BUTTON_TOKENS) {
    expect(text, `button label must not contain "${token}"`).not.toContain(token);
  }
}

describe('RunRefreshButton', () => {
  beforeEach(() => {
    mockRun.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the advisory-only copy without forbidden words', () => {
    render(<RunRefreshButton />);
    const btn = screen.getByTestId('run-refresh-button');
    expect(btn).toHaveTextContent(/Run advisory-only source refresh/i);
    assertButtonNeverPromisesExecution(btn);
  });

  it('calls runLiveRefresh and shows loading state', async () => {
    let resolve!: (v: unknown) => void;
    mockRun.mockImplementation(
      () => new Promise((r) => {
        resolve = r;
      }),
    );
    render(<RunRefreshButton />);

    fireEvent.click(screen.getByTestId('run-refresh-button'));
    expect(screen.getByTestId('run-refresh-button')).toBeDisabled();
    expect(screen.getByTestId('run-refresh-button')).toHaveTextContent(/Refreshing/i);
    expect(mockRun).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolve({
        advisory_status: 'ADVISORY_ONLY',
        execution_gate: 'LOCKED',
        broker_api_called: false,
        ai_execution_count: 0,
        refresh_status: 'SUCCESS',
        sources_attempted: 3,
        sources_succeeded: 3,
        sources_skipped: 0,
        sources_failed: 0,
        rows_written: 42,
        started_at_utc: '2026-05-26T00:00:00Z',
        finished_at_utc: '2026-05-26T00:01:00Z',
        source_results: [
          { source: 'gdelt', status: 'SUCCESS', rows_written: 20, skipped: false, error_redacted: '' },
        ],
      });
    });
    await waitFor(() => expect(screen.getByTestId('run-refresh-result')).toBeInTheDocument());
  });

  it('renders success summary with advisory stamps and source rows', async () => {
    mockRun.mockResolvedValue({
      advisory_status: 'ADVISORY_ONLY',
      execution_gate: 'LOCKED',
      broker_api_called: false,
      ai_execution_count: 0,
      refresh_status: 'PARTIAL',
      sources_attempted: 3,
      sources_succeeded: 2,
      sources_skipped: 1,
      sources_failed: 0,
      rows_written: 99,
      started_at_utc: '2026-05-26T00:00:00Z',
      finished_at_utc: '2026-05-26T00:00:30Z',
      source_results: [
        { source: 'gdelt', status: 'SUCCESS', rows_written: 60, skipped: false, error_redacted: '' },
        { source: 'kalshi_public', status: 'SUCCESS', rows_written: 39, skipped: false, error_redacted: '' },
        { source: 'newsapi', status: 'SKIPPED', rows_written: 0, skipped: true, error_redacted: 'NEWS_API_KEY missing' },
      ],
    });
    render(<RunRefreshButton />);
    fireEvent.click(screen.getByTestId('run-refresh-button'));

    await waitFor(() => expect(screen.getByTestId('run-refresh-result')).toBeInTheDocument());
    const panel = screen.getByTestId('run-refresh-panel');
    expect(panel.textContent).toContain('ADVISORY_ONLY');
    expect(panel.textContent).toContain('LOCKED');
    expect(panel.textContent).toContain('broker_api_called=false');
    expect(panel.textContent).toContain('ai_execution_count=0');
    expect(screen.getByTestId('run-refresh-source-gdelt')).toHaveTextContent('gdelt');
    expect(screen.getByTestId('run-refresh-source-newsapi')).toHaveTextContent('newsapi');
    expect(screen.getByTestId('run-refresh-status')).toHaveTextContent('PARTIAL');
    assertButtonNeverPromisesExecution(screen.getByTestId('run-refresh-button'));
  });

  it('shows degraded warning and does not pretend refresh ran when backend is offline', async () => {
    mockRun.mockRejectedValue(new Error('Backend unavailable'));
    render(<RunRefreshButton />);
    fireEvent.click(screen.getByTestId('run-refresh-button'));

    await waitFor(() =>
      expect(screen.getByTestId('run-refresh-degraded')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('run-refresh-result')).not.toBeInTheDocument();
    const panel = screen.getByTestId('run-refresh-panel');
    expect(panel.textContent).toMatch(/no refresh attempted/i);
    assertButtonNeverPromisesExecution(screen.getByTestId('run-refresh-button'));
  });

  it('subtext explicitly disclaims trading and surfaces execution_gate=LOCKED', () => {
    render(<RunRefreshButton />);
    const panel = screen.getByTestId('run-refresh-panel');
    expect(panel.textContent).toMatch(/does not trade/i);
    expect(panel.textContent).toContain('execution_gate=LOCKED');
  });
});
