import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for advisory-flow smoke tests.
 *
 * The specs mock the backend via page.route, so no live API is required — they
 * start a production Next.js server and stub every /api and data route. Run:
 *
 *   npx playwright install chromium   # one-time browser download
 *   npm run build
 *   npm run test:e2e
 *
 * Note: in network-restricted environments the browser binary cannot be
 * downloaded; see docs/PLAYWRIGHT_E2E.md.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3100',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run start -- -p 3100',
    url: 'http://127.0.0.1:3100',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
