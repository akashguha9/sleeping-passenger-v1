# Real-money readiness — effect of the 2026-05/06 paper book

**Decision:** journal-only import, PAPER provenance (per operator).

## What was done
- Generated `outcomes.csv` (61 rows) from the paper book via the strategy engine
  (realized P/L per position, €50 capital at risk, LONG, opened→2026-06-04 close).
- Imported through the official pipeline:
  `python scripts/import_outcomes_csv.py analysis/portfolio_2026_05/outcomes.csv`
  → 61 accepted / 61 written to `imported_outcomes` (idempotent, advisory-only).

## Effect on readiness: **none — by design**

| | Before | After |
|---|---|---|
| Readiness score | 6.5 / 8.0 | **6.5 / 8.0** |
| Allowed mode | TINY_MANUAL_PROBE_ONLY | **TINY_MANUAL_PROBE_ONLY** |
| calibration_status | NO_DATA | NO_DATA |
| eligible_n | 0 | **0** (paper_n=61) |

The 61 rows are **calibration-ineligible** (`missing_score_at_entry`). The gate
keys above 6.5 on the **calibration** dimension only, and calibration needs each
outcome paired with the score the engine assigned **at entry**. The book carries
no entry scores (runtime DB was empty; holdings JSON has none), so none were
invented — the rows stand as honest paper journal evidence and nothing more.

## Why 6.5 is the ceiling right now
`R_raw = 7.0`, capped to 6.5 by: `calibration C=0.0 → cap 6.5`. Other dimensions
are already maxed/non-binding (A,E=1.0; persistence 0.5; leverage-gov 1.0;
tests/backup/UI ok). `securities_coverage J=0.0` only caps at 7.0, so it is **not**
the binding constraint today.

## The only legitimate way up
1. **6.5 → ~7.0 (MANUAL_REAL_MONEY_READY_SMALL_ONLY):** attach a real
   `score_at_entry` (engine score, or operator `confidence_before` 0–1) to resolved
   outcomes until calibration reaches CALIBRATED on paper. Paper caps here.
2. **~7.0 → 8.0 (…_CALIBRATED):** accumulate **≥50 `REAL_MANUAL_TRADE`** resolved
   outcomes (not paper) carrying entry scores. Real-money sizing keys on `real_n`.
3. Independently, raising `securities_coverage` (J) clears the
   `securities_coverage_weak` warning but won't lift the score past the calibration cap.

## Honesty stamps preserved
Advisory-only, human execution required, broker_api_called=False, execution gate
LOCKED throughout. No score, return, or provenance was fabricated.
