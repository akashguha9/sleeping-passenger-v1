# Local Evidence Pipeline

Turns "calibration machinery exists" into "locally runnable evidence". No
network. No broker. No execution. Provenance is explicit at every step.

## Steps & commands
1. Seed securities master:
   `python scripts/securities_master_coverage.py --seed`
   then verify: `python scripts/securities_master_coverage.py --json`
2. Import historical OHLCV (read-only):
   `python scripts/import_ohlcv_csv.py bars.csv` (idempotent; --dry-run to preview)
3. Backtest scored signals vs imported OHLCV (IMPORTED_BACKTEST, no lookahead):
   `python scripts/run_imported_backtest.py --signals signals.json`
4. Import resolved outcomes (PAPER/REAL):
   `python scripts/import_outcomes_csv.py templates/outcome_import_template.csv`
5. Run the full pipeline:
   `python scripts/run_calibration_pipeline.py --import-outcomes outcomes.csv --json`

## Provenance separation (non-negotiable)
| source_type | counts toward | lifts real-money readiness? |
|-------------|---------------|------------------------------|
| REAL_MANUAL_TRADE | real calibration | yes (real_n>=50, CALIBRATED, human-approved) |
| PAPER_TRADE | paper/signal quality | no |
| IMPORTED_BACKTEST | signal quality | no |
| SYNTHETIC_FIXTURE | tests only | never (rejected at runtime) |

## Verified end-to-end
60 imported PAPER outcomes -> calibration_status CALIBRATED (ECE 0.084,
Brier 0.157), Platt recalibration oos_improved=True, signal quality lifted,
yet readiness stays TINY_MANUAL_PROBE_ONLY and can_drive_sizing=False because
real_n=0. The gate keys on real outcomes only.

## Current runtime (this checkout)
real_n=22 (logged trades) but eligible_n=0 — they lack score_at_entry and/or
reconciliation, so calibration is honestly NO_DATA. Next operator action:
reconcile those trades and supply score_at_entry (or import outcomes CSV).
