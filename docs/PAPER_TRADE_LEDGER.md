# Paper-Trade Ledger (Sprint 7B.2)

> **Self-audit, not externally validated.**  This ledger and its
> scoring are operator-side artifacts.  No external auditor has
> reviewed them.
>
> **Calibration status: `INSUFFICIENT_EVIDENCE`** unless real outcome
> rows exist.  `N_real` must be displayed next to any readiness score
> derived from this ledger (see `docs/EVIDENCE_BUNDLE.md`).
>
> Lamborghini state labels (MIURA, MURCIÉLAGO, DIABLO, …) are
> *internal routing labels*, not proven predictive classes.  Do not
> cite them as such in any operator or customer-facing copy.
>
> Customer-facing mode is disabled or `DEMO_ONLY / UNCALIBRATED` until
> the proof-loop threshold is met (`N_real >= 20` and
> `evidence_status` ∈ {`SUFFICIENT_FOR_INVESTOR_DEMO`,
> `SUFFICIENT_FOR_PRIVATE_BETA`}).

The paper-trade ledger lets the operator rehearse the full signal →
decision → outcome → reconciliation loop using an Excel-maintained CSV.
No broker is contacted.  No order is placed.  No real capital is
committed.  Imported rows carry `trade_mode='PAPER'` and the safety
invariants below stay locked.

## Purpose

Paper trading is rehearsal/calibration infrastructure.  It tests:

- whether the workflow is usable end-to-end
- whether reactor-at-decision snapshots are captured
- whether delayed reconciliation actually happens
- whether learning completeness reports classify outcomes correctly
- whether the UI / API / data plumbing all line up
- whether the operator catches their own process mistakes

Paper trading is **not** proof of:

- real-money alpha
- real slippage survivability
- real emotional behaviour under pressure
- broker execution correctness
- production readiness

## Safety invariants (frozen for every paper row)

```
PAPER_TRADE_ONLY      = True
REAL_CAPITAL_AT_RISK  = False
BROKER_ORDER_ID       = "NONE"
BROKER_API_CALLED     = False
EXECUTION_PERMISSION  = False
CAN_EXECUTE           = False
EXECUTION_GATE        = "LOCKED"
AI_EXECUTION_COUNT    = 0
ADVISORY_STATUS       = "ADVISORY_ONLY"
HUMAN_REVIEW_REQUIRED = True
```

## Excel workflow

1. **Export the template once.**

   ```
   python scripts/export_paper_trade_template.py
   ```

   Writes `exports/paper_trade_template.csv`.  Open it in Excel.

   `--include-example` writes one obviously-fake example row
   (`EXAMPLE_TICKER`) so the column layout is visible; delete it before
   importing.

2. **Fill rows BEFORE the outcome is known.**  Set `paper_trade_id`,
   `symbol`, `side`, `thesis`, the planned entry/exit/invalidation,
   *and the reactor-at-decision snapshot you saw at decision time*.

   The reactor snapshot is the single most useful column block for
   calibration — fill it.

3. **Dry-run validate.**

   ```
   python scripts/import_paper_trades.py --file exports/paper_trade_template.csv --dry-run
   ```

   Validates every row.  No DB mutation.  Reports `rows_seen`,
   `rows_valid`, `rows_rejected` and a reason for each rejection.

4. **Write valid rows into the DB.**

   ```
   python scripts/import_paper_trades.py --file exports/paper_trade_template.csv --write
   ```

   Every accepted row lands in `manual_trades` with `trade_mode='PAPER'`
   and the safety stamps above.  Duplicates by `paper_trade_id` within
   the same file are flagged and rejected.

5. **Update outcomes LATER.**  When the planned holding period
   completes, fill `outcome_status`, `outcome_quality`, `process_quality`,
   `mistake_tags`, `lesson`, `paper_entry_price`, `paper_exit_price`,
   `paper_return_pct`, `paper_pnl_nominal`.  Then re-import (the
   `INSERT OR IGNORE` semantic protects against duplicate writes).

6. **Round-trip the current paper rows back to Excel for review.**

   ```
   python scripts/export_paper_trades.py --out exports/paper_trades_review.csv
   ```

   Read-only on the DB.

## Required columns

```
paper_trade_id   — unique per row (your choice of slug)
symbol           — ticker / contract identifier
side             — BUY or SELL
thesis           — one-sentence reason for the rehearsal
```

Empty / missing required columns cause the row to be rejected with
`missing_required:<column>`.

## Optional columns (highly encouraged)

- Reactor-at-decision snapshot (9 fields)
- `invalidation_level`, `time_horizon`, `risk_notes`
- `planned_entry`, `planned_exit`
- `outcome_status`, `outcome_quality`, `process_quality`
- `mistake_tags`, `lesson`, `journal_complete`, `reconciled_at`
- Paper economics: `paper_entry_price`, `paper_exit_price`,
  `paper_return_pct`, `paper_pnl_nominal`, `benchmark_return_pct`,
  `holding_period_days`
- `source_freshness_state_at_decision`

The reactor snapshot block + the outcome block together are what feed
the calibration report.  Paper rows count toward the reactor-snapshot
inventory but are **not** treated as real-money calibration evidence.

## Rejection rules

A row is rejected (no DB write) when any of these hold:

- a required field is empty
- the row carries a broker-like header
  (`broker_order_id`, `execution_permission`, `place_order`, ...) with a
  non-empty value
- any cell contains a forbidden phrase
  (`place order`, `submit order`, `execute trade`, `trade now`,
  `broker api`, `real money`)
- the `paper_trade_id` was already seen in this file

Rejected rows are reported with `rejection_reasons`.  Nothing is
persisted on `--dry-run` or for rejected rows on `--write`.

## How paper trades feed calibration

`scripts/reactor_calibration_report.py` reads `manual_trades` and the
reconciliation table.  Rows with `trade_mode='PAPER'` contribute to
`reactor_snapshot_count` and the per-label counts.  The report's
`calibration_confidence_band` is driven by the count of trades with
**both** a reactor snapshot AND a reconciled outcome.  Paper rows can
satisfy this count, but the report's prose disclaimer is permanent: at
small n, per-label counts are descriptive evidence, not estimates of
skill.

## How to avoid lookahead bias

1. **Write the decision row BEFORE the outcome is known.**  Set
   `outcome_status=OPEN` or leave it empty until the holding period
   completes.
2. **Do not edit the reactor snapshot after the fact.**  The reactor
   snapshot is the operator's view at decision time; editing it later
   destroys the calibration signal.
3. **Update only the outcome columns** when reconciling.  Treat the
   pre-trade columns as append-only.

## What this workflow CANNOT do

- It cannot place a trade.  The MVP refuses.
- It cannot prove real-money alpha.  Paper outcomes are simulation.
- It cannot reach a broker, exchange, or any third-party execution API.
- It cannot bypass `MVP_API_TOKEN` if you have that token set on the
  HTTP boundary.

If your CSV ever needs a `broker_order_id` column, you are not running
this MVP — you are running something else.
