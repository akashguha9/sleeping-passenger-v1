/**
 * Vitest spec for the Kalshi first-class source tab.
 *
 * Covers:
 *   - Kalshi tab exists and sits beside Polymarket in the source filter.
 *   - Selecting Kalshi requests the Kalshi-only feed; Polymarket selection
 *     does not surface Kalshi rows.
 *   - All Sources surfaces approved Kalshi rows.
 *   - Kalshi cards render the canonical safety chips and never use
 *     Buy / Sell / Execute trade / Arbitrage / Risk-free wording.
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
  getLiveSignals: vi.fn(),
  getSourceHealthSummary: vi.fn().mockResolvedValue(null),
  getLiveSourcesStatus: vi.fn(),
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

function makeKalshiEvent(overrides: any = {}) {
  return {
    id: overrides.id ?? 100,
    event_id: overrides.event_id ?? 'kalshi_btcmay',
    source_name: 'kalshi',
    raw_payload: {
      source: 'kalshi',
      source_label: 'Kalshi',
      source_market_id: 'BTCMAY-2026',
      title: 'How high will Bitcoin get in May?',
      category: 'Crypto',
      yes_price: 0.42,
      implied_probability: 0.42,
      volume: 1250,
      open_interest: 800,
      close_time_utc: '2026-05-31T23:59:00Z',
      market_url: 'https://kalshi.com/markets/BTCMAY-2026',
      semantic_text:
        'Title: How high will Bitcoin get in May?\nDescription: ...\nCategory: Crypto',
      advisory_status: 'ADVISORY_ONLY',
      execution_permission: 'ADVISORY_ONLY',
      execution_gate: 'LOCKED',
      human_review_required: true,
      broker_api_called: false,
      ai_execution_count: 0,
      ...overrides.raw_payload,
    },
    fetched_at: '2026-05-24T00:00:00Z',
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    execution_gate: 'LOCKED',
    ai_execution_count: 0,
    ...overrides,
  };
}

function makePolyEvent() {
  return {
    id: 1,
    event_id: 'polymarket_apple_foldable',
    source_name: 'polymarket',
    raw_payload: {
      title: 'Will Apple announce a foldable iPhone in 2026?',
      market_id: 'pm-001',
    },
    fetched_at: '2026-05-24T00:00:00Z',
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    execution_gate: 'LOCKED',
    ai_execution_count: 0,
  };
}

function makeDisagreementEvent() {
  // A disagreement row that MENTIONS Kalshi in its text but whose canonical
  // source is NOT kalshi. It must never appear in the Kalshi source tab.
  return {
    id: 700,
    event_id: 'poly_btc__kalshi_btc',
    source_name: 'prediction_market_disagreement',
    raw_payload: {
      pair_id: 'poly_btc__kalshi_btc',
      customer_label: 'Prediction Market Disagreement Alert',
      poly_title: 'Will Bitcoin hit a new high in May?',
      kalshi_title: 'How high will Bitcoin get in May?',
      advisory_status: 'ADVISORY_ONLY',
      execution_gate: 'LOCKED',
      human_review_required: true,
      broker_api_called: false,
      ai_execution_count: 0,
    },
    fetched_at: '2026-05-24T00:00:00Z',
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    execution_gate: 'LOCKED',
    ai_execution_count: 0,
  };
}

function makeStatus(overrides: any = {}) {
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
  mockStatus.mockResolvedValue(makeStatus());
});

describe('Live Signals — Kalshi first-class tab', () => {
  it('renders the Kalshi tab beside Polymarket', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [],
      count: 0,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);

    await waitFor(() => screen.getByRole('button', { name: 'Kalshi' }));
    const polyBtn = screen.getByRole('button', { name: 'Polymarket' });
    const kalshiBtn = screen.getByRole('button', { name: 'Kalshi' });
    // Both buttons exist; Kalshi follows Polymarket in DOM order.
    expect(polyBtn.compareDocumentPosition(kalshiBtn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // GDELT (the prior neighbour) follows Kalshi.
    const gdeltBtn = screen.getByRole('button', { name: 'GDELT' });
    expect(kalshiBtn.compareDocumentPosition(gdeltBtn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('Kalshi tab requests source=kalshi and renders only Kalshi rows', async () => {
    mockLiveSignals.mockImplementation(async (source?: string) => {
      const events =
        source === 'kalshi' ? [makeKalshiEvent()] : [makePolyEvent(), makeKalshiEvent()];
      return {
        live_signal_events: events,
        count: events.length,
        ...SAFETY,
      };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Kalshi' }));
    (screen.getByRole('button', { name: 'Kalshi' }) as HTMLButtonElement).click();

    // Wait for the DOM to settle on the Kalshi-only view (avoids capturing a
    // transient stale render while the source-scoped refetch is in flight).
    await waitFor(() => {
      expect(screen.getAllByTestId('signal-event-card')).toHaveLength(1);
    });
    const cards = screen.getAllByTestId('signal-event-card');
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toMatch(/Bitcoin/i);
    expect(cards[0].textContent).toMatch(/Kalshi/i);
    expect(cards[0].textContent).toMatch(/CRYPTO/i);
  });

  it('Polymarket tab does NOT show Kalshi rows', async () => {
    mockLiveSignals.mockImplementation(async (source?: string) => {
      const events = source === 'polymarket' ? [makePolyEvent()] : [];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Polymarket' }));
    (screen.getByRole('button', { name: 'Polymarket' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('signal-event-card'));
    for (const card of screen.getAllByTestId('signal-event-card')) {
      // No Kalshi event_id, ticker, or category should appear in the
      // Polymarket-only view.
      expect(card.textContent).not.toMatch(/kalshi/i);
    }
  });

  it('All Sources includes approved Kalshi rows alongside other sources', async () => {
    mockLiveSignals.mockImplementation(async (_source?: string) => {
      const events = [makePolyEvent(), makeKalshiEvent()];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'All Sources' }));
    (screen.getByRole('button', { name: 'All Sources' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('signal-event-card'));
    const allText = screen.getAllByTestId('signal-event-card').map((c) => c.textContent || '').join('|');
    expect(allText).toMatch(/Polymarket/i);
    expect(allText).toMatch(/Kalshi/i);
  });

  it('Kalshi tab excludes prediction_market_disagreement rows even if they mention Kalshi', async () => {
    // Even if the kalshi-scoped response carries a leaked disagreement row
    // (or stale All-Sources data lingers), the canonical source guard keeps
    // the Kalshi tab strictly source_name === 'kalshi'.
    mockLiveSignals.mockImplementation(async (source?: string) => {
      const events =
        source === 'kalshi'
          ? [makeKalshiEvent(), makeDisagreementEvent()]
          : [makePolyEvent(), makeKalshiEvent(), makeDisagreementEvent()];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Kalshi' }));
    (screen.getByRole('button', { name: 'Kalshi' }) as HTMLButtonElement).click();

    await waitFor(() => {
      const cards = screen.getAllByTestId('signal-event-card');
      expect(cards).toHaveLength(1);
    });
    const cards = screen.getAllByTestId('signal-event-card');
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toMatch(/Kalshi/i);
    // The disagreement detail block must NOT be present in the Kalshi tab.
    expect(screen.queryByTestId('disagreement-detail-block')).toBeNull();
  });

  it('switching All Sources → Kalshi replaces visible cards (no stale append)', async () => {
    mockLiveSignals.mockImplementation(async (source?: string) => {
      const events =
        source === 'kalshi' ? [makeKalshiEvent()] : [makePolyEvent(), makeKalshiEvent()];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    // All Sources first: both rows visible.
    await waitFor(() => {
      expect(screen.getAllByTestId('signal-event-card')).toHaveLength(2);
    });

    (screen.getByRole('button', { name: 'Kalshi' }) as HTMLButtonElement).click();

    // After switching, exactly the single Kalshi card remains — the Polymarket
    // card is replaced, not appended to.
    await waitFor(() => {
      const cards = screen.getAllByTestId('signal-event-card');
      expect(cards).toHaveLength(1);
    });
    const cards = screen.getAllByTestId('signal-event-card');
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).not.toMatch(/Apple/i); // the Polymarket row is gone
    expect(cards[0].textContent).toMatch(/Bitcoin/i);
  });

  it('Kalshi cards never use Buy / Sell / Execute / Arbitrage language', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [makeKalshiEvent()],
      count: 1,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Kalshi' }));
    (screen.getByRole('button', { name: 'Kalshi' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('signal-event-card'));
    const card = screen.getAllByTestId('signal-event-card')[0];
    const text = (card.textContent || '').toLowerCase();
    const forbidden = [
      'buy ',
      'sell ',
      'trade now',
      'execute trade',
      'arbitrage this',
      'guaranteed edge',
      'risk-free',
      'auto trade',
      'place order',
    ];
    for (const word of forbidden) {
      expect(text).not.toContain(word);
    }
    // Advisory safety chips must still be visible.
    expect(text).toMatch(/advisory/);
    expect(text).toMatch(/execution.*locked/);
    expect(text).toMatch(/ai executions: 0/);
  });
});
