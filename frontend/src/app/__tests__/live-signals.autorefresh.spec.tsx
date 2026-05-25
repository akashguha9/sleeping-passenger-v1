/**
 * Vitest spec for the Live Signals Auto-refresh panel and stale wording.
 *
 * Pins the contract:
 *   - When auto_refresh_status.status === PASS, panel shows "ENABLED"
 *     and cadence "every 6 hours"
 *   - When NOT_INSTALLED, panel shows the exact PowerShell registration
 *     command and the manual refresh command
 *   - When FAILING, panel shows the repair command
 *   - Stale-source banner wording uses "hours" not "h" or bare number
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
  getLiveSignals: vi.fn().mockResolvedValue({
    operation: 'get_live_signals',
    bridge: { total_event_count: 0 },
    events: [],
    live_signal_events: [],
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    execution_permission: false,
    can_execute: false,
    human_review_required: true,
  }),
  getSourceHealthSummary: vi.fn().mockResolvedValue(null),
  getLiveSourcesStatus: vi.fn(),
  getKalshiSourceHealth: vi.fn().mockResolvedValue(null),
  getWatchdogSummary: vi.fn().mockResolvedValue(null),
}));

import { getLiveSourcesStatus } from '@/lib/apiClient';
import LiveSignalsPage from '@/app/live-signals/page';

const mockStatus = getLiveSourcesStatus as unknown as ReturnType<typeof vi.fn>;

const SAFETY = {
  advisory_status: 'ADVISORY_ONLY',
  execution_gate: 'LOCKED',
  broker_api_called: false,
  ai_execution_count: 0,
  execution_permission: false,
  can_execute: false,
  human_review_required: true,
};

function makeStatus(overrides: any) {
  return {
    operation: 'get_live_sources_status',
    sources: {},
    source_count: 0,
    freshness_distribution: {},
    stale_sources: [],
    refresh_configured: true,
    stale_threshold_hours: 6,
    last_refresh_attempt: '2026-05-15T10:00:00Z',
    last_refresh_success: '2026-05-15T10:00:00Z',
    scheduler_hint: '.\\scripts\\windows\\register_live_signal_refresh_task.ps1',
    manual_refresh_command: 'python scripts/refresh_live_signals.py --write',
    ...SAFETY,
    ...overrides,
  };
}

beforeEach(() => {
  mockStatus.mockReset();
});

describe('Live Signals Auto-refresh panel', () => {
  it('PASS — shows ENABLED with 6-hour cadence', async () => {
    mockStatus.mockResolvedValue(makeStatus({
      auto_refresh_status: {
        status: 'PASS',
        cadence_hours: 6,
        last_run_time: '2026-05-15T10:00:00Z',
        next_run_time: '2026-05-15T16:00:00Z',
        last_successful_refresh_utc: '2026-05-15T10:00:00Z',
        installed: true,
        enabled: true,
        advisory_only: true,
        broker_api_called: false,
        ai_execution_count: 0,
        execution_gate: 'LOCKED',
      },
    }));
    render(<LiveSignalsPage />);
    await waitFor(() =>
      expect(screen.getByTestId('auto-refresh-panel')).toBeTruthy(),
    );
    const panel = screen.getByTestId('auto-refresh-panel');
    expect(panel.getAttribute('data-auto-refresh-status')).toBe('PASS');
    expect(screen.getByTestId('auto-refresh-chip').textContent).toMatch(/ENABLED/);
    expect(panel.textContent ?? '').toMatch(/every 6 hours/i);
  });

  it('NOT_INSTALLED — surfaces the exact PowerShell registration command', async () => {
    mockStatus.mockResolvedValue(makeStatus({
      stale_sources: ['polymarket', 'gdelt'],
      refresh_configured: false,
      auto_refresh_status: {
        status: 'NOT_INSTALLED',
        cadence_hours: 6,
        installed: false,
        enabled: false,
        status_reason:
          "Scheduled task 'SleepingPassengerLiveSignalRefresh' is not registered.",
        suggested_command:
          'powershell -ExecutionPolicy Bypass -File .\\scripts\\windows\\register_live_signal_refresh_task.ps1',
        manual_refresh_command: 'python scripts/refresh_live_signals.py --write',
        advisory_only: true,
        broker_api_called: false,
        ai_execution_count: 0,
        execution_gate: 'LOCKED',
      },
    }));
    render(<LiveSignalsPage />);
    await waitFor(() =>
      expect(screen.getByTestId('auto-refresh-panel')).toBeTruthy(),
    );
    expect(screen.getByTestId('auto-refresh-chip').textContent).toMatch(/NOT INSTALLED/);
    expect(screen.getByTestId('auto-refresh-suggested-command').textContent).toMatch(
      /register_live_signal_refresh_task\.ps1/,
    );
  });

  it('FAILING — shows repair command in panel', async () => {
    mockStatus.mockResolvedValue(makeStatus({
      auto_refresh_status: {
        status: 'FAILING',
        cadence_hours: 6,
        installed: true,
        enabled: true,
        last_task_result: 1,
        status_reason: 'Last task result 1 (non-zero exit).',
        suggested_command:
          'powershell -ExecutionPolicy Bypass -File .\\scripts\\windows\\register_live_signal_refresh_task.ps1 -Force',
        advisory_only: true,
        broker_api_called: false,
        ai_execution_count: 0,
        execution_gate: 'LOCKED',
      },
    }));
    render(<LiveSignalsPage />);
    await waitFor(() =>
      expect(screen.getByTestId('auto-refresh-panel')).toBeTruthy(),
    );
    expect(screen.getByTestId('auto-refresh-chip').textContent).toMatch(/FAILING/);
    expect(screen.getByTestId('auto-refresh-suggested-command').textContent).toMatch(
      /-Force/,
    );
  });

  it('stale-source banner wording uses "hours" not bare number', async () => {
    mockStatus.mockResolvedValue(makeStatus({
      stale_sources: ['polymarket', 'gdelt', 'india'],
      stale_threshold_hours: 6,
      auto_refresh_status: {
        status: 'PASS',
        cadence_hours: 6,
        advisory_only: true,
        broker_api_called: false,
        ai_execution_count: 0,
        execution_gate: 'LOCKED',
      },
    }));
    render(<LiveSignalsPage />);
    await waitFor(() => {
      const txt = document.body.textContent ?? '';
      expect(txt).toMatch(/older than 6 hours/i);
      expect(txt).not.toMatch(/older than 6\)/); // bare "6)"
    });
  });
});
