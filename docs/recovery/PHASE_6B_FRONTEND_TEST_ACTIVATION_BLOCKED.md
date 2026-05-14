# Phase 6B — Frontend Test Activation: BLOCKED BY DESIGN

> Sprint: closing verification + merge-readiness (Phase 6A–6C).
> This document records why Phase 6B did **not** install a frontend test
> runner, and lists the exact future commands required to activate the
> 27 already-committed Vitest-ready `it()` cases.

---

## 1. Decision

`Frontend_Test_Activation = BLOCKED (case D)`.

No frontend test framework was installed. The committed specs remain
ready to run, but `npm test` cannot execute them until Vitest is
introduced as a future, scoped sprint.

This matches the project's existing convention, which is **explicit**
in two places already merged on this branch:

- `docs/recovery/FRONTEND_TEST_PLAN.md` line 1–3:
  > Decision: **no frontend test framework was installed in this
  > recovery sprint.** […] Adding Vitest + React Testing Library […]
  > is doable but is a *new dependency* with TypeScript path-mapping
  > and JSDOM config that should be reviewed by the human operator
  > before landing.
- Header comment on every spec file (e.g.
  `frontend/src/components/__tests__/ReactorBadge.spec.tsx` line 8):
  > They do NOT run today — `frontend/package.json` does not yet
  > ship Vitest.

The closing-sprint mandate explicitly forbids casual mutation of the
frontend dependency graph and over-engineering. Honouring the
already-merged decision is the safe choice; reversing it inside a
verification sprint would be the unsafe one.

---

## 2. Evidence of current state

| Probe | Result |
| --- | --- |
| `frontend/package.json` test script | absent |
| `frontend/package.json` devDependencies for vitest / jest / @testing-library / jsdom | absent |
| `frontend/package-lock.json` references to `vitest` or `@testing-library` | **0** |
| `frontend/node_modules/vitest` | does not exist |
| `frontend/node_modules/@testing-library` | does not exist |
| `frontend/vitest.config.*` / `jest.config.*` / `playwright.config.*` | absent |
| Committed spec files | 3 (`ReactorBadge.spec.tsx`, `backlogReadiness.spec.ts`, `nextBestAction.spec.ts`) |
| Committed `it(...)` cases across those specs | **27** |

The specs themselves intentionally use `@ts-ignore` to stub
`describe / it / expect / @testing-library/react` at type-check time,
which is how `npx tsc --noEmit` and `npm run build` stay green today.

---

## 3. Specs already committed (ready to run)

### `frontend/src/components/__tests__/ReactorBadge.spec.tsx` — 13 cases

`ReactorBadge`:
1. Renders the canonical reactor state label.
2. Renders an `UNKNOWN` label when state is missing.
3. Renders an `UNKNOWN` label when state is unrecognised.
4. Renders a visible `GALLARDO_BLOCK` pill when `gallardoBlock=true`.
5. Does NOT render the gallardo block pill when false.
6. Renders `REACTOR_UNAVAILABLE` pill when `reactorAvailable=false`.
7. Never emits execution / broker / AI-approved copy in any state.

`ReactorDiagnosticsPanel`:
8.  Renders all eight reactor fields with valid values.
9.  Degrades safely to `n/a` / `unknown` when fields are missing.
10. Renders the gallardo block warning callout when `gallardo_block=true`.
11. Always shows the `ADVISORY_ONLY` / `HUMAN_EXECUTION_REQUIRED` copy.
12. Never grants execution permission in DOM data attributes.
13. Never emits forbidden execution / broker / AI-approved copy.

### `frontend/src/lib/__tests__/backlogReadiness.spec.ts` — 8 cases

1. Returns `UNKNOWN` when count is null/undefined.
2. Returns `OK` below the warn threshold.
3. Returns `WARN` between warn and block thresholds.
4. Returns `BLOCK` at/above the block threshold.
5. Returns `FULL_REVIEW` at/above the full-review threshold.
6. Surfaces the canonical advisory-only reason text.
7. Renders incomplete-journal pressure as a separate signal.
8. Never produces an execution / readiness-to-trade flag.

### `frontend/src/lib/__tests__/nextBestAction.spec.ts` — 6 cases

Pre-existing convention reference (kept). Validates
`deriveNextBestAction` over `HealthResponse` permutations.

---

## 4. Exact commands to activate (future sprint)

This is intentionally identical to the install block already merged in
`docs/recovery/FRONTEND_TEST_PLAN.md` so there is one source of truth.

```bash
cd frontend
npm install -D \
  vitest \
  @vitest/coverage-v8 \
  @testing-library/react \
  @testing-library/jest-dom \
  @testing-library/user-event \
  jsdom
```

Add `frontend/vitest.config.ts`:

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

Add `frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
```

Add to `frontend/package.json` scripts:

```json
"test": "vitest run",
"test:watch": "vitest"
```

Then:

```bash
cd frontend
npm test
```

Expected outcome the first time it runs:
- All 27 committed cases should pass without spec edits.
- `npx tsc --noEmit` and `npm run build` should remain green; the
  `@ts-ignore` shims in the specs become no-ops once
  `@testing-library/react` and Vitest globals are actually resolvable.

---

## 5. Why this is not being done in the current sprint

1. **Project convention is explicit.** Two on-disk documents
   (`FRONTEND_TEST_PLAN.md` and the spec headers themselves) record the
   prior decision to defer install. Reversing that inside a closing
   verification sprint would contradict an already-merged decision.
2. **Closing-sprint mandate.** The current sprint prompt explicitly
   says *"Do not casually mutate frontend dependency graph"* and
   *"This is NOT a feature sprint."* A 6-package devDep install plus a
   new config file plus a setup file is a non-trivial dependency
   surface change.
3. **Risk asymmetry.** Backend tests (3495) are green, Next build is
   green, TypeScript is clean. Inserting Vitest + JSDOM + a path-alias
   config now risks breaking `npm run build` (Next 14 + Vitest path
   aliasing has documented sharp edges). The downside dominates the
   upside in a verification sprint.
4. **The work to be activated is preserved.** The specs are
   already committed (Phase 3 / Phase 2A of the previous sprint). A
   future sprint will be able to run them by adding the install block
   above — no spec rewrites are required.

---

## 6. Scorecard impact

`Frontend_Test_Activation = 0` change. Per the closing-sprint scoring
rules: *"If frontend tests could not be activated, score movement
should be small or zero."* Testing remains backend-driven at this
point in the project.

---

## 7. Safety invariants

This blocker does **not** weaken any invariant. All of the following
are preserved and continue to be enforced by the existing 3495 backend
tests (notably `tests/test_frontend_no_execution_language.py`,
`tests/test_local_security_floor.py`, and
`tests/test_signal_reactor_wiring.py`):

```
ADVISORY_ONLY               = true
HUMAN_EXECUTION_REQUIRED    = true
BROKER_ORDER_PERMISSION     = false
AI_EXECUTION                = 0
broker_api_called           = false
execution_permission        = false
can_execute                 = false
```
