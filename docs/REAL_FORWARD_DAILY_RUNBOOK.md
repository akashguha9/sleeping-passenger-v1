# Real-Forward Outcome Maturation — Daily Operator Runbook

> **ADVISORY ONLY. Human execution required. No broker action. NOT real-money ready.**
> This loop attaches *real* outcomes to past advisory decisions after their
> prediction horizon has elapsed, recomputes calibration, and refreshes the
> evidence bundle. It places **no orders**, calls **no broker API**, and makes
> **no predictive claim** until the calibration gate passes
> (`N_real_forward >= 200`, `Brier <= 0.25`, `ECE <= 0.10`).

This is Kanté work: protect truth, protect timing, protect calibration, recycle
evidence daily. Make the maturation loop boring, repeatable, and auditable.

---

## Daily commands (PowerShell)

```powershell
cd "C:\Users\akash\sleeping-passenger-v1"

# 1. Read-only: what can attach today? When is the next horizon due?
python scripts/forward_outcome_maturity_scanner.py

# 2. Safe daily maturation: scan -> attach due -> calibrate -> bundle -> report.
#    (Dry-run by default; --write persists outcomes/calibration/bundle.)
python scripts/run_daily_outcome_maturation.py --write

# 3. Recompute calibration evidence on the real-forward corpus.
python scripts/real_calibration_evidence.py --write

# 4. Refresh the honest evidence bundle.
python scripts/real_evidence_bundle.py --write
```

Optional one-command pipeline (canary -> score -> decisions -> attach ->
calibrate -> bundle):

```powershell
python scripts/refresh_real_evidence.py --write
```

---

## Reading the maturity scanner

The scanner is **read-only** and classifies every snapshot:

| State             | Meaning                                                        |
|-------------------|----------------------------------------------------------------|
| `ATTACHED`        | A real-forward outcome `y ∈ {0,1}` is already recorded.        |
| `DUE_FORWARD`     | Eligible **and** the horizon has elapsed — can attach today.  |
| `PENDING_HORIZON` | Eligible but the horizon is still open — wait, do not attach.  |
| `INELIGIBLE`      | Structurally cannot carry a forward outcome (see reasons).     |

Key fields:

- `n_due_forward` — how many outcomes can attach right now.
- `next_due_in_hours` — hours until the next horizon becomes due
  (`0.0` if something is already due, `null` if nothing is open).
- `earliest_horizon_close_utc` — the next horizon-close timestamp.

---

## Rules (do not break these)

- **Do not run with fake dates.** Use the real clock. The `--now` override
  exists only for tests; never use it to pretend a horizon has elapsed.
- **Do not backdate.** A decision's `timestamp_utc` is never moved, and an exit
  price after the horizon close is never used.
- **Do not attach pending horizons.** If a horizon has not elapsed in real
  calendar time, leave it `PENDING_HORIZON`.
- **If `n_due_forward = 0`, stop.** The runner records
  `NO_DUE_FORWARD_SNAPSHOTS` and attaches nothing. That is the correct, honest
  outcome — there is nothing to mature today.
- **If outcomes attach, inspect Brier/ECE but do not claim calibration below N=200.**
  The gate is `I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)`. Below N=200
  the status is `FIRST_REAL_FORWARD_PAIRS_ATTACHED_BUT_BELOW_GATE` and
  `predictive_claim_allowed` stays `false`.
- **No fabricated evidence.** No fake ticker, no fake price, no fake
  probability, no fake outcome. A missing real price means the decision is
  excluded with a reason, never invented.
- **Push code only**, not the runtime DB (`runtime/mvp_local.db`) or generated
  JSON under `runtime/release/` and `data/daily_payload/`.

---

## Outcome math (for the auditor)

```
HorizonElapsed_i = I(now_utc >= decision_ts_i + horizon_days_i · 24h)
DueForward_i     = ForwardOutcomeEligible_i · HorizonElapsed_i
r_i              = (P_exit_i - P_entry_i) / P_entry_i
y_i              = I(r_i >= target_return_threshold_i)   # default threshold 0.0

Brier   = (1/N) Σ (p_i - y_i)^2
ECE     = Σ_b (n_b/N) |acc(b) - conf(b)|
LogLoss = -(1/N) Σ [y ln(p') + (1-y) ln(1-p')],  p' = clip(p, 1e-15, 1-1e-15)
CalibrationAllowed = I(N>=200) · I(Brier<=0.25) · I(ECE<=0.10)
```

---

## Safety invariants (must always hold)

```
ADVISORY_ONLY
HUMAN_EXECUTION_REQUIRED
execution_gate = LOCKED
broker_api_called = false
ai_execution_count = 0
predictive_claim_allowed = false   (until the calibration gate passes)
edge_claimed = false
real_money_ready = false
```
