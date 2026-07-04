# CI Fix — /nbi/cockpit artifact age truth marker

**Date:** 2026-07-04 · **Branch:** `sprint/open-the-gate-gap-closer`

## CI failure

```text
FAILED tests/test_cockpit_truth_smoke.py::test_smoke_runner_passes_end_to_end
AssertionError: ['/nbi/cockpit lacks artifact_age_minutes']
1 failed, 7978 passed
```

## Root cause

Environment divergence, not flakiness. `GET /nbi/cockpit` has two branches:

1. **artifact present** → payload enriched with `artifact_age_minutes` ✓
2. **artifact missing** → fail-closed `NO_COCKPIT_RUN_RECORDED` envelope
   which **omitted `artifact_age_minutes` entirely** ✗

`runtime/` is gitignored, so on CI's fresh checkout the cockpit artifact
does not exist → branch 2 → smoke fails. On the dev machine the live
artifact exists → branch 1 → smoke passed locally, masking the gap.

A secondary inconsistency amplified it: cockpit **writers** honor the
`NBI_ARTIFACT_DIR` test-isolation override, but the API **reader** used a
hardcoded canonical path — so hermetic tests could never exercise the
endpoint against controlled fixtures.

## Fix (product surface, not the test)

`scripts/api_server.py` `GET /nbi/cockpit`:

- the fail-closed envelope now always carries
  `artifact_age_minutes: null`, `artifact_age_status: "MISSING"`,
  `artifact_stale: true` — the truth key exists on **every** branch and a
  missing artifact can never read as fresh;
- the artifact-present branch additionally emits `artifact_age_status`
  (`FRESH` ≤26h / `STALE` >26h / `UNKNOWN` unparseable) alongside the
  existing `artifact_age_minutes` + `artifact_stale`;
- the artifact path now honors `NBI_ARTIFACT_DIR` (same convention as the
  writers), so CI, hermetic tests, and production resolve consistently.

The smoke test was **not weakened** — its assertion is unchanged and now
passes in all three environments for the same reason.

## Regression guard (strengthened)

`tests/test_cockpit_truth_smoke.py`: the previously tolerant
`test_nbi_cockpit_exposes_artifact_age` (which accepted the key's absence
when `artifact_present=false` — the exact CI hole) was replaced by three
strict tests:

- missing artifact → key present, `null`, status `MISSING`, stale, never
  HEALTHY;
- fresh fixture artifact (30 min) → `FRESH`, age ≈30, not stale;
- 50-hour-old artifact → key present, `STALE`, stale=true (an old HEALTHY
  artifact can never render as an ageless green).

## Commands run

| Command | Result |
|---|---|
| `pytest tests/test_cockpit_truth_smoke.py::test_smoke_runner_passes_end_to_end -q` | 1 passed |
| `pytest tests/test_cockpit_truth_smoke.py -q` | 7 passed |
| `pytest tests -q -k "cockpit or truth or artifact_age or nbi"` | 414 passed (5m43s) |
| `pytest tests -q` (full) | 7,978 passed, 3 skipped, 0 failed |
| `npm test` / `npm run build` | 213/213, build 16 routes |

## Before / after

- Before: `/nbi/cockpit` with no artifact → envelope **without** the truth
  key → CI smoke failure; hermetic tests couldn't reach the endpoint's
  artifact branches.
- After: the key exists on every branch with an honest status; both
  branches covered by hermetic fixture tests; CI == local == test env.

**Advisory-only execution lock untouched** — this change reads one JSON
artifact and adds response fields; `tests/test_no_execution_guard_repowide.py`
remains green in the full run.
