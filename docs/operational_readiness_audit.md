# Sleeping Passenger Operational Readiness Audit

> Read-only, advisory-only. Second-generation hardening scorecard beside the coordination audit. This report measures **operational readiness, not trading edge**.

## Executive Summary

- **Readiness grade:** `NOT_READY_NO_REAL_OUTCOMES`
- **Readiness score:** 0.1789
- **Raw (pre-penalty) score:** 0.9688
- **Evidence quality score:** 0.2059
- **NO_DATA ratio:** 0.2059
- **Mode:** `PARTIAL_DATA`
- **Real outcome count:** 0
- **Imported backtest count:** 0
- **Synthetic fixture count:** 0
- **Runtime records inspected:** 0
- **Biggest blocker:** none
- **Biggest strength:** `outcome_evidence` section (score 1.0)
- **Generated (UTC):** 2026-06-05T21:44:43+00:00
- **Repo commit:** `91af69bc402375619893eda49c136f8c8fdb915b`

**This report measures operational readiness, not trading edge.** Code-level operational readiness can be high while trading edge stays unproven; calibration remains gated by evidence until real outcomes exist.

## Score Formula

```
readiness_score = raw_readiness_score
                  * evidence_quality_score
                  * (1 - 0.50 * no_data_ratio)

  raw_readiness_score   = 0.9688   (mean of section scores)
  evidence_quality_score= 0.2059   (provenance-weighted)
  no_data_ratio         = 0.2059
  => readiness_score     = 0.1789
```

The evidence-quality multiplier is what makes this audit honest: a static-only, perfectly-structured system cannot reach FIELD_READY without real outcomes raising its evidence quality.

## Section A — Outcome Evidence

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** The outcome model is complete and provenance-honest, but there are 0 real closed operator outcomes — calibration-grade evidence does not exist yet.

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| real_outcome_presence | 0 | `NO_DATA` | None | NO_DATA | >=30 PASS; 1-29 WARN; 0 NO_DATA |
| outcome_schema_field_coverage | 1.0 | `PASS` | 1.0 | STATIC_CODE | >=0.95 PASS |
| closed_trade_math_integrity | True | `PASS` | 1.0 | TEST_RESULT | direction-signed return; no negative holding; no div0; tested |
| outcome_mode_honesty | True | `PASS` | 1.0 | STATIC_CODE | LIVE_MANUAL/PAPER/IMPORTED/SYNTHETIC separated; synthetic never eligible |
| real_outcome_field_coverage | None | `NO_DATA` | None | NO_DATA | NO_DATA until real outcomes exist |

**Evidence:**

- `scripts/outcome_evidence.py:42` (STATIC_CODE) — source-type vocabulary
- `scripts/outcome_evidence.py:83` (STATIC_CODE) — direction-signed return math
- `runtime/mvp_local.db` (NO_DATA) — real_n=0 (closed LIVE_MANUAL outcomes)

## Section B — Manual Trade Integrity

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** Manual trades canonicalize to EXCHANGE:SYMBOL with an explicit currency; bare tickers and unsupported exchanges are rejected; a stable natural key plus DB idempotency block duplicates.

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| manual_trade_required_field_coverage | True | `PASS` | 1.0 | STATIC_CODE | validator enforces required manual-trade fields |
| duplicate_manual_trade_guard | True | `PASS` | 1.0 | TEST_RESULT | duplicate natural-key blocked/merged idempotently |
| ticker_canonicalization_integrity | 1.0 | `PASS` | 1.0 | TEST_RESULT | 1.0 PASS; >=0.95 WARN; else FAIL (no silent cross-exchange collision) |
| currency_integrity | 1.0 | `PASS` | 1.0 | TEST_RESULT | 1.0 PASS (every exchange maps to an explicit currency) |

**Evidence:**

- `scripts/manual_trade_validation.py:129` (STATIC_CODE) — ticker canonicalization
- `scripts/manual_trade_validation.py:54` (STATIC_CODE) — exchange->currency mapping
- `tests/test_manual_trade_validation.py` (TEST_RESULT) — validation proofs

## Section C — Reconciliation Integrity

- **Score:** 0.875
- **Status:** `WARN`
- **What it checks:** Reconciliation pairs trades to outcomes through stable IDs, is idempotent at the DB boundary, and its P&L/return/holding-period math is tested. A full field-level correction journal remains a gap (WARN).

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| reconciliation_pairing_integrity | True | `PASS` | 1.0 | STATIC_CODE | manual_trade_id<->trade_id<->outcome paired; provenance-gated queue |
| idempotent_reconciliation_guard | True | `PASS` | 1.0 | TEST_RESULT | same reconciliation twice -> idempotent (PK + INSERT OR IGNORE) |
| correction_audit_trail_presence | True | `WARN` | 0.5 | STATIC_CODE | soft-cancel audit exists; full old/new correction journal is a gap |
| reconciliation_math_consistency | True | `PASS` | 1.0 | TEST_RESULT | net P&L / realized return / holding period computed + tested |

**Evidence:**

- `scripts/persistence.py:98` (STATIC_CODE) — idempotency key
- `scripts/paper_reconciliation.py:260` (STATIC_CODE) — reconciliation return math
- `tests/test_reconciliation_math_integrity.py` (TEST_RESULT) — math proofs

## Section D — Calibration Readiness

- **Score:** 1.0
- **Status:** `WARN`
- **What it checks:** The calibration math (Brier, ECE, Murphy reliability/resolution) is implemented and tested, and labels provenance honestly — but it stays NO_DATA because there are 0 real and 0 imported outcomes (below the N>=30 gate). Calibration is evidence-gated, not faked.

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| calibration_dataset_availability | real=0 imported=0 | `NO_DATA` | None | NO_DATA | >=100 real PASS; 30-99 WARN; imported>=100 WARN; else NO_DATA |
| calibration_mode_assignment | NO_DATA | `NO_DATA` | None | NO_DATA | MEASURED_REAL/IMPORTED/PAPER/SYNTHETIC/NO_DATA per dataset counts |
| brier_score_readiness | None | `NO_DATA` | None | NO_DATA | computed only when N>=30 non-synthetic outcomes exist |
| expected_calibration_error_readiness | None | `NO_DATA` | None | NO_DATA | computed only when N>=30 with >=3 non-empty bins |
| reliability_decomposition_readiness | None | `NO_DATA` | None | NO_DATA | Murphy decomposition only when N>=100 |
| calibration_report_honesty | True | `PASS` | 1.0 | STATIC_CODE | Brier/ECE/Murphy exist; provenance labelled; synthetic never live |

**Evidence:**

- `scripts/calibration_map.py:175` (STATIC_CODE) — Brier score
- `scripts/calibration_map.py:160` (STATIC_CODE) — expected calibration error
- `scripts/score_calibration.py:399` (STATIC_CODE) — Murphy decomposition
- `scripts/calibration_gate.py:16` (STATIC_CODE) — honest no-evidence gate

## Section E — Dashboard Truthfulness

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** The dashboard suppresses performance metrics below sample thresholds, labels every number with provenance and sample size, and shows honest no-data states instead of fabricated win rates or edge.

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| dashboard_no_data_honesty | True | `PASS` | 1.0 | STATIC_CODE | no real outcomes -> no fake win rate/Sharpe/edge |
| metric_visibility_by_provenance | True | `PASS` | 1.0 | STATIC_CODE | every displayed metric carries provenance + sample size + mode |
| performance_metric_suppression | 1.0 | `PASS` | 1.0 | TEST_RESULT | Sharpe/Sortino/drawdown/win-rate suppressed below sample gates |
| dashboard_failure_states | 1.0 | `PASS` | 1.0 | TEST_RESULT | >=0.75 of async sections have finite-state specs |

**Evidence:**

- `tests/test_score_calibration.py` (TEST_RESULT) — win_rate None at n=0
- `scripts/performance_truthfulness.py:168` (STATIC_CODE) — sample-gated metrics with provenance
- `frontend/src/components/AdvisoryEmptyState.tsx` (STATIC_CODE) — no-data variants

## Section F — Export / Auditability

- **Score:** 0.875
- **Status:** `WARN`
- **What it checks:** Audit reports and the new JSON envelope carry schema_version, generated_at_utc, provenance, source_count, and a content checksum, and round-trip losslessly. Legacy CSV exports still ship without metadata headers (WARN).

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| export_surface_coverage | 1.0 | `PASS` | 1.0 | STATIC_CODE | >=0.8 of required export surfaces available |
| export_schema_stability | True | `WARN` | 0.5 | STATIC_CODE | envelope adds schema_version/generated_at/provenance/source_count/checksum; legacy CSVs still lack it |
| round_trip_integrity | 1.0 | `PASS` | 1.0 | TEST_RESULT | 1.0 PASS (export -> parse -> verify checksum) |
| audit_traceability | True | `PASS` | 1.0 | STATIC_CODE | every headline number traces to file+source+provenance |

**Evidence:**

- `scripts/export_envelope.py:43` (STATIC_CODE) — checksummed envelope
- `scripts/gsheet_export.py:230` (STATIC_CODE) — CSV injection guard
- `tests/test_export_envelope.py` (TEST_RESULT) — round-trip proofs

## Section G — Failure Recovery

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** Bad inputs are rejected, runtime failures fail closed to NO_DATA/ERROR instead of crashing, destructive resets are guarded and tested, and new runtime artifacts are governance-stamped.

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| malformed_input_rejection | 1.0 | `PASS` | 1.0 | TEST_RESULT | 1.0 PASS (all malformed manual-trade inputs rejected; clean accepted) |
| fail_closed_runtime_behavior | True | `PASS` | 1.0 | STATIC_CODE | DB/log/JSON failures degrade to NO_DATA/ERROR, never crash |
| reset_recovery_safety | True | `PASS` | 1.0 | TEST_RESULT | reset: dry-run default + role guard + allowlist + safe-path + backup + tested |
| managed_runtime_artifact_coherence | True | `PASS` | 1.0 | STATIC_CODE | new runtime artifacts are governance-stamped (managed) |

**Evidence:**

- `scripts/manual_trade_validation.py:217` (TEST_RESULT) — malformed-input rejection
- `scripts/reset_local_logs.py:172` (STATIC_CODE) — guarded destructive reset
- `scripts/operational_readiness_audit.py:885` (STATIC_CODE) — managed artifact writer

## Section H — Release Readiness

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** Release tiers are defined (local-dev / paper / real-money pilot) with explicit thresholds; this audit is documented as a pilot-gate input. It is not yet a hard blocking gate because real outcomes are absent.

| Metric | Value | Status | Score | Provenance | Expected |
| --- | --- | --- | --- | --- | --- |
| release_gate_includes_operational_audit | True | `PASS` | 1.0 | STATIC_CODE | release gate runs this audit OR documents why not (pilot gate doc) |
| minimum_readiness_threshold | local-dev | `PASS` | 1.0 | STATIC_CODE | local-dev: no BLOCKER (paper/pilot tiers need higher scores) |
| branch_push_safety | True | `PASS` | 1.0 | STATIC_CODE | release gate + tests exist; full suite must pass before push |

**Evidence:**

- `docs/manual_money_pilot_gate.md` (STATIC_CODE) — pilot gate thresholds
- `scripts/release_gate.py:1` (STATIC_CODE) — release gate verdict

## Blocking Findings

None. No FAIL-level metric was detected.

### Warnings

| severity | section | finding | suggested fix |
| --- | --- | --- | --- |
| WARN | reconciliation_integrity | correction_audit_trail_presence is WARN (value=True; expected soft-cancel audit exists; full old/new correction journal is a gap). | Tighten correction_audit_trail_presence toward PASS. |
| WARN | export_auditability | export_schema_stability is WARN (value=True; expected envelope adds schema_version/generated_at/provenance/source_count/checksum; legacy CSVs still lack it). | Tighten export_schema_stability toward PASS. |

## Provenance Statement

Counts by provenance:

- **LIVE_MANUAL (real):** 0
- **IMPORTED_BACKTEST:** 0
- **SYNTHETIC:** 0
- **RUNTIME_DB records inspected:** 0
- **STATIC_CODE / TEST_RESULT:** structural guards + inline deterministic checks (see per-metric provenance).
- **NO_DATA:** calibration-on-real-outcomes and real-outcome field coverage (honest absence).

Disallowed mixing rules (enforced):
- SYNTHETIC outcomes can never be calibration-eligible or shown as live.
- IMPORTED_BACKTEST can never be presented as LIVE_MANUAL performance.
- PAPER outcomes can never be aggregated as real-money outcomes.
- Missing real outcomes surface as NO_DATA, never fabricated confidence.
- PARTIAL_DATA becomes MEASURED only with real (LIVE_MANUAL) outcomes.

## Pilot Gate

The MVP is currently: **`NOT_READY_NO_REAL_OUTCOMES`**.

Tier ladder: NOT_READY < REHEARSAL_READY < PAPER_READY < PILOT_READY < OPERATIONALLY_READY < FIELD_READY.

- **Local development:** allowed (no BLOCKER required; honest NO_REAL_OUTCOMES).
- **Paper-trading release:** needs readiness_score >= 0.70, no BLOCKER, and dashboard/manual-trade/reconciliation sections PASS.
- **Real manual-money pilot:** needs readiness_score >= 0.80, no BLOCKER, no synthetic/live contamination, and real outcomes displayed honestly even if small.

See `docs/manual_money_pilot_gate.md` for the full gate definition.

## Next Fixes

Ranked by `impact = safety * evidence_gap_reduction * operator_value / implementation_risk` (each 1-5):

1. **Capture real operator outcomes (LIVE_MANUAL closed trades).** _impact: 5*5*5/2 = 62.5._ This is the only thing that moves the audit from PARTIAL_DATA toward MEASURED and lifts evidence quality. _Acceptance:_ >=30 real closed outcomes with auditable provenance; calibration leaves NO_DATA.
2. **Wire `manual_trade_validation` into the live entry boundary** so bare tickers / unsupported exchanges are rejected at write time. _impact: 5*3*4/2 = 30._ _Acceptance:_ log_manual_trade rejects the malformed-input set; full suite green.
3. **Add export metadata headers to legacy CSV exports** (schema_version, generated_at, provenance, checksum). _impact: 3*3*4/2 = 18._ _Acceptance:_ export_schema_stability reaches PASS.
4. **Add a field-level correction journal** (old/new/actor/reason) for post-reconciliation edits. _impact: 4*2*3/3 = 8._ _Acceptance:_ correction_audit_trail_presence reaches PASS.
