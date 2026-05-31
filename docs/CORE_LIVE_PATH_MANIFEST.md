# Core Live Path Manifest — sleeping-passenger-v1

> **Purpose.** A single, test-anchored map of the files that make up the *core
> live advisory + evidence path*. This is the spine an operator (or reviewer)
> should read first; everything else under `scripts/` is supporting, legacy, or
> quarantine surface catalogued in [`DEAD_CODE_AUDIT.md`](DEAD_CODE_AUDIT.md).
>
> **Safety.** Every file below is advisory-only. No file in this path calls a
> broker, places an order, routes an order, or executes a trade. `execution_gate`
> is `LOCKED`, `broker_api_called = false`, `ai_execution_count = 0`, and
> `predictive_claim_allowed` stays `false` until the calibration gate
> (`N_real_forward >= 200`, `Brier <= 0.25`, `ECE <= 0.10`) is cleared.

Kanté principle: this manifest is *squad fitness* — knowing exactly which
players are on the pitch, so dead weight does not slow recoveries.

---

## 1. Real rows — ball recovery / interceptions

| File | Role | Tests |
|---|---|---|
| `scripts/real_evidence_canary.py` | Read-only ≥3-source canary (yfinance, polymarket, **sec_edgar**, gdelt). Persists genuine canonical fresh rows; mock/backfill never canonical; `rows_added == 0` ⇒ `ZERO_FRESH_ROWS`, never `LIVE_CANONICAL`. | `tests/test_real_evidence_canary.py` |
| `scripts/source_freshness_contract.py` | Single canonical-status reducer separating provider API health from canonical fresh rows. | `tests/test_source_freshness_contract.py` |
| `scripts/persistence.py` | Canonical SQLite (`runtime/mvp_local.db`): `signal_events`, `source_run_log`, decision snapshots. Advisory stamps re-asserted on every write. | `tests/test_persistence*.py` |

## 2. Live decision path — central progression

| File | Role | Tests |
|---|---|---|
| `scripts/live_decision_path.py` | The single orchestrator: source freshness → base probability → Moltbook adjust → capacity guard → admission gates → snapshot persist → advisory output. Moltbook can only *downgrade*; it never unlocks execution. | `tests/test_live_decision_path.py` |
| `scripts/probability_snapshot.py` | Pure advisory probability math from the six score axes (EMS/EQS/DS/LS/EFS/APS). | `tests/test_probability_snapshot.py` |
| `scripts/decision_probability_snapshot.py` | Additive `decision_probability_snapshots` table; persists `model_probability` at decision time so `n_valid_p` can grow. | `tests/test_decision_probability_snapshot.py` |
| `scripts/admission_gates.py` | Central advisory veto/admission contract. | `tests/test_admission_gates.py` |
| `scripts/moltbook_adjustment.py` | Learn-from-lost-duels downgrade only. | `tests/test_moltbook_adjustment.py` |
| `scripts/capital_rotation_guard.py` | Per-position capacity; missing context ⇒ `CAPACITY_UNKNOWN` ⇒ block. | `tests/test_capital_rotation_guard.py` |
| `scripts/portfolio_correlation_guard.py` | Cross-position correlation/exposure; missing covariance ⇒ UNKNOWN ⇒ block. | `tests/test_portfolio_correlation_guard.py` |
| `scripts/run_daily_live_advisory_decisions.py` | **Daily batch**: fresh canonical rows → `run_live_decision_path` → persisted snapshots. Grows `n_valid_p`; reports block reasons + `NO_FRESH_CANONICAL_ROWS`. | `tests/test_daily_live_advisory_decisions.py` |

## 3. Outcomes + calibration — VAR / referee truth system

| File | Role | Tests |
|---|---|---|
| `scripts/outcome_labeling_flow.py` | Attaches real `(p, y)` pairs; rejects open/unresolved/fabricated outcomes; keeps real-forward and historical-proxy corpora separate. | `tests/test_outcome_labeling_flow.py` |
| `scripts/attach_due_outcomes.py` | **Elapsed-horizon** outcome attachment. Open trades never labelled; missing price evidence excluded with reason; only eligible real-forward pairs grow `N_real_forward`. | `tests/test_attach_due_outcomes.py` |
| `scripts/real_calibration_evidence.py` | Brier / ECE / LogLoss on the real-forward corpus only; honest `INSUFFICIENT_EVIDENCE` below N=200. | `tests/test_real_calibration_evidence.py` |

## 4. Evidence surface — analyst camera / full-back outlet

| File | Role | Tests |
|---|---|---|
| `scripts/real_evidence_bundle.py` | Composes the honest, reproducible evidence bundle (`real_money_ready = false`, `edge_claimed = false`). | `tests/test_real_evidence_bundle.py` |
| `scripts/api/routers/evidence_router.py` | **Read-only `GET /evidence/*` routes** (source-truth, calibration, bundle, live-decision-path, capacity-risk, summary). Strips secrets; capacity-unknown ⇒ risk; predictive-claim surfaced verbatim. | `tests/test_evidence_api_routes.py` |
| `scripts/refresh_real_evidence.py` | **One-command real-evidence refresh** (canary → daily decisions → attach outcomes → calibration → bundle). Offline by default; real canary requires explicit flag + `REAL_EVIDENCE_CANARY=1`. | `tests/test_refresh_real_evidence.py` |
| `scripts/advisory_contract.py` | Advisory-only safety stamps spread across every artifact. | `tests/test_advisory_contract*.py` |

---

## 5. Maintainability index (this sprint)

```
CorePathClarity = core_files_documented / core_files_detected
DeadCodeRisk    = legacy_unclassified_files / total_files
TestAnchoring   = core_files_with_tests / core_files_detected
MaintainabilityIndex =
      0.40 * CorePathClarity
    + 0.30 * TestAnchoring
    + 0.20 * (1 - DeadCodeRisk)
    + 0.10 * ScopeGuardCoverage
```

* **Core files documented above:** 18 / 18 ⇒ `CorePathClarity = 1.0`
* **Core files with named tests:** 18 / 18 ⇒ `TestAnchoring = 1.0`
* **Legacy/quarantine unclassified:** classified in `DEAD_CODE_AUDIT.md`; the
  `dead_code_inventory.py` map is READ-ONLY and never deletes.
* **Scope-guard coverage:** the three new evidence modules
  (`run_daily_live_advisory_decisions.py`, `attach_due_outcomes.py`,
  `refresh_real_evidence.py`) are registered in
  `private_scope_guard.EXPLICIT_IN_SCOPE`.

> Nothing in this manifest is auto-deleted. Deletion candidates live in
> `DEAD_CODE_AUDIT.md` and require `DeleteAllowed_f = 1` (not imported, not
> tested, marked legacy/quarantine, no runtime reference, full suite green
> after delete) before any removal.
