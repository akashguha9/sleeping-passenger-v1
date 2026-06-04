# Outcome Import Workflow

Accrue resolved-outcome evidence so calibration can become real. Read-only
journal evidence — no broker, no execution.

## CSV schema (`templates/outcome_import_template.csv`)
`source_type, trade_id, signal_id, ticker, opened_at, closed_at, direction,
entry_price, exit_price, realized_pnl, capital_at_risk, leverage,
score_at_entry, archetype, signal_class, notes`

## Provenance rules
- `REAL_MANUAL_TRADE` / `PAPER_TRADE` — require `trade_id` or `signal_id`.
- `IMPORTED_BACKTEST` — prefer the backtest runner; manual CSV is accepted but warned.
- `SYNTHETIC_FIXTURE` — tests only; rejected at runtime.

## Return math (centralised in `outcome_evidence.py`)
- If `realized_pnl` and `capital_at_risk`: `r = pnl / capital_at_risk`.
- Else LONG: `r = (exit − entry)/entry`; SHORT: `r = (entry − exit)/entry`.
- Levered: `r_L = leverage · r`. Label by ε = 0.001.
- Missing exit AND pnl → OPEN/ineligible. Missing `score_at_entry` → ineligible.

## Eligibility
Eligible iff source ∈ {REAL, PAPER, BACKTEST} ∧ resolved label ∧ score present
∧ quality ≥ 0.70. Quality uses the `outcome_evidence` weighting.

## Steps
1. `python scripts/import_outcomes_csv.py outcomes.csv --dry-run --json` (validate)
2. `python scripts/import_outcomes_csv.py outcomes.csv` (idempotent write)
3. `python scripts/run_calibration_pipeline.py --json` (recompute calibration)

## Honesty
- `real_n` rises only from `REAL_MANUAL_TRADE`; readiness keys on `real_n`.
- `paper_n` / `backtest_n` improve signal quality and paper calibration but
  NOT real-money readiness.
- Imports are idempotent (PK = `source_type:trade_id|signal_id|ticker@opened_at`).
