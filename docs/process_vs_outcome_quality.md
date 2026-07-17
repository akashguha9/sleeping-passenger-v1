# Process Quality vs Outcome Quality

`process_outcome.py` separates disciplined reasoning from luck.

## Process quality (outcome-independent)
Scored at prediction time from evidence completeness/freshness, provenance,
uncertainty honesty, scenario coverage, tail preservation, decision consistency,
and **no-execution compliance** (a hard gate — a violation caps process quality at
3.0). Knowable without any outcome.

## Four-quadrant classification
`classify(process, outcome)` →
- `GOOD_PROCESS_GOOD_OUTCOME` → reinforce.
- `GOOD_PROCESS_BAD_OUTCOME` → **protect process credit** (do NOT punish a
  well-calibrated process for one probabilistic loss).
- `BAD_PROCESS_GOOD_OUTCOME` → **flag lucky process** (do NOT reward luck).
- `BAD_PROCESS_BAD_OUTCOME` → correct the process.

Each verdict emits a `ledger_signal` the RACR contribution ledger consumes, so the
system learns from decision-process quality, not merely realised returns. Tested:
`test_four_quadrant_classification`, `test_process_quality_capped_on_no_execution_violation`.
