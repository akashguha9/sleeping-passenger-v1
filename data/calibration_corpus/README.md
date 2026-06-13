# Calibration corpus (local runtime data — NOT canonical, NOT committed)

This directory holds **runtime** forward-capture output from the advisory
runner. It is operator-local state, not source of truth.

## What is tracked vs ignored

| File | Tracked? | Why |
|------|----------|-----|
| `README.md` | ✅ tracked | this doc |
| `paper_trade_ledger_template.csv` | ✅ tracked | empty template for manual outcome reconciliation |
| `decisions.jsonl` | ❌ **gitignored** | runtime capture; committing it would pollute the calibration corpus with non-canonical / demo rows |

The `decisions.jsonl` ignore rule lives in the repo root `.gitignore`. Never
force-add it. Each operator regenerates it locally by running the advisory
runner with capture enabled (see `docs/OPERATOR_QUICKSTART.md`).

## Calibration honesty

A captured snapshot is **calibration-eligible** only when it is
feature-bearing, has a resolved outcome label in
`{WIN, LOSS, AVOIDED_TRAP, FALSE_POSITIVE, FALSE_NEGATIVE, MISSED_WINNER}`, and
its `source_type` is not `SYNTHETIC_FIXTURE`. Demo captures (`--demo`) are
forced to `SYNTHETIC_FIXTURE` and can never become eligible.

Readiness ladder (`--check-corpus`):

- `N_eligible < 10` → insufficient evidence
- `10 ≤ N < 30` → provisional diagnostic
- `30 ≤ N < 100` → first-pass calibration
- `N ≥ 100` → stronger calibration ready

Real-money execution is **PROHIBITED** everywhere in this pipeline.
