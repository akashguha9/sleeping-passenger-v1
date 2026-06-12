# Calibration First Light — the ledger's first non-synthetic rows

**Date:** 2026-06-12 · **Pinned by** `tests/test_first_light_calibration.py`
· **Fixture:** `examples/outcomes/first_light_empirical.jsonl`
· **Run it:** `python scripts/import_outcomes.py examples/outcomes/first_light_empirical.jsonl --streak`

## Data source and tier

Four resolved trades converted 1:1 from the **operator's committed
journal** (real, tiny-probe-sized positions):

* `moltbook/mw_direction_v1_2026_04_19.json` — the operator's own
  resolved 4-trade pattern record
* `moltbook/signal_ledger.json` — frozen pre-entry CE scores + statuses
* `moltbook/fcg_2026q2_close.json` — full FCG close record

**Tier: `empirical` (operator-attested).** These are real decisions
with real recorded outcomes — but attested by the operator's journal,
not externally verifiable from inside this repo. Network egress is
blocked here (verified: market-data hosts are not allowlisted), so no
real OHLCV could be fetched; the journal is the highest-tier evidence
the repo contains, and it was already committed before this exercise.

## What was imported (n = 4)

| Trade | Pre-entry record | Gate behaviour | Outcome |
|---|---|---|---|
| TLT | CE 0.62, approved | veto did not fire | **+1.23%** |
| TIP | CE 0.68, approved | veto did not fire | **+4.19%** |
| UNG | CE 0.35, CHAOS | veto FIRED, overridden | **−4.49%** |
| FCG | CE 0.30, CHAOS | veto FIRED, overridden | **−8.67%** |

Import discipline (all test-pinned):

* Returns imported **as recorded** (`return_basis: recorded_return`) —
  raw prices were not journaled for 3 of 4 trades, and fabricating
  price pairs would be dishonest.
* **No alpha is claimed** (`alpha_basis: absolute_return_no_benchmark`,
  `mean_realized_alpha: null`, `rows_without_benchmark: 4`) — no
  benchmark was journaled.
* **No `predicted_edge`** — the journal froze conviction (CE scores),
  not return forecasts; mapping CE to an edge would be fabrication, so
  `prediction_error` is honestly `null`.
* Open positions (`moltbook/open_positions.json` shapes) are **rejected
  by the importer** — unresolved predictions cannot enter the resolved
  ledger.

## Results

```
win_rate                0.50          mean_absolute_return  −1.94%
streak_reliability      1.00          (both wins carry the named
causal_confidence       ≤ 0.50         CE-discipline mechanism;
warnings                SMALL_SAMPLE   both losses were tagless
                                       chaos overrides)
```

**Gate utility (`summarize_gate_outcomes`)** — `ce_threshold_veto`:
2 observed counterfactuals (both veto overrides lost: the gate would
have avoided both losses), 0 harmful, 2 pass-through. Verdict:
**`insufficient_data`, leaning `helpful`** — two counterfactuals are an
anecdote, not a measurement (floor: 3).

## What this proves / does not prove

**Proves:** the full evidence pipeline runs on real records end-to-end —
journal → tiered import → calibration summary → gate-utility
counterfactuals → streak audit — with every honesty guard engaging on
real data (no alpha without benchmark, no prediction error without a
frozen forecast, no verdict below the observation floor, tier separation
intact). The ledger is no longer empty scaffolding.

**Does not prove:** that the model or the CE discipline has edge. n=4,
single asset cluster (rates + nat gas), one month, no benchmark, and
the 2W/2L split with a perfect discipline pattern is exactly the kind
of result the repo's own streak audit warns about (`SMALL_SAMPLE`).

## Calibration maturity cap

With 4 operator-attested rows and 6 labeled synthetic seed rows:
**calibration maturity is capped at ~6.0/10.** Raising it requires
(in order of value): journaling `predicted_edge` + benchmark at entry
going forward (the lifecycle ledger's `entry_from_lifecycle` exists for
exactly this), reconciling ≥10 resolved rows, and importing real OHLCV
via `scripts/import_ohlcv_csv.py` for backtest-tier breadth.
ADVISORY_ONLY throughout; nothing here sizes or routes anything.
