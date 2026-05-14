# Frontend Proof Plan — Next Sprint, Not This One

> Decision: **no frontend test framework was installed in this
> recovery sprint.** The current `frontend/package.json` lists no test
> runner; the only `*.test.*` files under `frontend/` are inside
> `node_modules` (Next.js's own internal tests).  Adding Vitest +
> React Testing Library, or Jest + RTL, is doable but is a *new
> dependency* with TypeScript path-mapping and JSDOM config that should
> be reviewed by the human operator before landing.

## Current frontend stack

- Next.js 14.2.29
- React 18, React-DOM 18
- TypeScript 5
- Tailwind 3.4
- Path alias `@/` → `frontend/src` (Next default)

## Recommended setup (when ready)

### Vitest + React Testing Library (preferred)

Rationale: Vitest is the lightest first runner that works cleanly with
TypeScript + a Vite-like build, and it tolerates Next.js's `app/` router
when paired with `@testing-library/react` + `jest-dom`. Jest works too
but requires more Next-specific config.

```bash
npm install -D \
  vitest \
  @vitest/coverage-v8 \
  @testing-library/react \
  @testing-library/jest-dom \
  @testing-library/user-event \
  jsdom
```

`frontend/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
});
```

`frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
```

Add to `package.json` scripts:

```json
"test": "vitest run",
"test:watch": "vitest"
```

### Playwright (later, for E2E)

Only after Vitest + RTL coverage exists. Playwright runs the dev
server against real backend stubs.

## First-pass coverage targets (priority order)

Each test should be deterministic, mock the network layer
(`@/lib/apiClient`), and never hit a real backend.

| # | Component / Page | What to test | Why |
|---|---|---|---|
| 1 | `HumanOnlyBadge`, `AdvisoryOnlyBadge` | renders advisory copy; no execution language | smallest possible smoke test |
| 2 | `NoExecutionBanner` | renders "no broker call" disclaimer | safety surface |
| 3 | `ManualTradeLogForm` | required-field validation (ticker, qty, price, thesis), leverage bounds, soft-warning collection (invalidation_level/exit_plan/risk_reason/confidence/emotional_state), successful submit | core operator-discipline flow |
| 4 | `ReconciliationCard` | renders trade fields and (when present) reconciliation status; no execute/buy/sell language anywhere | core learning flow |
| 5 | `app/reconciliation/page` | renders live queue panel (unreconciled count, oldest age, avg completeness, learning-ready count) | proves backend → frontend wire |
| 6 | `SignalCard` | renders core signal fields; advisory badges visible | inbox primary view |
| 7 | `app/signal-inbox/page` | renders bucket filters and action counts; never renders an "Execute" / "Submit Order" button | inbox safety |
| 8 | **New (next sprint)** `ReactorStateBadge` | renders one of 9 reactor states; OPERATOR_CONTROL_RODS / HOT_CONTAINMENT_REQUIRED display a visible warning ring; gallardo_block visible but disabled-looking | reactor visibility |
| 9 | **New (next sprint)** Meltdown/heat warning | renders a callout when `meltdown_risk_score >= 0.6` or `operator_heat_score >= 0.7` | reactor visibility |

## Safety assertions that should appear in *every* frontend test

```ts
expect(container.textContent).not.toMatch(/place order/i);
expect(container.textContent).not.toMatch(/execute trade/i);
expect(container.textContent).not.toMatch(/broker connected/i);
expect(container.querySelector('[data-execution-permission="true"]')).toBeNull();
```

This bakes the advisory-only doctrine into the frontend test layer,
mirroring the AST checks already in `tests/test_signal_inbox_api.py`.

## Reactor badge spec (for the next sprint)

When the inbox/payload now carries:

- `reactor_state` ∈ {COLD_OBSERVE, WARM_WATCH, FUSION_REVIEW_CANDIDATE,
  FISSION_MAP_ONLY, HOT_CONTAINMENT_REQUIRED, WASTE_DECAY,
  ECHO_SUPPRESSED, OPERATOR_CONTROL_RODS, INSUFFICIENT_DATA}
- `decision_grade_energy` ∈ [0, 1] | null
- `echo_risk_score` ∈ [0, 1] | null
- `meltdown_risk_score` ∈ [0, 1] | null
- `fusion_validity` ∈ {valid_fusion, weak_fusion, echo_not_fusion,
  overheated_uncontained, insufficient_data}
- `fission_branch_clarity` ∈ [0, 1] | null
- `operator_heat_score` ∈ [0, 1] | null
- `gallardo_block` ∈ {true, false}
- `reactor_recommendation` ∈ {observe, watch, review_later,
  review_candidate, map_branches, quarantine, decay_archive,
  human_review_only, cool_down}

…the frontend should add (next sprint, not this one):

1. `<ReactorStateBadge state={...} />` in `SignalCard`, color-coded:
   - cool (gray) for COLD_OBSERVE / INSUFFICIENT_DATA
   - amber for WARM_WATCH / FUSION_REVIEW_CANDIDATE
   - warning amber for WASTE_DECAY / FISSION_MAP_ONLY
   - red for ECHO_SUPPRESSED / HOT_CONTAINMENT_REQUIRED /
     OPERATOR_CONTROL_RODS
2. A "Decision-grade energy" mini-meter on the signal detail page.
3. A "Gallardo block" callout when `gallardo_block === true`.
4. A "Reactor unavailable" cue when `reactor_available === false`.

None of these add an Execute path. All of them are *labels*.

## Why no test framework is being introduced today

- `next.config.js` would need a transform shim for TypeScript path
  aliases; getting that wrong destabilises `npm run build`.
- Two new top-level packages (vitest, jsdom) and four sub-packages on
  the testing-library line is a non-trivial dependency surface for a
  recovery sprint whose primary mandate is *not breaking the working
  parts*.
- The current sprint's biggest leverage point — Signal Reactor
  visibility — is on the backend payload, not the rendering. The
  rendering follows next.

This document is the explicit plan for the next sprint, so when it
starts the operator can copy-paste the commands above.
