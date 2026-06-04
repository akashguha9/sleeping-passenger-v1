# Repo Discipline Census — guards, god-module split plan, safe seams

Companion to `docs/module_census.md` (raw tiers). This file holds the
**forward-looking plan** and the **guard rails**, not raw lists.

## 1. Current entropy snapshot (corrected)

| Metric | Value |
|---|---|
| Total `scripts/*.py` | 325 |
| ACTIVE (orchestrator path) | 70 |
| API_REACHED | 54 |
| TEST_ONLY | 132 |
| ORPHAN (this branch) | 69 |

The earlier "145 orphans" figure was a measurement artifact (BOM + `from
scripts import X` parser bugs), now fixed. Real dead-weight risk is materially
smaller than first reported, but still non-trivial: 69 modules are reachable
from neither entrypoint nor any test on this branch.

## 2. Guard rails (test-enforced)

- **Active-set growth gate** — `tests/test_module_census.py` pins the ACTIVE
  set at a ceiling (currently **70**). Any PR pulling a new module onto the
  `run_diagnostics_pipeline` path fails the test until the ceiling is
  consciously bumped and this census updated. (Bumped 68 → 69 for `tag_engine`, then 69 → 70 for the extracted
  `governance_verdict`, each deliberately.)
- **Safety-critical existence gate** — `tests/test_repo_discipline_guards.py`
  pins a list of safety-critical modules that must not be silently deleted.
- **God-module split-plan existence gate** — the same test asserts this plan
  exists and still names the three god modules, so the plan cannot quietly
  rot away.

## 3. Safety-critical modules (must not be deleted silently)

These enforce the advisory-only / fail-closed posture. Deleting any of them
silently is a safety regression:

- `pipeline_health_report.py` — governance verdict (`can_deploy_capital`,
  `system_readiness_state`).
- `narrative_operator_wisdom_filter.py` — `action_authority` (REVOKED default).
- `busquets_pre_execution_audit.py` — `HARD_VETO`.
- `board_control_safety_layer.py` — promotion clearance block.
- `execution_governance.py` — execution policy / no-new-risk.
- `paper_execution.py` — refuses to run while live execution is enabled.
- `execution_integrity_audit.py` — `LOCKED_EXECUTION`.
- `tag_engine.py` — canonical tag source of truth.

## 4. God-module split plan (NOT executed here)

Each is a future, test-protected, reversible extraction. **One seam (the
governance verdict) was extracted this round; no god module was wholesale
split.** Recommended order (lowest risk / highest value first):

1. **`pipeline_health_report.py` (4968)** — ✅ DONE this round: the governance
   verdict (`determine_system_readiness` → `can_deploy_capital`/
   `system_readiness_state`) was extracted to `scripts/governance_verdict.py`
   (pure, re-exported for compatibility, golden-tested byte-identical). The
   god-module dropped 4996 → 4968. Remaining future seams below.
2. **`api_server.py` (3029)** — separate Pydantic request/response models +
   money validators into `api_models.py`, leaving routes behind. Seam: models
   are already grouped in a contiguous block.
3. **`structural_admission_layer.py` (2318)** — extract the ~30 input
   dataclasses + enums into `structural_admission_types.py`, leaving scoring +
   admission decision. Seam: types are contiguous at the top of the file.

Each extraction must: (a) be pure move + re-export (no behavior change),
(b) keep the old import paths working via re-export shims, (c) land with the
full suite green, (d) be revertible in one commit.

## 5. Deletion candidates — REQUIRE cross-branch verification first

No deletions are proposed. The 69 ORPHAN modules (see `docs/module_census.md`
§4) are candidates *for investigation only*, gated by the §6 "do not delete
without" checklist. Standalone CLIs in that list (`run_dashboard`,
`run_ingestion`, `export_*`, `milk_test_*`, …) are orphaned **by design** and
are not deletion candidates at all.
