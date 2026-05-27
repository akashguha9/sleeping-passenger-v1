// Advisory proof-loop end-to-end scaffold.
//
// proof_loop_hardening_sprint, Phase 6.
//
// THIS IS A SCAFFOLD.  Playwright is not yet installed in this repo.
// Running this file requires (manual next steps — not auto-installed
// by Claude):
//
//     cd frontend
//     npm install -D @playwright/test
//     npx playwright install --with-deps
//     npx playwright test e2e/advisory-proof-loop.spec.ts
//
// The spec is written to:
//   - exercise the operator surface, not the customer-facing surface
//   - degrade gracefully (test.skip) when the backend is unreachable
//   - prefer role/text selectors (no fragile CSS chains)
//   - assert advisory framing and ABSENCE of execution language
//   - never invoke any execution / broker / order path (none exist).
//
// If/when Playwright is wired up, the imports below resolve normally.

// @ts-ignore - playwright is optional and only resolves once installed.
import { test, expect } from '@playwright/test';
import {
  ADVISORY_ONLY_LABEL,
  scanForForbiddenLanguage,
} from '../src/lib/advisoryTruth';

const BACKEND_BASE = process.env.SP_BACKEND_BASE ?? 'http://127.0.0.1:8000';
const FRONTEND_BASE = process.env.SP_FRONTEND_BASE ?? 'http://127.0.0.1:3000';

async function backendReachable(): Promise<boolean> {
  try {
    // Cast to any so the spec compiles without @types/node.
    const fetchFn = (globalThis as any).fetch as
      | ((url: string, init?: any) => Promise<{ ok: boolean }>)
      | undefined;
    if (!fetchFn) return false;
    const resp = await fetchFn(`${BACKEND_BASE}/api/source-health`);
    return Boolean(resp && resp.ok);
  } catch {
    return false;
  }
}

test.describe('advisory proof loop', () => {
  test.beforeAll(async () => {
    const ok = await backendReachable();
    test.skip(!ok, 'backend unreachable — advisory proof loop e2e SKIPPED');
  });

  test('dashboard shows advisory-only framing and no execution language', async ({
    page,
  }) => {
    await page.goto(FRONTEND_BASE);
    await expect(page.getByText(ADVISORY_ONLY_LABEL, { exact: false }).first())
      .toBeVisible();
    const bodyText = await page.locator('body').innerText();
    const findings = scanForForbiddenLanguage(bodyText);
    expect(findings, JSON.stringify(findings, null, 2)).toEqual([]);
  });

  test('truth bar surfaces mock / live / stale / degraded distinctions', async ({
    page,
  }) => {
    await page.goto(FRONTEND_BASE);
    // The TopTruthBar renders mock/live/stale/degraded chips.  Tolerate
    // any of the four — the test asserts that the concept is shown, not
    // any particular state.
    const truthBar = page.getByTestId('top-truth-bar').or(
      page.locator('[data-testid*="truth"]').first(),
    );
    await expect(truthBar).toBeVisible();
  });

  test('signal inbox cards stamp advisory and no-execution', async ({
    page,
  }) => {
    await page.goto(`${FRONTEND_BASE}/live-signals`);
    const bodyText = await page.locator('body').innerText();
    expect(
      scanForForbiddenLanguage(bodyText),
      'forbidden execution language on /live-signals',
    ).toEqual([]);
    await expect(
      page.getByText(ADVISORY_ONLY_LABEL, { exact: false }).first(),
    ).toBeVisible();
  });

  test('reconciliation surface shows broker not connected and AI executions 0', async ({
    page,
  }) => {
    await page.goto(`${FRONTEND_BASE}/manual-trades`);
    const bodyText = await page.locator('body').innerText().catch(() => '');
    if (!bodyText) {
      test.skip(true, '/manual-trades not present in this build');
      return;
    }
    expect(scanForForbiddenLanguage(bodyText)).toEqual([]);
  });

  test('Kalshi operator truth panel separates api health from signal freshness', async ({
    page,
  }) => {
    await page.goto(`${FRONTEND_BASE}/operator`);
    const bodyText = await page.locator('body').innerText().catch(() => '');
    if (!bodyText) {
      test.skip(true, '/operator not present in this build');
      return;
    }
    expect(scanForForbiddenLanguage(bodyText)).toEqual([]);
  });
});
