/**
 * Vitest spec for the Chart Structure freshness gate (Sprint H).
 *
 * Locks down the visible behaviour of the page when the backend returns
 * a freshness_gate other than PASS:
 *
 *   * BLOCK: prominent stale-data warning is rendered, the normal report
 *     view is suppressed, latest_candle_utc is visible, suggested next
 *     step is DATA_REFRESH_REQUIRED or HUMAN_REVIEW_DATA_STALE, and the
 *     ADVISORY_ONLY / HUMAN_ONLY / Execution-Locked badges remain.
 *   * 2004 latest candle: the freshness panel surfaces the timestamp and
 *     the page does NOT render OHLCV summary tiles for it.
 *   * FRESH: latest close formats neutrally (no hardcoded "$") and the
 *     latest_candle_utc is shown in the freshness panel.
 */
// @ts-ignore
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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
  getChartStructure: vi.fn(),
  bootstrapChartSymbol: vi.fn(),
  getSourceHealthSummary: vi.fn().mockResolvedValue(null),
}));

import { getChartStructure } from '@/lib/apiClient';
import ChartStructurePage from '@/app/chart-structure/page';

const mockGet = getChartStructure as unknown as ReturnType<typeof vi.fn>;

const SAFETY_STAMPS = {
  advisory_status: 'ADVISORY_ONLY',
  execution_gate: 'LOCKED',
  human_review_required: true,
  ai_execution_count: 0,
  broker_api_called: false,
  broker_order_id: 'NONE',
};

function freshFreshness(latestUtc = '2026-05-15T16:00:00Z') {
  return {
    data_freshness_status: 'FRESH',
    freshness_gate: 'PASS',
    latest_candle_utc: latestUtc,
    first_candle_utc: '2026-01-01T16:00:00Z',
    data_age_hours: 1.0,
    data_age_days: 0.04,
    freshness_reason: 'latest candle is 0.0 days old',
    source_kind: 'CANONICAL_SQLITE',
    candle_count: 100,
  } as const;
}

function blockedFreshness(latestUtc = '2004-10-20T16:00:00Z') {
  return {
    data_freshness_status: 'ANCIENT',
    freshness_gate: 'BLOCK',
    latest_candle_utc: latestUtc,
    first_candle_utc: '2004-06-02T16:00:00Z',
    data_age_hours: 99999,
    data_age_days: 7900.5,
    freshness_reason: `latest candle ${latestUtc.slice(0, 10)} is too old`,
    source_kind: 'CANONICAL_SQLITE',
    candle_count: 100,
  } as const;
}

function freshReport() {
  return {
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    human_review_required: true,
    ai_execution_count: 0,
    broker_api_called: false,
    broker_order_id: 'NONE',
    summary: {
      symbol: 'ICICIBANK.NS',
      source: 'market_data',
      candle_count: 100,
      first_timestamp: '2026-01-01',
      latest_timestamp: '2026-05-15T16:00:00Z',
      latest_close: 1085.5,
      latest_volume: 25000000,
      price_change_abs: 5.0,
      price_change_pct: 0.46,
      high_low_range_pct: 1.2,
      average_volume: 24000000,
      volume_ratio_latest_to_average: 1.04,
    },
    candle_anatomy: null,
    trend: null,
    volatility: null,
    support_resistance: null,
    context: { chart_confirmation_score: 0.5, confirmation_reasons: [], contradiction_reasons: [], chart_state: 'TRENDING_UP' },
    advisory: { advisory_summary: 'Chart structure shows an upward trend.', suggested_next_step: 'WATCH_ONLY' },
  };
}

beforeEach(() => {
  mockGet.mockReset();
});

async function fetchSymbol(symbol: string) {
  render(<ChartStructurePage />);
  const input = screen.getByPlaceholderText(/AAPL/);
  fireEvent.change(input, { target: { value: symbol } });
  fireEvent.click(screen.getByRole('button', { name: /fetch/i }));
}

describe('Chart Structure freshness gate', () => {
  it('A7.1 — BLOCK state renders prominent stale-data warning and suppresses report', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'ICICIBANK.NS',
      source_event_id: null,
      candle_count: 100,
      chart_state: 'STALE_DATA_BLOCKED',
      advisory_summary:
        'Market data for ICICIBANK.NS is ancient — latest candle 2004-10-20T16:00:00Z (7900.5 days old).',
      suggested_next_step: 'HUMAN_REVIEW_DATA_STALE',
      report: null,
      freshness: blockedFreshness(),
      data_freshness_status: 'ANCIENT',
      freshness_gate: 'BLOCK',
      latest_candle_utc: '2004-10-20T16:00:00Z',
      data_age_days: 7900.5,
      source_kind: 'CANONICAL_SQLITE',
    });

    await fetchSymbol('ICICIBANK.NS');

    await waitFor(() => {
      expect(screen.getByTestId('chart-stale-data-block')).toBeTruthy();
    });
    expect(screen.getByTestId('chart-freshness-panel').getAttribute('data-freshness-gate')).toBe('BLOCK');
    expect(screen.getByTestId('chart-latest-candle-utc').textContent).toContain('2004-10-20');
    expect(screen.getByTestId('chart-suggested-next-step').textContent).toMatch(
      /DATA_REFRESH_REQUIRED|HUMAN_REVIEW_DATA_STALE/,
    );
    // Normal verdict tiles must NOT be rendered.
    expect(screen.queryByTestId('chart-latest-close')).toBeNull();
    // Safety badges remain visible (the chip row + the page-level badges).
    expect(screen.getAllByText(/Execution.*Locked/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Advisory_Only/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Human_Review_Required/i).length).toBeGreaterThan(0);
  });

  it('A7.2 — 2004 latest candle is surfaced in the freshness panel and does not look normal', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'ICICIBANK.NS',
      source_event_id: null,
      candle_count: 100,
      chart_state: 'STALE_DATA_BLOCKED',
      advisory_summary: 'ancient',
      suggested_next_step: 'HUMAN_REVIEW_DATA_STALE',
      report: null,
      freshness: blockedFreshness('2004-10-20T16:00:00Z'),
      data_freshness_status: 'ANCIENT',
      freshness_gate: 'BLOCK',
      latest_candle_utc: '2004-10-20T16:00:00Z',
      data_age_days: 7900,
      source_kind: 'CANONICAL_SQLITE',
    });

    await fetchSymbol('ICICIBANK.NS');
    await waitFor(() => {
      expect(screen.getByTestId('chart-freshness-warning')).toBeTruthy();
    });
    expect(screen.getByTestId('chart-latest-candle-utc').textContent).toContain('2004-10-20');
    expect(screen.queryByTestId('chart-latest-close')).toBeNull();
  });

  it('A7.3 — fresh data renders the report and the latest_candle_utc', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'ICICIBANK.NS',
      source_event_id: null,
      candle_count: 100,
      report: freshReport(),
      freshness: freshFreshness(),
      data_freshness_status: 'FRESH',
      freshness_gate: 'PASS',
      latest_candle_utc: '2026-05-15T16:00:00Z',
      data_age_days: 0.04,
      source_kind: 'CANONICAL_SQLITE',
    });

    await fetchSymbol('ICICIBANK.NS');
    await waitFor(() => {
      expect(screen.getByTestId('chart-latest-close')).toBeTruthy();
    });
    expect(screen.getByTestId('chart-freshness-panel').getAttribute('data-freshness-gate')).toBe('PASS');
    expect(screen.getByTestId('chart-latest-candle-utc').textContent).toContain('2026-05-15');
  });

  it('A7.4 — latest close formats neutrally without a hardcoded "$" prefix', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'ICICIBANK.NS',
      source_event_id: null,
      candle_count: 100,
      report: freshReport(),
      freshness: freshFreshness(),
      data_freshness_status: 'FRESH',
      freshness_gate: 'PASS',
      latest_candle_utc: '2026-05-15T16:00:00Z',
      data_age_days: 0.04,
      source_kind: 'CANONICAL_SQLITE',
    });

    await fetchSymbol('ICICIBANK.NS');
    await waitFor(() => {
      expect(screen.getByTestId('chart-latest-close')).toBeTruthy();
    });
    const text = screen.getByTestId('chart-latest-close').textContent ?? '';
    expect(text.startsWith('$')).toBe(false);
    expect(text.replace(/,/g, '')).toMatch(/\d/);
  });
});

// ---------------------------------------------------------------------------
// Sprint I — generic price-truth panel.  The page must show "Latest daily
// close" (not "Latest close"), surface latest quote + delta when the
// backend ships the new fields, and render a divergence warning for
// QUOTE_DIVERGES_FROM_DAILY regardless of symbol / market.
// ---------------------------------------------------------------------------

function priceTruthExtras(extras: Record<string, unknown>) {
  return {
    price_truth: {
      symbol: 'X',
      latest_daily_close: null,
      latest_daily_candle_utc: null,
      latest_quote_price: null,
      latest_quote_currency: null,
      latest_quote_timestamp_utc: null,
      latest_quote_source: null,
      quote_freshness_status: null,
      quote_freshness_gate: null,
      quote_age_minutes: null,
      quote_price_delta: null,
      quote_price_delta_pct: null,
      price_truth_status: 'DAILY_ONLY',
      price_truth_reason: '',
      suggested_next_step: 'WATCH_ONLY',
      advisory_status: 'ADVISORY_ONLY',
      execution_gate: 'LOCKED',
      broker_api_called: false,
      ai_execution_count: 0,
      execution_permission: false,
      can_execute: false,
      record_keeping_only: true,
      ...extras,
    },
    ...extras,
  };
}

describe('Chart Structure price-truth panel', () => {
  it('BHARTIARTL.NS divergence shows QUOTE_DIVERGES_FROM_DAILY + HUMAN_REVIEW_PRICE_MISMATCH', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'BHARTIARTL.NS',
      source_event_id: null,
      candle_count: 100,
      report: freshReport(),
      freshness: freshFreshness('2026-05-14T16:00:00Z'),
      data_freshness_status: 'FRESH',
      freshness_gate: 'PASS',
      latest_candle_utc: '2026-05-14T16:00:00Z',
      data_age_days: 1.1,
      source_kind: 'CANONICAL_SQLITE',
      ...priceTruthExtras({
        latest_daily_close: 1789.20,
        latest_daily_candle_utc: '2026-05-14T16:00:00Z',
        latest_quote_price: 1905.40,
        latest_quote_currency: 'INR',
        latest_quote_timestamp_utc: '2026-05-15T15:55:00Z',
        latest_quote_source: 'yahoo_finance',
        quote_price_delta: 116.20,
        quote_price_delta_pct: 6.49,
        price_truth_status: 'QUOTE_DIVERGES_FROM_DAILY',
        price_truth_reason:
          'Latest quote differs strongly from latest daily candle close (+6.49%). Treat chart features as daily-candle technicals, not live price.',
        suggested_next_step: 'HUMAN_REVIEW_PRICE_MISMATCH',
      }),
    });

    await fetchSymbol('BHARTIARTL.NS');
    await waitFor(() => expect(screen.getByTestId('chart-price-truth-panel')).toBeTruthy());

    const panel = screen.getByTestId('chart-price-truth-panel');
    expect(panel.getAttribute('data-price-truth-status')).toBe('QUOTE_DIVERGES_FROM_DAILY');
    expect(screen.getByTestId('price-truth-status-chip').textContent).toMatch(
      /QUOTE DIVERGES FROM DAILY/,
    );
    expect(screen.getByTestId('price-truth-quote-price').textContent).toMatch(/1,?905\.40 INR/);
    expect(screen.getByTestId('price-truth-daily-close').textContent).toMatch(/1,?789\.20 INR/);
    expect(screen.getByTestId('price-truth-delta').textContent).toMatch(/\+116\.20.*\+6\.49%/);
    expect(screen.getByTestId('price-truth-next-step').textContent).toMatch(
      /HUMAN_REVIEW_PRICE_MISMATCH/,
    );
    expect(screen.getByTestId('chart-latest-close').textContent).toMatch(/1,?085\.5/);
  });

  it('AAPL aligned shows QUOTE_ALIGNED — generic, not symbol-special', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'AAPL',
      source_event_id: null,
      candle_count: 100,
      report: freshReport(),
      freshness: freshFreshness(),
      data_freshness_status: 'FRESH',
      freshness_gate: 'PASS',
      latest_candle_utc: '2026-05-15T16:00:00Z',
      data_age_days: 0.04,
      source_kind: 'CANONICAL_SQLITE',
      ...priceTruthExtras({
        latest_daily_close: 180.00,
        latest_daily_candle_utc: '2026-05-15T16:00:00Z',
        latest_quote_price: 180.50,
        latest_quote_currency: 'USD',
        latest_quote_timestamp_utc: '2026-05-15T15:55:00Z',
        latest_quote_source: 'yahoo_finance',
        quote_price_delta: 0.50,
        quote_price_delta_pct: 0.28,
        price_truth_status: 'QUOTE_ALIGNED',
        price_truth_reason: 'Latest quote within 2.0% of latest daily close.',
        suggested_next_step: 'WATCH_ONLY',
      }),
    });

    await fetchSymbol('AAPL');
    await waitFor(() => expect(screen.getByTestId('chart-price-truth-panel')).toBeTruthy());
    expect(screen.getByTestId('chart-price-truth-panel').getAttribute('data-price-truth-status')).toBe(
      'QUOTE_ALIGNED',
    );
    expect(screen.getByTestId('price-truth-quote-price').textContent).toMatch(/180\.50 USD/);
    expect(screen.getByTestId('price-truth-next-step').textContent).toMatch(/WATCH_ONLY/);
  });

  it('Quote unavailable degrades to daily-only without faking a quote', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'UNKNOWN_XYZ',
      source_event_id: null,
      candle_count: 100,
      report: freshReport(),
      freshness: freshFreshness(),
      data_freshness_status: 'FRESH',
      freshness_gate: 'PASS',
      latest_candle_utc: '2026-05-15T16:00:00Z',
      data_age_days: 0.04,
      source_kind: 'CANONICAL_SQLITE',
      ...priceTruthExtras({
        latest_daily_close: 42.0,
        latest_daily_candle_utc: '2026-05-15T16:00:00Z',
        price_truth_status: 'QUOTE_UNAVAILABLE',
        price_truth_reason:
          'Latest quote unavailable; showing latest daily candle close only.',
        suggested_next_step: 'WATCH_ONLY',
      }),
    });
    await fetchSymbol('UNKNOWN_XYZ');
    await waitFor(() => expect(screen.getByTestId('chart-price-truth-panel')).toBeTruthy());
    const reason = screen.getByTestId('price-truth-reason').textContent ?? '';
    expect(reason).toMatch(/Latest quote unavailable/);
    expect(screen.getByTestId('price-truth-quote-price').textContent).toMatch(/—/);
  });

  it('Renders "Latest daily close" label rather than "Latest close"', async () => {
    mockGet.mockResolvedValue({
      ...SAFETY_STAMPS,
      symbol: 'AAPL',
      source_event_id: null,
      candle_count: 100,
      report: freshReport(),
      freshness: freshFreshness(),
      data_freshness_status: 'FRESH',
      freshness_gate: 'PASS',
      latest_candle_utc: '2026-05-15T16:00:00Z',
      data_age_days: 0.04,
      source_kind: 'CANONICAL_SQLITE',
    });
    await fetchSymbol('AAPL');
    await waitFor(() => expect(screen.getByTestId('chart-latest-close')).toBeTruthy());
    const labelNode = screen.getByTestId('chart-latest-close').previousSibling as HTMLElement | null;
    expect(labelNode?.textContent ?? '').toMatch(/Latest Daily Close/i);
  });
});
