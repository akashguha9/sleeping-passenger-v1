/**
 * Vitest spec for the Capital Rotation operator page.
 *
 * Pins the contract from Section 11 of the Capital Rotation auto-feed
 * sprint:
 *
 *   * Safety stamp is always visible (RECORD-KEEPING ONLY · NO BROKER
 *     CALL · AI EXECUTIONS = 0).
 *   * Regime banner reflects the mocked portfolio_regime.
 *   * Capacity score is rendered.
 *   * Exit Review Board renders above Buy Admission Board (rotation
 *     first, possession recycle before progression).
 *   * DATA_BLOCKED rows surface their missing_fields so the operator
 *     can fix the source.
 *   * Candidate Feed status panel renders the mocked status.
 *   * Buy Admission Board is non-empty when the mocked feed carries
 *     candidates.
 *   * Empty-state explanation explains *why* the admission board is
 *     empty (no candidate feed loaded, file stale, etc.).
 *   * Theme Slot Board shows used / cap.
 *   * No forbidden execution language ("place order", "broker order",
 *     "AI executed", "auto trade") appears in any rendered board.
 *   * BUY_BLOCKED state shows a "new entries blocked" warning.
 *   * BUY_LIMITED state shows the max-3-entries / max-€50 hint.
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

import CapitalRotationPage from '@/app/capital-rotation/page';

type Snapshot = {
  portfolio_regime: 'BUY_ALLOWED' | 'BUY_LIMITED' | 'BUY_BLOCKED';
  portfolio_capacity_score: number;
  allowed_new_entries: number;
  max_size_per_entry: number;
  max_total_new_capital: number;
  leverage_allowed: number;
  capacity_components: Record<string, number>;
  exit_review_board: any;
  theme_slot_summary: any;
  buy_admission_board: any;
  risk_budget: any;
  generated_at_utc: string;
  source_health: string;
  position_context_status: any;
  candidate_feed_status: any;
  live_mark_summary?: any;
};

function makeSnapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  const base: Snapshot = {
    portfolio_regime: 'BUY_ALLOWED',
    portfolio_capacity_score: 7.6,
    allowed_new_entries: 3,
    max_size_per_entry: 100,
    max_total_new_capital: 300,
    leverage_allowed: 1,
    capacity_components: {
      S_live: 0.9, S_recon: 0.8, S_stop: 0.7, S_cash: 0.8,
      S_theme: 0.7, S_lev: 1.0, P_dup: 0.0, P_unreviewed: 0.0,
      P_dirty: 0.0, P_tp: 0.0, P_stop: 0.0,
    },
    exit_review_board: {
      rows: [
        {
          ticker: 'NVDA',
          economic_exposure_key: 'NVIDIA',
          theme_buckets: ['AI_SEMIS_CLOUD'],
          exit_status: 'HOLD_OK',
          thesis_status: 'THESIS_CONFIRMED',
          live_price: 110,
          stop_loss: 95,
          tp_price: 130,
          pnl_pct: 0.1,
          distance_to_stop_pct: 0.13,
          distance_to_tp_pct: 0.18,
          human_action_required: false,
          reason_codes: ['all_checks_passed'],
          missing_fields: [],
        },
      ],
      counts: { HOLD_OK: 1 },
      duplicate_exposures: [],
      open_position_count: 1,
    },
    theme_slot_summary: {
      themes: [
        {
          theme: 'AI_SEMIS_CLOUD',
          used_weight: 1.0,
          warning_cap: 6,
          hard_cap: 8,
          utilization: 0.125,
          status: 'OK',
          holdings: ['NVDA'],
          weakest_holding_candidates: [],
          allowed_action: 'ADD',
        },
      ],
      over_cap_themes: [],
      near_cap_themes: [],
      any_hard_cap_exceeded: false,
    },
    buy_admission_board: {
      rows: [],
      counts: {},
      candidate_count: 0,
    },
    risk_budget: {
      available_new_risk_budget: 300,
      cash_budget_unknown: false,
      buffers: { stop_buffer: 100, runner_buffer: 50 },
      allowed_new_entries: 3,
      max_size_per_entry: 100,
      max_total_new_capital: 300,
    },
    generated_at_utc: '2026-05-26T08:00:00Z',
    source_health: 'LIVE_VERIFIED',
    position_context_status: {
      open_positions_loaded: 1,
      quality_counts: { COMPLETE: 1, USABLE: 0, PARTIAL: 0, INSUFFICIENT: 0 },
      source_counts: { CANONICAL_DB: 0, MANUAL_LOG: 1, RELEASE_FILE: 0, VERIFIED_HOLDINGS: 0, FALLBACK: 0 },
      reason_codes: ['CONTEXT_MERGED'],
      db_available: true,
      holdings_present: true,
    },
    candidate_feed_status: {
      status: 'NO_CANDIDATE_FILE',
      candidate_count: 0,
      source_files: [],
      reason_codes: ['NO_CANDIDATE_FILE'],
    },
    live_mark_summary: {
      generated_at: '2026-05-26T16:00:00Z',
      aggregate_source_health: 'LIVE_VERIFIED',
      coverage_ratio: 1.0,
      usable_coverage_ratio: 1.0,
      average_quality_score: 0.91,
      requested_tickers: ['NVDA'],
      resolved_tickers: ['NVDA'],
      missing_tickers: [],
      stale_tickers: [],
      provider_status: { yfinance: { ok: true } },
      marks: [{ ticker: 'NVDA' }],
      reason_codes: ['LIVE_MARK_COVERAGE_FULL'],
    },
  };
  return { ...base, ...overrides };
}

function stubFetch(snapshot: Snapshot) {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => snapshot,
    text: async () => JSON.stringify(snapshot),
  } as unknown as Response);
  // @ts-ignore
  globalThis.fetch = spy;
  return spy;
}

describe('CapitalRotationPage', () => {
  beforeEach(() => {
    // @ts-ignore
    globalThis.fetch = undefined;
  });

  it('renders the RECORD-KEEPING ONLY safety stamp', async () => {
    stubFetch(makeSnapshot());
    render(<CapitalRotationPage />);
    const stamp = await screen.findByTestId('record-keeping-stamp');
    const text = (stamp.textContent ?? '').toUpperCase();
    expect(text).toMatch(/RECORD-KEEPING ONLY/);
    expect(text).toMatch(/NO BROKER CALL/);
    expect(text).toMatch(/AI EXECUTIONS = 0/);
  });

  it('renders the Portfolio Regime banner for BUY_ALLOWED', async () => {
    stubFetch(makeSnapshot({ portfolio_regime: 'BUY_ALLOWED' }));
    render(<CapitalRotationPage />);
    const banner = await screen.findByTestId('regime-banner-BUY_ALLOWED');
    expect(banner.textContent ?? '').toMatch(/BUY_ALLOWED/);
  });

  it('renders the Capacity Score', async () => {
    stubFetch(makeSnapshot({ portfolio_capacity_score: 7.6 }));
    render(<CapitalRotationPage />);
    const card = await screen.findByTestId('capacity-card');
    expect(card.textContent ?? '').toMatch(/7\.6/);
  });

  it('renders the Exit Review Board above the Buy Admission Board', async () => {
    stubFetch(makeSnapshot());
    render(<CapitalRotationPage />);
    const exit = await screen.findByTestId('exit-review-board');
    const admission = await screen.findByTestId('buy-admission-board');
    const order = exit.compareDocumentPosition(admission);
    // Bit 4 = DOCUMENT_POSITION_FOLLOWING
    expect(order & 4).toBeTruthy();
  });

  it('renders the missing-field explanation for DATA_BLOCKED rows', async () => {
    const snap = makeSnapshot({
      exit_review_board: {
        rows: [
          {
            ticker: 'XYZ',
            economic_exposure_key: 'XYZ',
            theme_buckets: ['OTHER'],
            exit_status: 'DATA_BLOCKED',
            thesis_status: 'THESIS_UNCHANGED',
            live_price: null,
            stop_loss: null,
            tp_price: null,
            pnl_pct: null,
            distance_to_stop_pct: null,
            distance_to_tp_pct: null,
            human_action_required: true,
            reason_codes: ['data_blocked:live_price,stop_loss'],
            missing_fields: ['live_price', 'stop_loss'],
          },
        ],
        counts: { DATA_BLOCKED: 1 },
        duplicate_exposures: [],
        open_position_count: 1,
      },
    });
    stubFetch(snap);
    render(<CapitalRotationPage />);
    const missing = await screen.findByTestId('exit-row-missing-XYZ');
    const text = (missing.textContent ?? '').toLowerCase();
    expect(text).toMatch(/missing/);
    expect(text).toMatch(/live_price/);
    expect(text).toMatch(/stop_loss/);
  });

  it('renders Candidate Feed Status (NO_CANDIDATE_FILE)', async () => {
    stubFetch(makeSnapshot());
    render(<CapitalRotationPage />);
    const panel = await screen.findByTestId('candidate-feed-panel');
    expect(panel.textContent ?? '').toMatch(/NO_CANDIDATE_FILE/);
  });

  it('renders Candidate Feed Status (CANDIDATES_LOADED) and a non-empty board', async () => {
    const snap = makeSnapshot({
      candidate_feed_status: {
        status: 'CANDIDATES_LOADED',
        candidate_count: 1,
        source_files: ['runtime/release/operator_daily_signal.json'],
        reason_codes: [],
      },
      buy_admission_board: {
        rows: [
          {
            ticker: 'MU',
            economic_exposure_key: 'MICRON',
            theme_buckets: ['AI_SEMIS_CLOUD', 'HIGH_BETA_SPECULATIVE'],
            candidate_admission_score: 0.78,
            buy_admission_class: 'ADDITIVE_OK',
            add_or_replace_recommendation: 'ADD',
            replace_target_ticker: null,
            max_allowed_size: 100,
            max_allowed_leverage: 1.0,
            reason_codes: ['regime_allowed_and_score_strong'],
          },
        ],
        counts: { ADDITIVE_OK: 1 },
        candidate_count: 1,
      },
    });
    stubFetch(snap);
    render(<CapitalRotationPage />);
    const panel = await screen.findByTestId('candidate-feed-panel');
    expect(panel.textContent ?? '').toMatch(/CANDIDATES_LOADED/);
    const board = await screen.findByTestId('buy-admission-board');
    expect(within(board).getByText(/MU/)).toBeTruthy();
    expect(within(board).getByText(/ADDITIVE_OK/)).toBeTruthy();
  });

  it('renders an empty-state explanation when no candidate feed loaded', async () => {
    stubFetch(makeSnapshot());
    render(<CapitalRotationPage />);
    const empty = await screen.findByTestId('buy-admission-empty');
    expect((empty.textContent ?? '').toLowerCase()).toMatch(/no candidate feed loaded/);
  });

  it('renders the Theme Slot Board with used / cap', async () => {
    stubFetch(makeSnapshot());
    render(<CapitalRotationPage />);
    const board = await screen.findByTestId('theme-slot-board');
    expect(board.textContent ?? '').toMatch(/AI_SEMIS_CLOUD/);
    expect(board.textContent ?? '').toMatch(/1\.0\s*\/\s*8/);
  });

  it('does not render forbidden execution language in any board', async () => {
    stubFetch(
      makeSnapshot({
        buy_admission_board: {
          rows: [
            {
              ticker: 'MU',
              economic_exposure_key: 'MICRON',
              theme_buckets: ['AI_SEMIS_CLOUD'],
              candidate_admission_score: 0.78,
              buy_admission_class: 'ADDITIVE_OK',
              add_or_replace_recommendation: 'ADD',
              replace_target_ticker: null,
              max_allowed_size: 100,
              max_allowed_leverage: 1.0,
              reason_codes: ['regime_allowed_and_score_strong'],
            },
          ],
          counts: { ADDITIVE_OK: 1 },
          candidate_count: 1,
        },
      }),
    );
    render(<CapitalRotationPage />);
    await screen.findByTestId('buy-admission-board');
    // Words used as positive prohibitions in safety disclaimers (e.g.
    // "no broker call", "ai executions = 0") are OK; the page must NOT
    // imply *active* execution.
    const body = (document.body.textContent ?? '').toLowerCase();
    for (const forbidden of ['place order', 'broker order', 'ai executed', 'auto-trading']) {
      expect(body).not.toContain(forbidden);
    }
  });

  it('renders BUY_BLOCKED warning copy when the regime is blocked', async () => {
    stubFetch(makeSnapshot({ portfolio_regime: 'BUY_BLOCKED' }));
    render(<CapitalRotationPage />);
    const warning = await screen.findByTestId('buy-blocked-warning');
    const text = (warning.textContent ?? '').toLowerCase();
    expect(text).toMatch(/new entries blocked/);
  });

  it('renders BUY_LIMITED warning copy when the regime is limited', async () => {
    stubFetch(makeSnapshot({
      portfolio_regime: 'BUY_LIMITED',
      max_size_per_entry: 50,
      max_total_new_capital: 150,
    }));
    render(<CapitalRotationPage />);
    const warning = await screen.findByTestId('buy-limited-warning');
    const text = (warning.textContent ?? '').toLowerCase();
    expect(text).toMatch(/max 3 entries/);
    expect(text).toMatch(/€50/);
  });

  it('renders the Live Mark Panel with LIVE_VERIFIED state', async () => {
    stubFetch(makeSnapshot());
    render(<CapitalRotationPage />);
    const panel = await screen.findByTestId('live-mark-panel');
    expect(panel.textContent ?? '').toMatch(/Live Mark Coverage/);
    const health = await screen.findByTestId('live-mark-health-LIVE_VERIFIED');
    expect(health.textContent ?? '').toMatch(/LIVE_VERIFIED/);
    const headline = await screen.findByTestId('live-mark-headline');
    expect((headline.textContent ?? '').toLowerCase()).toMatch(/live marks verified/);
  });

  it('renders DELAYED_BUT_USABLE wording when marks are delayed', async () => {
    stubFetch(
      makeSnapshot({
        live_mark_summary: {
          generated_at: '2026-05-26T16:00:00Z',
          aggregate_source_health: 'DELAYED_BUT_USABLE',
          coverage_ratio: 1.0,
          usable_coverage_ratio: 0.9,
          average_quality_score: 0.68,
          requested_tickers: ['NVDA'],
          resolved_tickers: ['NVDA'],
          missing_tickers: [],
          stale_tickers: [],
          provider_status: {},
          marks: [],
          reason_codes: ['DELAYED_BUT_USABLE'],
        },
      }),
    );
    render(<CapitalRotationPage />);
    const headline = await screen.findByTestId('live-mark-headline');
    expect((headline.textContent ?? '').toLowerCase()).toMatch(/delayed marks usable/);
  });

  it('renders NO_LIVE_MARKS wording and the missing ticker list', async () => {
    stubFetch(
      makeSnapshot({
        live_mark_summary: {
          generated_at: '2026-05-26T16:00:00Z',
          aggregate_source_health: 'NO_LIVE_MARKS',
          coverage_ratio: 0.0,
          usable_coverage_ratio: 0.0,
          average_quality_score: 0.0,
          requested_tickers: ['NVDA'],
          resolved_tickers: [],
          missing_tickers: ['NVDA'],
          stale_tickers: [],
          provider_status: {},
          marks: [],
          reason_codes: ['NO_LIVE_MARKS'],
        },
      }),
    );
    render(<CapitalRotationPage />);
    const headline = await screen.findByTestId('live-mark-headline');
    expect((headline.textContent ?? '').toLowerCase()).toMatch(/no usable live marks/);
    const missing = await screen.findByTestId('live-mark-missing-tickers');
    expect(missing.textContent ?? '').toMatch(/NVDA/);
  });

  it('renders the stale-ticker warning when marks are stale', async () => {
    stubFetch(
      makeSnapshot({
        live_mark_summary: {
          generated_at: '2026-05-26T16:00:00Z',
          aggregate_source_health: 'PARTIAL',
          coverage_ratio: 0.5,
          usable_coverage_ratio: 0.4,
          average_quality_score: 0.5,
          requested_tickers: ['NVDA'],
          resolved_tickers: ['NVDA'],
          missing_tickers: [],
          stale_tickers: ['NVDA'],
          provider_status: {},
          marks: [],
          reason_codes: ['SOME_MARKS_STALE'],
        },
      }),
    );
    render(<CapitalRotationPage />);
    const stale = await screen.findByTestId('live-mark-stale-tickers');
    expect(stale.textContent ?? '').toMatch(/NVDA/);
  });

  it('shows DATA_BLOCKED row explanation when live mark is missing', async () => {
    stubFetch(
      makeSnapshot({
        exit_review_board: {
          rows: [
            {
              ticker: 'XYZ',
              economic_exposure_key: 'XYZ',
              theme_buckets: ['OTHER'],
              exit_status: 'DATA_BLOCKED',
              thesis_status: 'THESIS_UNCHANGED',
              live_price: null,
              display_live_price: null,
              mechanical_live_price_usable: false,
              live_mark_source_health: 'NO_LIVE_MARK',
              stop_loss: 90,
              tp_price: 130,
              pnl_pct: null,
              distance_to_stop_pct: null,
              distance_to_tp_pct: null,
              human_action_required: true,
              reason_codes: ['data_blocked:live_price', 'LIVE_MARK_MISSING'],
              missing_fields: ['live_price'],
            },
          ],
          counts: { DATA_BLOCKED: 1 },
          duplicate_exposures: [],
          open_position_count: 1,
        },
      }),
    );
    render(<CapitalRotationPage />);
    const missing = await screen.findByTestId('exit-row-missing-XYZ');
    expect((missing.textContent ?? '').toLowerCase()).toMatch(/live_price/);
  });

  it('Position Context status counts still render below Live Mark Panel', async () => {
    stubFetch(makeSnapshot({
      position_context_status: {
        open_positions_loaded: 4,
        quality_counts: { COMPLETE: 2, USABLE: 1, PARTIAL: 1, INSUFFICIENT: 0 },
        source_counts: { CANONICAL_DB: 0, MANUAL_LOG: 3, RELEASE_FILE: 0, VERIFIED_HOLDINGS: 1, FALLBACK: 0 },
        reason_codes: ['CONTEXT_MERGED'],
        db_available: true,
        holdings_present: true,
      },
    }));
    render(<CapitalRotationPage />);
    const panel = await screen.findByTestId('position-context-panel');
    const text = panel.textContent ?? '';
    expect(text).toMatch(/4 open loaded/);
    expect(text).toMatch(/COMPLETE/);
  });
});
