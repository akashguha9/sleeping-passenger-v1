/**
 * Vitest spec for honest, source-aware Live Signals display state.
 *
 * Covers the truthfulness fix:
 *   - Etherscan tab with display_state=optional_unconfigured_with_archive:
 *     no "Total Signals 25" / "Latest Fetched", instead
 *     "Current live signals 0" + "Archived/persisted rows 25" +
 *     "Latest archived row" + optional-not-configured warning.
 *   - Asia Disclosure tab with display_state=planned_coverage:
 *     coverage table with exactly 11 countries, India excluded,
 *     planned/not-scored banner present.
 *   - Stale-active source (GDELT) keeps the stale banner intact.
 *   - Advisory-only badges remain visible.
 */
// @ts-ignore
import { render, screen, waitFor, within } from '@testing-library/react';
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
  getLiveSignals: vi.fn(),
  getSourceHealthSummary: vi.fn().mockResolvedValue(null),
  getLiveSourcesStatus: vi.fn(),
  getKalshiSourceHealth: vi.fn().mockResolvedValue(null),
  getWatchdogSummary: vi.fn().mockResolvedValue(null),
}));

import {
  getLiveSignals,
  getLiveSourcesStatus,
} from '@/lib/apiClient';
import LiveSignalsPage from '@/app/live-signals/page';

const mockLiveSignals = getLiveSignals as unknown as ReturnType<typeof vi.fn>;
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

const COUNTRY_LIST = [
  'China',
  'Japan',
  'Russia',
  'South Korea',
  'Turkey',
  'Indonesia',
  'Saudi Arabia',
  'Taiwan',
  'Israel',
  'Singapore',
  'United Arab Emirates',
];

function makeEntry(overrides: any = {}) {
  return {
    source_key: overrides.source_key ?? 'polymarket',
    freshness_state: 'fresh',
    last_success_at: null,
    hours_since_last_success: null,
    next_expected_refresh_at: null,
    cadence_hours: 6,
    credential_configured: true,
    adapter_status: 'implemented',
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    execution_permission: false,
    can_execute: false,
    may_inform_human_review: true,
    may_execute: false,
    may_call_broker: false,
    tier: 'core',
    advisory_only: true,
    ...overrides,
  };
}

function makeStatus(overrides: any) {
  return {
    operation: 'get_live_sources_status',
    sources: {},
    source_count: 0,
    freshness_distribution: {},
    stale_sources: [],
    excluded_from_stale: [],
    refresh_configured: true,
    stale_threshold_hours: 6,
    scheduler_hint: '.\\scripts\\windows\\register_live_signal_refresh_task.ps1',
    manual_refresh_command: 'python scripts/refresh_live_signals.py --write',
    source_coverage_rows: {},
    asia_disclosure_coverage_rows: [],
    ...SAFETY,
    ...overrides,
  };
}

beforeEach(() => {
  mockLiveSignals.mockReset();
  mockStatus.mockReset();
});

describe('Etherscan tab — optional, not configured, with archived rows', () => {
  beforeEach(() => {
    // 25 archived Etherscan rows, all from May 12.
    const events = Array.from({ length: 25 }, (_, i) => ({
      id: i + 1,
      event_id: `etherscan-row-${i}`,
      source_name: 'etherscan',
      raw_payload: { hash: `0xabc${i}`, block_number: String(1000 + i) },
      fetched_at: '2026-05-12T12:00:00Z',
      advisory_status: 'ADVISORY_ONLY',
      human_review_required: true,
      execution_gate: 'LOCKED',
      ai_execution_count: 0,
    }));
    mockLiveSignals.mockResolvedValue({
      live_signal_events: events,
      count: events.length,
      advisory_status: 'ADVISORY_ONLY',
      execution_mode: 'HUMAN_ONLY',
      ai_execution_count: 0,
      human_review_required: true,
    });
    mockStatus.mockResolvedValue(
      makeStatus({
        excluded_from_stale: [
          { source: 'etherscan', reason: 'optional_config_missing' },
        ],
        sources: {
          etherscan: makeEntry({
            source_key: 'etherscan',
            adapter_status: 'implemented',
            credential_configured: false,
            tier: 'optional',
            freshness_state: 'skipped',
            is_stale: false,
            stale_excluded_reason: 'optional_config_missing',
            stale_reason:
              'optional source not configured — not counted as stale',
            display_state: 'optional_unconfigured_with_archive',
            is_current_live: false,
            is_configured: false,
            is_optional: true,
            is_planned: false,
            is_active: true,
            current_live_count: 0,
            archived_row_count: 25,
            coverage_row_count: 0,
            total_persisted_count: 25,
            latest_persisted_row_at_utc: '2026-05-12T12:00:00+00:00',
            display_count_label: 'Archived/persisted rows',
            display_timestamp_label: 'Latest archived row',
            display_timestamp_value: '2026-05-12T12:00:00+00:00',
            source_display_warning:
              'Etherscan is optional and not configured. Rows below are archived/persisted records, not current live data.',
            rows_are_current_live: false,
            rows_are_archived: true,
            rows_are_stale: false,
            rows_display_reason: 'optional_config_missing_archive',
            excluded_from_stale: true,
            advisory_only: true,
          }),
        },
      }),
    );
  });

  it('does NOT render generic "Total Signals" / "Latest Fetched" labels', async () => {
    render(<LiveSignalsPage />);
    // Switch to the Etherscan tab so the source-aware tiles render.
    await waitFor(() => screen.getByRole('button', { name: 'Etherscan' }));
    (screen.getByRole('button', { name: 'Etherscan' }) as HTMLButtonElement).click();

    await waitFor(() =>
      expect(screen.queryByTestId('signal-stat-tiles')).toBeTruthy(),
    );
    const tiles = screen.getByTestId('signal-stat-tiles');
    expect(tiles.getAttribute('data-display-state')).toBe(
      'optional_unconfigured_with_archive',
    );
    expect(within(tiles).queryByText(/^Total Signals$/i)).toBeNull();
  });

  it('renders Current live signals 0, Archived/persisted rows 25, Latest archived row', async () => {
    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Etherscan' }));
    (screen.getByRole('button', { name: 'Etherscan' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getByTestId('tile-current-live'));
    const liveTile = screen.getByTestId('tile-current-live');
    expect(liveTile.textContent).toMatch(/Current live signals/i);
    expect(liveTile.textContent).toMatch(/0/);

    const archivedTile = screen.getByTestId('tile-archived');
    expect(archivedTile.textContent).toMatch(/Archived\/persisted rows/i);
    expect(archivedTile.textContent).toMatch(/25/);

    expect(screen.getByTestId('tile-latest-archived').textContent).toMatch(
      /Latest archived row/i,
    );
  });

  it('renders the optional-not-configured display banner', async () => {
    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Etherscan' }));
    (screen.getByRole('button', { name: 'Etherscan' }) as HTMLButtonElement).click();

    await waitFor(() =>
      expect(screen.getByTestId('selected-source-display-banner')).toBeTruthy(),
    );
    const banner = screen.getByTestId('selected-source-display-banner');
    expect(banner.getAttribute('data-source')).toBe('etherscan');
    expect(banner.textContent).toMatch(/optional and not configured/i);
    expect(banner.textContent).toMatch(/archived\/persisted records/i);
  });

  it('marks individual Etherscan cards as archived (not current live)', async () => {
    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Etherscan' }));
    (screen.getByRole('button', { name: 'Etherscan' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('signal-event-card'));
    const cards = screen.getAllByTestId('signal-event-card');
    expect(cards.length).toBeGreaterThan(0);
    for (const card of cards) {
      expect(card.getAttribute('data-row-classification')).toBe('archived');
      expect(within(card).getByTestId('archived-row-chip')).toBeTruthy();
    }
  });
});

describe('Asia Disclosure tab — planned, coverage rows', () => {
  beforeEach(() => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [],
      count: 0,
      advisory_status: 'ADVISORY_ONLY',
      execution_mode: 'HUMAN_ONLY',
      ai_execution_count: 0,
      human_review_required: true,
    });
    const coverageRows = COUNTRY_LIST.map((c) => ({
      country: c,
      disclosure_source: '',
      source_url: '',
      status: 'Active',
      notes: '',
    }));
    mockStatus.mockResolvedValue(
      makeStatus({
        excluded_from_stale: [
          { source: 'asia_disclosure', reason: 'planned_not_scored' },
        ],
        asia_disclosure_coverage_rows: coverageRows,
        source_coverage_rows: { asia_disclosure: coverageRows },
        sources: {
          asia_disclosure: makeEntry({
            source_key: 'asia_disclosure',
            adapter_status: 'planned',
            credential_configured: true,
            tier: 'planned',
            freshness_state: 'never_run',
            is_stale: false,
            stale_excluded_reason: 'planned_not_scored',
            stale_reason: 'planned adapter — not counted as stale',
            display_state: 'planned_coverage',
            is_current_live: false,
            is_configured: true,
            is_optional: false,
            is_planned: true,
            is_active: false,
            current_live_count: 0,
            archived_row_count: 0,
            coverage_row_count: 11,
            total_persisted_count: 0,
            latest_persisted_row_at_utc: null,
            display_count_label: 'Coverage rows',
            display_timestamp_label: 'No live runs',
            display_timestamp_value: null,
            source_display_warning:
              'This source is planned/not scored. Showing configured coverage only; no live source run has been recorded.',
            rows_are_current_live: false,
            rows_are_archived: false,
            rows_are_stale: false,
            rows_display_reason: 'planned_coverage',
            excluded_from_stale: true,
            advisory_only: true,
          }),
        },
      }),
    );
  });

  it('renders the planned/coverage empty-state banner instead of generic empty', async () => {
    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Asia Disclosure' }));
    (screen.getByRole('button', { name: 'Asia Disclosure' }) as HTMLButtonElement).click();

    await waitFor(() =>
      expect(
        screen.getByTestId('asia-disclosure-empty-coverage-banner'),
      ).toBeTruthy(),
    );
    const banner = screen.getByTestId('asia-disclosure-empty-coverage-banner');
    expect(banner.textContent).toMatch(
      /No live Asia Disclosure signals recorded yet/i,
    );
    expect(banner.textContent).toMatch(/Showing configured coverage list/i);
  });

  it('renders the 11-country coverage table without India', async () => {
    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Asia Disclosure' }));
    (screen.getByRole('button', { name: 'Asia Disclosure' }) as HTMLButtonElement).click();

    await waitFor(() =>
      expect(screen.getByTestId('asia-disclosure-coverage-table')).toBeTruthy(),
    );
    const rows = screen.getAllByTestId('asia-disclosure-coverage-row');
    expect(rows.length).toBe(11);
    const countries = rows.map((r) => r.getAttribute('data-country'));
    expect(countries).toEqual(COUNTRY_LIST);
    expect(countries).not.toContain('India');
  });

  it('reports Current live signals 0 + Coverage rows 11 in summary tiles', async () => {
    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Asia Disclosure' }));
    (screen.getByRole('button', { name: 'Asia Disclosure' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getByTestId('tile-current-live'));
    expect(screen.getByTestId('tile-current-live').textContent).toMatch(
      /Current live signals/i,
    );
    expect(screen.getByTestId('tile-current-live').textContent).toMatch(/0/);
    expect(screen.getByTestId('tile-coverage').textContent).toMatch(
      /Coverage rows/i,
    );
    expect(screen.getByTestId('tile-coverage').textContent).toMatch(/11/);
    expect(screen.getByTestId('tile-status-planned').textContent).toMatch(
      /planned/i,
    );
  });
});

describe('Stale active sources — GDELT remains visible and not hidden', () => {
  it('renders the stale-source banner with GDELT listed', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [],
      count: 0,
      advisory_status: 'ADVISORY_ONLY',
      execution_mode: 'HUMAN_ONLY',
      ai_execution_count: 0,
      human_review_required: true,
    });
    mockStatus.mockResolvedValue(
      makeStatus({
        stale_sources: ['gdelt'],
        excluded_from_stale: [
          { source: 'etherscan', reason: 'optional_config_missing' },
          { source: 'grok_xai', reason: 'optional_config_missing' },
          { source: 'asia_disclosure', reason: 'planned_not_scored' },
        ],
        sources: {
          gdelt: makeEntry({
            source_key: 'gdelt',
            credential_configured: true,
            freshness_state: 'overdue',
            is_stale: true,
            stale_reason: 'refresh error: HTTP 429 rate_limited',
            display_state: 'stale_active',
            current_live_count: 0,
            archived_row_count: 5,
            total_persisted_count: 5,
          }),
        },
      }),
    );

    render(<LiveSignalsPage />);
    await waitFor(() =>
      expect(screen.getByTestId('stale-refresh-banner')).toBeTruthy(),
    );
    expect(screen.getByTestId('stale-active-sources').textContent).toMatch(
      /GDELT/,
    );
    expect(screen.getByTestId('excluded-from-stale').textContent).toMatch(
      /Etherscan.*optional.*not configured/i,
    );
    expect(screen.getByTestId('excluded-from-stale').textContent).toMatch(
      /Asia Disclosure.*planned\/not scored/i,
    );
  });
});
