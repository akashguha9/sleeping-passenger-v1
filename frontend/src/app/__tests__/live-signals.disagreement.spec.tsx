/**
 * Vitest spec for the Disagreements first-class source tab.
 *
 * Covers (10/10 sprint — Section I + new sprint #1):
 *   - Disagreements tab exists and sits beside Kalshi in the filter strip.
 *   - Selecting Disagreements requests source=prediction_market_disagreement.
 *   - Disagreement cards display Polymarket vs Kalshi probabilities, gap,
 *     pair type, and status.
 *   - ALERT status shows review-required + advisory-only wording.
 *   - SAME_EVENT_DIFFERENT_THRESHOLD pairs show BLOCKED/WATCH + reasons.
 *   - Polymarket filter does NOT show disagreement alerts.
 *   - Kalshi filter does NOT show disagreement alerts.
 *   - All Sources includes disagreement alerts.
 *   - Forbidden customer-facing trading language is absent.
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
  getKalshiSourceHealth: vi.fn().mockResolvedValue(null),
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

function makeDisagreementEvent(overrides: any = {}) {
  return {
    id: overrides.id ?? 700,
    event_id: overrides.event_id ?? 'poly_btc__kalshi_btc',
    source_name: 'prediction_market_disagreement',
    raw_payload: {
      pair_id: 'poly_btc__kalshi_btc',
      signal_class: 'CROSS_VENUE_DISAGREEMENT',
      customer_label: 'Prediction Market Disagreement Alert',
      polymarket_title: 'What price will Bitcoin hit in May?',
      kalshi_title: 'How high will Bitcoin get in May?',
      polymarket_probability: 0.62,
      kalshi_probability: 0.54,
      probability_gap: 0.08,
      disagreement_threshold: 0.05,
      pair_type: 'SAME_EVENT_SAME_RESOLUTION',
      status: 'ALERT',
      disagreement_triggered: true,
      resolution_mismatch_reasons: [],
      probability_source_polymarket: 'implied_probability',
      probability_source_kalshi: 'implied_probability',
      pair_score_components: {
        text_score: 0.82,
        entity_score: 1.0,
        category_score: 1.0,
        date_score: 0.75,
        threshold_score: 1.0,
        resolution_score: 1.0,
        embedding_score: 0.68,
        final_score: 0.89,
      },
      embedding_provider: 'deterministic',
      embedding_model: 'hashed-token-histogram-16',
      embedding_available: true,
      embedding_status_reason: '',
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

function makeBlockedDisagreementEvent() {
  return makeDisagreementEvent({
    id: 701,
    event_id: 'poly_btc150__kalshi_btc100',
    raw_payload: {
      pair_id: 'poly_btc150__kalshi_btc100',
      polymarket_title: 'Will Bitcoin hit $150k in May?',
      kalshi_title: 'Will Bitcoin close above $100k on May 31?',
      polymarket_probability: 0.80,
      kalshi_probability: 0.18,
      probability_gap: 0.62,
      pair_type: 'SAME_EVENT_DIFFERENT_THRESHOLD',
      status: 'DIAGNOSTIC',
      disagreement_triggered: false,
      resolution_mismatch_reasons: [
        'resolution_style_mismatch:poly=touch/kalshi=close',
        'threshold_mismatch:poly=[$150k]/kalshi=[$100k]',
      ],
    },
  });
}

function makeKalshiEvent() {
  return {
    id: 100,
    event_id: 'kalshi_btcmay',
    source_name: 'kalshi',
    raw_payload: {
      source: 'kalshi',
      source_label: 'Kalshi',
      source_market_id: 'BTCMAY-2026',
      title: 'How high will Bitcoin get in May?',
      category: 'Crypto',
      yes_price: 0.42,
      implied_probability: 0.42,
      advisory_status: 'ADVISORY_ONLY',
      execution_permission: 'ADVISORY_ONLY',
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

describe('Live Signals — Disagreements first-class tab', () => {
  it('renders the Disagreements tab beside Kalshi', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [],
      count: 0,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);

    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    const kalshiBtn = screen.getByRole('button', { name: 'Kalshi' });
    const disagreementsBtn = screen.getByRole('button', { name: 'Disagreements' });
    expect(
      kalshiBtn.compareDocumentPosition(disagreementsBtn) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('selecting Disagreements requests source=prediction_market_disagreement', async () => {
    const seenSources: (string | undefined)[] = [];
    mockLiveSignals.mockImplementation(async (source?: string) => {
      seenSources.push(source);
      const events =
        source === 'prediction_market_disagreement' ? [makeDisagreementEvent()] : [];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    (screen.getByRole('button', { name: 'Disagreements' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('disagreement-detail-block'));
    expect(seenSources).toContain('prediction_market_disagreement');
  });

  it('Disagreement card shows Polymarket + Kalshi rows, gap, pair type, ALERT status', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [makeDisagreementEvent()],
      count: 1,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    (screen.getByRole('button', { name: 'Disagreements' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('disagreement-detail-block'));
    const block = screen.getAllByTestId('disagreement-detail-block')[0];
    expect(block.textContent).toMatch(/Polymarket/);
    expect(block.textContent).toMatch(/Kalshi/);
    expect(block.textContent).toMatch(/62\.0%/);
    expect(block.textContent).toMatch(/54\.0%/);
    expect(block.textContent).toMatch(/8\.0 percentage points/);
    expect(block.textContent).toMatch(/SAME_EVENT_SAME_RESOLUTION/);

    const card = screen.getAllByTestId('signal-event-card')[0];
    const cardText = (card.textContent || '').toLowerCase();
    // ALERT status + advisory wording must be visible.
    expect(cardText).toMatch(/alert/);
    expect(cardText).toMatch(/advisory/);
    expect(cardText).toMatch(/human.review.required/);
    expect(cardText).toMatch(/execution.*locked/);
  });

  it('BLOCKED / mismatch pair displays WATCH + mismatch reasons', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [makeBlockedDisagreementEvent()],
      count: 1,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    (screen.getByRole('button', { name: 'Disagreements' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('disagreement-detail-block'));
    const block = screen.getAllByTestId('disagreement-detail-block')[0];
    expect(block.textContent).toMatch(/SAME_EVENT_DIFFERENT_THRESHOLD/);
    expect(block.textContent).toMatch(/Blocked by resolution mismatch/i);
    expect(block.textContent).toMatch(/resolution_style_mismatch/);
    expect(block.textContent).toMatch(/threshold_mismatch/);
    // Big gap, but the status pill must NOT say ALERT.
    expect(block.textContent).not.toMatch(/\bAlert\b/);
  });

  it('All Sources includes disagreement alerts alongside Polymarket + Kalshi', async () => {
    mockLiveSignals.mockImplementation(async (_source?: string) => {
      const events = [makePolyEvent(), makeKalshiEvent(), makeDisagreementEvent()];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'All Sources' }));
    (screen.getByRole('button', { name: 'All Sources' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('signal-event-card'));
    const blocks = screen.queryAllByTestId('disagreement-detail-block');
    expect(blocks.length).toBeGreaterThanOrEqual(1);
  });

  it('Polymarket tab does NOT show disagreement alerts', async () => {
    mockLiveSignals.mockImplementation(async (source?: string) => {
      const events = source === 'polymarket' ? [makePolyEvent()] : [];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Polymarket' }));
    (screen.getByRole('button', { name: 'Polymarket' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('signal-event-card'));
    expect(screen.queryAllByTestId('disagreement-detail-block')).toHaveLength(0);
  });

  it('Kalshi tab does NOT show disagreement alerts', async () => {
    mockLiveSignals.mockImplementation(async (source?: string) => {
      const events = source === 'kalshi' ? [makeKalshiEvent()] : [];
      return { live_signal_events: events, count: events.length, ...SAFETY };
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Kalshi' }));
    (screen.getByRole('button', { name: 'Kalshi' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('signal-event-card'));
    expect(screen.queryAllByTestId('disagreement-detail-block')).toHaveLength(0);
  });

  it('renders pair_score_components, embedding metadata, and probability sources', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [makeDisagreementEvent()],
      count: 1,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    (screen.getByRole('button', { name: 'Disagreements' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('pair-score-components'));
    const componentsBlock = screen.getAllByTestId('pair-score-components')[0];
    expect(componentsBlock.textContent).toMatch(/Pair score components/i);
    // Per-axis scores render with two decimals.
    expect(componentsBlock.textContent).toMatch(/0\.82/);
    expect(componentsBlock.textContent).toMatch(/0\.68/);
    // Final score visible.
    expect(screen.getByTestId('pair-score-final_score').textContent).toMatch(/0\.89/);
    // Embedding provider + model + availability.
    expect(screen.getByTestId('pair-score-embedding-provider').textContent).toMatch(
      /deterministic/,
    );
    expect(screen.getByTestId('pair-score-embedding-model').textContent).toMatch(
      /hashed-token-histogram-16/,
    );
    expect(screen.getByTestId('pair-score-embedding-available').textContent).toMatch(
      /true/,
    );
    // Probability source lines.
    expect(
      screen.getByTestId('disagreement-poly-prob-source').textContent,
    ).toMatch(/implied_probability/);
    expect(
      screen.getByTestId('disagreement-kalshi-prob-source').textContent,
    ).toMatch(/implied_probability/);
  });

  it('shows fallback line + warning when embedding is unavailable', async () => {
    const event = makeDisagreementEvent({
      raw_payload: {
        embedding_provider: 'deterministic_fallback_from_real',
        embedding_model: 'hashed-token-histogram-16',
        embedding_available: false,
        embedding_status_reason: 'real_provider_unavailable:no_api_key',
      },
    });
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [event],
      count: 1,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    (screen.getByRole('button', { name: 'Disagreements' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('pair-score-embedding-fallback'));
    const fallback = screen.getAllByTestId('pair-score-embedding-fallback')[0];
    expect(fallback.textContent).toMatch(/Embedding unavailable/i);
    expect(fallback.textContent).toMatch(/deterministic/i);
    expect(fallback.textContent).toMatch(/real_provider_unavailable/);
  });

  it('falls back gracefully when pair_score_components are absent', async () => {
    const event = makeDisagreementEvent({
      raw_payload: {
        pair_score_components: undefined,
        embedding_provider: undefined,
        embedding_model: undefined,
        embedding_available: undefined,
      },
    });
    delete (event.raw_payload as any).pair_score_components;
    delete (event.raw_payload as any).embedding_provider;
    delete (event.raw_payload as any).embedding_model;
    delete (event.raw_payload as any).embedding_available;

    mockLiveSignals.mockResolvedValue({
      live_signal_events: [event],
      count: 1,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    (screen.getByRole('button', { name: 'Disagreements' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('pair-score-components-fallback'));
    const fallback = screen.getAllByTestId('pair-score-components-fallback')[0];
    expect(fallback.textContent).toMatch(/Pair score components unavailable/i);
  });

  it('Disagreement card never uses Buy / Sell / Execute / Arbitrage language', async () => {
    mockLiveSignals.mockResolvedValue({
      live_signal_events: [makeDisagreementEvent(), makeBlockedDisagreementEvent()],
      count: 2,
      ...SAFETY,
    });

    render(<LiveSignalsPage />);
    await waitFor(() => screen.getByRole('button', { name: 'Disagreements' }));
    (screen.getByRole('button', { name: 'Disagreements' }) as HTMLButtonElement).click();

    await waitFor(() => screen.getAllByTestId('disagreement-detail-block'));
    for (const card of screen.getAllByTestId('signal-event-card')) {
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
    }
  });
});
