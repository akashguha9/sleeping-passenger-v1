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
