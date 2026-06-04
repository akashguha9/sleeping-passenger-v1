# Real-Money Manual Readiness

Honest gate before logging real-money manual trades.
`scripts/pre_real_money_preflight.py :: assess_real_money_readiness()` and
`GET /api/readiness/real-money`. Advisory-only; never authorises execution.

## Allowed modes
- `SCALE_BLOCKED` — an execution surface was detected (advisory invariants
  broken). Hard fail, score 0.
- `PAPER_ONLY` — blocking issues (leverage governance missing, preflight
  blockers, or failing tests). Paper trading only.
- `TINY_MANUAL_PROBE_ONLY` — safety + leverage hold but scores are
  UNCALIBRATED. Tiny manual probes only; do not size from scores.
- `MANUAL_REAL_MONEY_READY` — safety, leverage, calibration status, and the
  feedback loop all hold. Manual real-money permitted with discipline.

## Score caps (enforced by tests)
- execution surface present → **0.0** (hard fail)
- leverage governance missing → cap **5.0**
- calibration UNCALIBRATED → cap **6.5**
- backend/frontend tests failing → cap **6.0**
- preflight blocking issues → cap **6.0**
- everything clean → may reach **7.0** — and never more.

`READINESS_MAX = 7.0`. **This gate can never certify scaling.** Scaling needs
a sustained CALIBRATED sample of real reconciled outcomes, which a single-user
journal accrues slowly.

## What still blocks 8/10 and scaling
- Scores remain empirically UNCALIBRATED until real reconciled outcomes accrue
  (the mechanism exists; the evidence does not yet).
- The feedback loop recommends but never auto-applies threshold changes.
- Single-operator outcome volume is low, so calibration confidence is capped.

## Tests
`tests/test_real_money_readiness.py`, `tests/test_pre_real_money_preflight.py`.
