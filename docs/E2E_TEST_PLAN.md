# E2E_TEST_PLAN — exact future frontend / Playwright spec

> Status: **PLAN, NOT RUN.**
>
> As of the Day 1-10 sprint, `frontend/package.json` ships with no test
> tooling (no Vitest, no Jest, no React Testing Library, no Playwright).
> No new packages were installed during this sprint -- doing so requires
> explicit user approval. The work below is the blueprint for the next
> operator who is approved to wire frontend testing in.

## Why this doc exists

The backend has ~2900 pytest cases. The frontend has zero automated
tests. That's the single biggest remaining gap in the survival floor:
a green pytest run does not prove the demo works.

This doc fixes the absence of a plan, not the absence of tests.

## Proposed tool choices

| Concern | Tool | Why |
|---|---|---|
| Unit / component | Vitest + React Testing Library + `jsdom` | Fast, Vite-friendly, idiomatic for Next 14 app router |
| E2E | Playwright | First-party Chromium/WebKit/Firefox, good CI story, headless by default |
| Mock backend | `msw` (Mock Service Worker) | Intercepts `fetch` so component tests don't need a live backend |
| Lint of test files | `next lint` (already in place) | No new config needed |

Install commands (DO NOT RUN without approval):

```powershell
cd frontend
npm install --save-dev vitest @vitejs/plugin-react jsdom
npm install --save-dev @testing-library/react @testing-library/jest-dom @testing-library/user-event
npm install --save-dev msw
npm install --save-dev @playwright/test
npx playwright install --with-deps chromium
```

Approximate disk cost: ~250 MB additional `node_modules/`.

## package.json scripts to add

```jsonc
{
  "scripts": {
    "test":            "vitest run",
    "test:watch":      "vitest",
    "test:coverage":   "vitest run --coverage",
    "e2e":             "playwright test",
    "e2e:headed":      "playwright test --headed",
    "e2e:install":     "playwright install --with-deps chromium"
  }
}
```

## Component unit tests (Vitest + RTL)

Target files and what each pins down:

### `frontend/src/components/__tests__/BullStateBadge.test.tsx`

- renders the state label (`MIURA`, `MURCIÉLAGO`, etc.)
- `title` attribute contains the plain-English meaning
- `aria-label` contains the plain-English meaning
- unknown / null / undefined state does not crash; renders a fallback
- advisory tone (no language implying execution permission)

### `frontend/src/components/__tests__/AdvisoryOnlyBadge.test.tsx`

- always renders the string "ADVISORY_ONLY"
- visible against both light and dark backgrounds (snapshot)
- has an accessible name

### `frontend/src/components/__tests__/NoExecutionBanner.test.tsx`

- renders the "no broker API" copy
- includes `AI executions: 0`
- is always visible (no `hidden`/`aria-hidden` regressions)

### `frontend/src/components/__tests__/ManualTradeLogForm.test.tsx`

- empty submit shows validation errors (event_id, ticker, side, quantity, price required)
- quantity > 0 enforced
- leverage between 1.0 and 25.0 inclusive
- advisory copy present on the form (`record-keeping only` or equivalent)
- successful submit calls the `onSubmit` / API handler exactly once
- 401 response surfaces a visible error, not a silent fail
- 500 response surfaces a visible error
- form does not auto-execute or autosubmit

### `frontend/src/components/__tests__/SignalCard.test.tsx`

- renders ticker, state badge, priority score
- next-human-action badge present (IGNORE / HAVE_A_LOOK / WATCHLIST / etc.)
- click navigates to the detail route (or fires the prop callback)

### `frontend/src/components/__tests__/MockFallbackBanner.test.tsx`
(or wherever the `BACKEND OFFLINE` / `MOCK_FALLBACK` copy lives)

- when API returns 5xx / no response, banner renders
- when API returns 200 with `truth_source="sqlite"`, banner is absent
- when API returns 200 with `truth_source="legacy_fabric"` or
  `"jsonl_fallback"`, a softer "fallback in use" cue is rendered
  (this is the persistence-truth signal from
  `docs/PERSISTENCE_MODEL.md`)
- mock data is never rendered without a visible cue

### `frontend/src/lib/__tests__/apiClient.test.ts`

- includes `Authorization: Bearer <token>` only when `NEXT_PUBLIC_API_TOKEN`
  is set (if applicable)
- handles 401 by surfacing a typed error
- handles network failure by surfacing a typed error (not throwing
  uncaught in a render)

## Canonical E2E spec (Playwright)

`frontend/e2e/canonical-demo.spec.ts`

This spec follows the canonical demo walkthrough from `DEMO.md`. Each
step is a single assertion. If any assertion fails, the demo is not
ready.

```ts
import { test, expect } from '@playwright/test';

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000';

test.describe('canonical demo journey', () => {
  test('1. dashboard loads with safety copy visible', async ({ page }) => {
    await page.goto(BASE);
    await expect(page.getByText('ADVISORY_ONLY')).toBeVisible();
    await expect(page.getByText('HUMAN_ONLY')).toBeVisible();
    await expect(page.getByText(/AI executions:\s*0/i)).toBeVisible();
  });

  test('2. backend status is visible (green or BACKEND OFFLINE)', async ({ page }) => {
    await page.goto(BASE);
    const live = page.getByText(/connected/i);
    const offline = page.getByText(/BACKEND OFFLINE/i);
    await expect(live.or(offline)).toBeVisible();
  });

  test('3. signal inbox renders or shows mock-fallback banner', async ({ page }) => {
    await page.goto(`${BASE}/signal-inbox`);
    const items = page.locator('[data-testid="signal-card"]');
    const banner = page.getByText(/MOCK_FALLBACK|BACKEND OFFLINE/i);
    await expect(items.first().or(banner)).toBeVisible();
  });

  test('4. signal detail page loads without crash', async ({ page }) => {
    await page.goto(`${BASE}/signal-inbox`);
    const firstCard = page.locator('[data-testid="signal-card"]').first();
    if (await firstCard.isVisible()) {
      await firstCard.click();
      await expect(page.getByText('ADVISORY_ONLY')).toBeVisible();
    } else {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No signals available (mock fallback). Detail page not exercised.',
      });
    }
  });

  test('5. manual trade log form is visible with required validation', async ({ page }) => {
    await page.goto(`${BASE}/manual-trade-log`);
    await expect(page.getByRole('heading', { name: /manual trade log/i })).toBeVisible();
    await expect(page.getByText(/record-keeping only/i)).toBeVisible();
  });

  test('6. reconciliation page loads', async ({ page }) => {
    await page.goto(`${BASE}/reconciliation`);
    await expect(page.getByRole('heading', { name: /reconciliation/i })).toBeVisible();
  });

  test('7. moltbook page loads', async ({ page }) => {
    await page.goto(`${BASE}/moltbook`);
    await expect(page.getByRole('heading', { name: /moltbook/i })).toBeVisible();
  });

  test('8. exports page lists CSV downloads', async ({ page }) => {
    await page.goto(`${BASE}/exports`);
    await expect(page.getByText(/csv/i).first()).toBeVisible();
  });

  test('9. no broker-execution messaging anywhere on the dashboard', async ({ page }) => {
    await page.goto(BASE);
    await expect(page.getByText(/place order|broker order placed|live execution/i)).toHaveCount(0);
  });

  test('10. mock fallback is visually distinct from canonical data', async ({ page }) => {
    await page.goto(`${BASE}/signal-inbox`);
    const banner = page.getByText(/MOCK_FALLBACK|BACKEND OFFLINE/i);
    if (await banner.isVisible()) {
      // amber/yellow banner expected; assert non-default visual prominence
      const color = await banner.evaluate(el => getComputedStyle(el).color);
      expect(color).not.toEqual('rgb(0, 0, 0)');
    }
  });
});
```

## Skip / fallback rules

E2E tests must NOT depend on:

- a live external data API (NewsAPI, xAI, Polymarket, etc.)
- a non-empty `runtime/mvp_local.db`
- the user being on Windows specifically

If the backend isn't running, the suite should either:

1. start the backend itself via Playwright's `webServer` config and a
   short startup probe, OR
2. assert against the mock-fallback view, with `data-testid="mock-fallback"`
   driving the assertion path.

## CI wiring (later)

Add `.github/workflows/frontend.yml` with two jobs:

- `unit`: `npm ci && npm run lint && npm test -- --reporter=dot`
- `e2e`: `npm ci && npx playwright install --with-deps chromium && npm run e2e`

Gate PR merges on `unit`. Treat `e2e` as advisory until it's been
stable for ~2 weeks of green runs.

## What this plan deliberately omits

- Visual regression testing (Percy / Chromatic) -- premature for a
  single-screen-at-a-time UI.
- Performance budgets -- this is a localhost tool.
- Cross-browser parity -- Chromium-only is sufficient for the demo
  audience.

## Definition of "done" for the next operator

This plan is complete when:

- [ ] `npm test` runs at least one Vitest case, exits 0
- [ ] `npm run e2e` runs `canonical-demo.spec.ts`, exits 0 (with backend running)
- [ ] CI runs both on every push and blocks merge on `unit`
- [ ] `TESTING.md` is updated to delete the "no frontend tests" caveat

Until then, the manual smoke walkthrough in `DEMO.md` and the smoke
check in `scripts/smoke_check.py` are the only frontend safety nets.
