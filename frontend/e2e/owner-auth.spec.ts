/**
 * Owner-auth E2E proofs (route-mocked — no live backend required).
 *
 * Emulates the token-gated backend contract (all journal reads/writes
 * 401 without `Authorization: Bearer <valid>`) and proves the frontend:
 *   1. loads;
 *   2. shows the locked/empty state with no token;
 *   3. stays locked with a wrong token;
 *   4. renders protected data once the valid token is saved;
 *   5. never stores the token in localStorage (sessionStorage only);
 *   6. masks the token input and never echoes the raw token into the DOM.
 *
 * The "valid token" below is a synthetic E2E fixture, not a real secret.
 */
import { test, expect, type Page } from '@playwright/test';

const VALID_TOKEN = 'e2e-valid-owner-token-fixture';
const WRONG_TOKEN = 'e2e-wrong-token-fixture';
const PROTECTED_TICKER = 'E2EAAPL';

const ADVISORY = {
  advisory_status: 'ADVISORY_ONLY',
  execution_mode: 'HUMAN_ONLY',
  execution_gate: 'LOCKED',
  ai_execution_count: 0,
  broker_api_called: false,
  human_review_required: true,
};

function authorized(headers: Record<string, string>): boolean {
  return headers['authorization'] === `Bearer ${VALID_TOKEN}`;
}

/** Stub the token-gated backend: 401 everywhere without the valid bearer. */
async function stubTokenGatedBackend(page: Page) {
  await page.route('**/manual-trades**', (route) => {
    const headers = route.request().headers();
    if (!authorized(headers)) {
      return route.fulfill({
        status: 401,
        json: { status_code: 401, error: 'missing bearer token', ...ADVISORY },
      });
    }
    return route.fulfill({
      json: {
        operation: 'list_manual_trades',
        trades: [
          {
            trade_id: 'TRADE_E2E_1',
            event_id: 'EV_E2E_1',
            ticker: PROTECTED_TICKER,
            side: 'BUY',
            quantity: 1,
            price: 100,
            trade_origin: 'manual_trade_log',
            reconciliation_status: 'PENDING',
            logged_at: '2026-06-01T00:00:00Z',
            ...ADVISORY,
          },
        ],
        ...ADVISORY,
      },
    });
  });
  // Everything else the page touches: 401 without token, harmless empties with.
  await page.route('**/self-test/**', (route) => {
    const ok = authorized(route.request().headers());
    return route.fulfill(
      ok
        ? { json: { items: [], queue: [], ...ADVISORY } }
        : { status: 401, json: { status_code: 401, error: 'missing bearer token', ...ADVISORY } },
    );
  });
  await page.route('**/source-health**', (route) =>
    route.fulfill({ json: { sources: [], stale_sources: [], ...ADVISORY } }),
  );
  await page.route('**/api/**', (route) =>
    route.fulfill({ json: { ...ADVISORY } }),
  );
}

test.describe('owner-auth gate', () => {
  test.beforeEach(async ({ page }) => {
    await stubTokenGatedBackend(page);
  });

  test('frontend loads and shows the locked/empty state without a token', async ({
    page,
  }) => {
    await page.goto('/manual-trade-log');
    await expect(page.getByTestId('local-api-token-panel')).toBeVisible();
    await expect(page.getByTestId('token-status')).toHaveText('not set');
    // Protected data must NOT render.
    await expect(page.getByText(PROTECTED_TICKER)).toHaveCount(0);
  });

  test('wrong token still shows no protected data', async ({ page }) => {
    await page.goto('/manual-trade-log');
    await page.getByTestId('token-input').fill(WRONG_TOKEN);
    await page.getByTestId('token-save-btn').click();
    await expect(page.getByTestId('token-status')).toHaveText('set');
    await page.reload();
    await expect(page.getByText(PROTECTED_TICKER)).toHaveCount(0);
  });

  test('valid token unlocks a harmless protected read', async ({ page }) => {
    await page.goto('/manual-trade-log');
    await page.getByTestId('token-input').fill(VALID_TOKEN);
    await page.getByTestId('token-save-btn').click();
    await expect(page.getByTestId('token-status')).toHaveText('set');
    await page.reload();
    await expect(page.getByText(PROTECTED_TICKER).first()).toBeVisible();
  });

  test('token lives in sessionStorage only — never localStorage', async ({
    page,
  }) => {
    await page.goto('/manual-trade-log');
    await page.getByTestId('token-input').fill(VALID_TOKEN);
    await page.getByTestId('token-save-btn').click();
    const storage = await page.evaluate(() => ({
      session: window.sessionStorage.getItem('mvp_api_token'),
      localKeys: Object.keys(window.localStorage),
      localDump: JSON.stringify(window.localStorage),
    }));
    expect(storage.session).toBe(VALID_TOKEN);
    expect(storage.localDump).not.toContain(VALID_TOKEN);
    for (const key of storage.localKeys) {
      expect(key).not.toBe('mvp_api_token');
    }
  });

  test('token input is masked and the raw token never appears in the DOM', async ({
    page,
  }) => {
    await page.goto('/manual-trade-log');
    const input = page.getByTestId('token-input');
    await expect(input).toHaveAttribute('type', 'password');
    await input.fill(VALID_TOKEN);
    await page.getByTestId('token-save-btn').click();
    // After save the panel renders a masked preview, not the token.
    await expect(page.getByTestId('token-preview')).toBeVisible();
    const html = await page.content();
    expect(html).not.toContain(VALID_TOKEN);
  });
});
