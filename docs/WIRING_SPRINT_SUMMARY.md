# Wiring Sprint Summary — sleeping-passenger-v1

The previous sprint built five tested foundation modules but left them
**unwired** — nothing in a live decision path called them. This sprint converts
foundation into behavior. All changes are advisory-only and additive.

## Live decision path order

`scripts/live_decision_path.py::run_live_decision_path` is the single
orchestrator. It runs the foundation modules in this exact order:

1. **Source freshness** — `source_freshness_contract.classify_canonical_status`
   separates provider API health from canonical fresh rows. `C_s` (0 unless
   truly live) feeds the admission freshness gate, so a stale / zero-fresh /
   mock / backfill source can never be faked live.
2. **Base probability** — `probability_snapshot.build_probability_snapshot`
   produces `p_base` (staleness/mock penalties flow in from step 1).
3. **Moltbook adjustment** — `moltbook_adjustment.apply_moltbook_adjustment`
   lowers `p_base` → `p_after_moltbook` for prior bad-process / loss patterns;
   `adjust_admission` can downgrade CANDIDATE → WATCHLIST. Never increases p;
   never unlocks execution.
4. **Capacity guard** — `capital_rotation_guard.evaluate_capacity` produces
   sizing + a capacity verdict. Missing stop / unknown capital / breached
   country cap / invalid leverage → not promotable.
5. **Admission gates** — `admission_gates.evaluate_admission_gates` reduces the
   safety / state / freshness / leverage / capacity / moltbook gates to one
   `final_advisory_class` (BLOCKED_BY_* on any failure).
6. **Snapshot persist** — `decision_probability_snapshot.record_decision_probability`
   writes the decision-time `model_probability` to the additive
   `decision_probability_snapshots` table (only when `db_path` is supplied).
7. **Advisory output** — one dict with `final_advisory_class`, `p_base`,
   `p_after_moltbook`, `source_truth`, `gate_result`, `capacity_result`,
   `calibration_status`, `predictive_claim_allowed=false`, and the canonical
   advisory-only safety stamps.

## Where the contracts are now live-path

| Contract | Wired into |
|---|---|
| `evaluate_admission_gates` | `candidate_promotion_contract.evaluate_candidate` (`gate_result`) **and** the orchestrator |
| `apply_moltbook_adjustment` | orchestrator step 3 (before admission gates) |
| `evaluate_capacity` | orchestrator step 4 |
| `classify_canonical_status` | orchestrator step 1 **and** `GET /source-health/canonical-truth` |
| `record_decision_probability` | orchestrator step 6 |

## Calibration evidence pipeline (no claim)

`scripts/snapshot_calibration_bridge.py` pairs persisted snapshot
probabilities with realized `outcome_label`s and computes Brier / ECE /
LogLoss / MCE by reusing `calibration_report`'s audited primitives.

`CalibrationAllowed = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)`. Today N≈0, so
`calibration_status = INSUFFICIENT_EVIDENCE` and `predictive_claim_allowed =
false`. The bridge cannot flip the gate on its own.

## Safety invariants (preserved everywhere)

`ADVISORY_ONLY`, `HUMAN_EXECUTION_REQUIRED`, `execution_gate = LOCKED`,
`broker_api_called = false`, `ai_execution_count = 0`. No broker / order /
execute / buy / sell route was added. Moltbook and capacity can only downgrade
or warn; they never unlock execution. `predictive_claim_allowed` stays false
unless the calibration gate is genuinely met.
