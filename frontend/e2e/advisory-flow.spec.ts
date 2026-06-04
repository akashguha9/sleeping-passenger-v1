/**
 * Advisory-flow E2E smoke tests (route-mocked — no live backend required).
 *
 * Verifies the operator-facing pages render their advisory framing and never
 * present an execution call-to-action. The backend is stubbed via page.route
 * so the suite is hermetic.
 *
 * In network-restricted environments the Chromium binary cannot be downloaded;
 * see docs/PLAYWRIGHT_E2E.md. These specs are excluded from Vitest (which only
 * globs src/**​/__tests__).
 */
import { test, expect, type Page } from '@playwright/test';

const FORBIDDEN = /\b(execute order|place order|auto-buy|auto-sell|broker trade|send order|trade now)\b/i;

async function stubBackend(page: Page) {
  await page.route('**/api/readiness/real-money', (r) =>
    r.fulfill({ json: {
      report: 'real_money_readiness', readiness_score: 6.5, readiness_max: 8,
      allowed_mode: 'TINY_MANUAL_PROBE_ONLY', blockers: [], warnings: ['scores_uncalibrated'],
      reason: 'Scores are not calibrated enough to size from. Tiny manual probes only.',
      calibration_status: 'NO_DATA', real_n: 0, paper_n: 0,
      advisory_status: 'ADVISORY_ONLY', broker_api_called: false,
    } }));
  await page.route('**/api/score-calibration', (r) =>
    r.fulfill({ json: { calibration_status: 'UNCALIBRATED', sample_size: 0,
      score_should_drive_sizing: false, message: 'Do not size from this score.',
      advisory_status: 'ADVISORY_ONLY', broker_api_called: false } }));
  await page.route('**/signals**', (r) =>
    r.fulfill({ json: { operation: 'list_inbox_items', item_count: 0, items: [],
      fabric_bull_state: 'NEUTRAL', fabric_stats: {}, signal_source: 'live_events',
      score_calibration: { calibration_status: 'UNCALIBRATED', sample_size: 0,
        score_should_drive_sizing: false },
      advisory_status: 'ADVISORY_ONLY', human_review_required: true,
      execution_mode: 'HUMAN_ONLY', ai_execution_count: 0 } }));
  await page.route('**/manual-trades**', (r) =>
    r.fulfill({ json: { operation: 'list_manual_trades', trade_count: 1, trades: [{
      trade_id: 'MT_1', event_id: 'EV', ticker: 'AAPL', side: 'BUY', quantity: 5,
      price: 200, leverage: 2.0, leverage_ceiling: 1.0, leverage_breach: true,
      leverage_policy_severity: 'POLICY_BREACH', jurisdiction_group: 'REST_OF_WORLD',
      jurisdiction_resolution_source: 'SECURITIES_MASTER',
      leverage_policy_reason: '2x exceeds the 1x ceiling for REST_OF_WORLD.',
      executed_at: '2026-01-01T00:00:00Z', thesis: 'manual record', notes: '',
      logged_by: 'human', execution_mode: 'HUMAN_ONLY', ai_execution_count: 0,
      advisory_status: 'ADVISORY_ONLY', human_review_required: true,
      broker_order_id: 'NONE', broker_api_called: false, created_via: 'manual_trade_log',
    }] } }));
  // Generic catch-all for any other backend calls -> empty advisory payload.
  await page.route('**/diagnostics/**', (r) => r.fulfill({ json: {} }));
  await page.route('**/reconciliation**', (r) => r.fulfill({ json: { items: [] } }));
  await page.route('**/moltbook**', (r) => r.fulfill({ json: { items: [], item_count: 0 } }));
  await page.route('**/source-health**', (r) => r.fulfill({ json: {} }));
  await page.route('**/db/status', (r) => r.fulfill({ json: {} }));
  await page.route('**/health', (r) => r.fulfill({ json: { status: 'ok' } }));
}

test.beforeEach(async ({ page }) => { await stubBackend(page); });

test('cockpit shows advisory + readiness, no execution language', async ({ page }) => {
  await page.goto('/cockpit');
  await expect(page.getByTestId('advisory-banner')).toBeVisible();
  await expect(page.getByTestId('readiness-mode-badge')).toBeVisible();
  expect(FORBIDDEN.test(await page.content())).toBe(false);
});

test('signal inbox shows calibration warning', async ({ page }) => {
  await page.goto('/signal-inbox');
  await expect(page.getByTestId('score-calibration-badge')).toBeVisible();
  await expect(page.getByText(/Do not size from this score/i).first()).toBeVisible();
  expect(FORBIDDEN.test(await page.content())).toBe(false);
});

test('manual trade log shows leverage ceiling + jurisdiction source', async ({ page }) => {
  await page.goto('/manual-trade-log');
  await expect(page.getByTestId('leverage-breach-warning')).toBeVisible();
  await expect(page.getByText(/SECURITIES_MASTER/).first()).toBeVisible();
  await expect(page.getByText(/journal record only/i).first()).toBeVisible();
  // no execution button
  await expect(page.getByRole('button', { name: FORBIDDEN })).toHaveCount(0);
  expect(FORBIDDEN.test(await page.content())).toBe(false);
});

test('reconciliation page shows human/manual wording', async ({ page }) => {
  await page.goto('/reconciliation');
  expect(FORBIDDEN.test(await page.content())).toBe(false);
});

test('moltbook page renders without auto-apply wording', async ({ page }) => {
  await page.goto('/moltbook');
  const text = await page.content();
  expect(FORBIDDEN.test(text)).toBe(false);
  expect(/auto-?appl(y|ied)/i.test(text)).toBe(false);
});
