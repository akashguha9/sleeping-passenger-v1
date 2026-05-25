# Defensive Alpha

## Purpose

The MVP's value is not only what it recommends — it is what it **prevents**: bad
promotions blocked, stale signals downgraded, fake consensus detected, fake data
kept out of release, and losses converted into lessons. Defensive alpha is real
product value even though it never shows up as a P/L gain. The report counts it.

## Fields

| Field | Source |
|---|---|
| `bad_promotions_blocked` | Cohorts flagged for downgrade/watch by the source-independence audit. |
| `stale_signals_downgraded` | Stale/expired signal cells (`business_value_report`). |
| `fake_data_rows_blocked` | `fake_rows_detected` (truth-purity audit). |
| `closed_losses_captured_as_lessons` | Loss-review Moltbook entries. |
| `source_echoes_detected` | Duplicate AI theses + duplicate catalysts across cohorts. |
| `operator_overload_warnings` | 1 when the queueing attention gate flags overload. |
| `compliance_blocks` | Reserved (0 unless wired to compliance preflight). |
| `advisory_only_invariants_verified` | From the closed-loop audit invariant scan. |
| `human_execution_required_verified` | From the closed-loop audit. |
| `total_defensive_events` | Sum of the prevention counts. |

## Scripts

- `scripts/defensive_alpha_report.py` — composes `business_value_report`,
  `runtime_truth_purity_audit`, `source_independence_audit`, and
  `closed_loop_learning_audit` so all numbers share one source of truth.

## Tests

`tests/test_defensive_alpha_report.py`:
- runs on empty DB; counts stale + repaired + echo events; counts fake-data
  blocks; verifies advisory-only invariants; never claims a P/L gain.

## Failure modes

- **DB missing** → counts default to zero, reported honestly.
- **Honesty contract** — the report must never claim profit/return; tests assert
  forbidden phrases are absent. Keep it a prevention ledger, not a returns claim.

## Advisory-only safety note

Counts prevention and record-keeping events only. `claims_pl_improvement` is
always `False`. No broker calls; advisory stamps on every output.

## How to verify locally

```powershell
python scripts\defensive_alpha_report.py
python -m pytest tests\test_defensive_alpha_report.py -q
```
