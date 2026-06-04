# Playwright E2E

`frontend/e2e/advisory-flow.spec.ts` — route-mocked smoke (no live backend):
cockpit (advisory + readiness visible), signal inbox (calibration "do not size"),
manual trade log (leverage ceiling + jurisdiction source, no execution button),
reconciliation, moltbook (no auto-apply wording). Forbidden-CTA regex:
`\b(execute order|place order|auto-buy|auto-sell|broker trade|send order|trade now)\b`.

## Run
```
cd frontend
npx playwright install chromium   # one-time browser download
npm run build
npm run test:e2e
```

## Sandbox note
In network-restricted environments the Chromium binary cannot be downloaded, so
the Playwright suite is NOT executed here. The runnable counterpart
`src/app/__tests__/no-execution-language.spec.tsx` renders the cockpit and
manual-trade pages under Vitest and asserts the same forbidden-CTA regex never
appears — that runs in `npm test`.

## Sprint update — local run attempt (real-evidence-playwright-hygiene)

`@playwright/test` 1.60.0 is installed and `npx playwright --version` works.
Running the browser install in this sandbox fails with an explicit network
block:

```
npx playwright install chromium
Error: Download failed: server returned code 403 body 'Host not in allowlist'.
URL: https://cdn.playwright.dev/builds/cft/.../linux64/chrome-linux64.zip
```

No system Chromium/Chrome is present either. Therefore the Playwright suite is
NOT executed in this environment and **no e2e score increase is claimed**.

The suite is ready to run on any machine with outbound access to the Playwright
CDN (or a vendored browser): `npx playwright install chromium && npm run
test:e2e`. The runnable Vitest guard
(`src/app/__tests__/no-execution-language.spec.tsx`) remains the executed
fallback and asserts the same forbidden-CTA regex across rendered pages.
