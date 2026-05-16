# Outcome Calibration Readiness Gate (Sprint 10F)

This gate tells the operator how much to read into recorded paper-trade
and real-manual outcomes. It is intentionally conservative. The default
posture is **do not interpret the outcomes yet**.

> Paired tools:
> - `scripts/calibration_gate.py` — read-only DB scan, prints status
> - `scripts/local_mvp_audit.py --section calibration` — adjacent report
> - `docs/PAPER_LEDGER_OPERATING_ROUTINE.md` — the source of paper rows
> - `docs/PRIVATE_OPERATOR_DAILY_CHECKLIST.md` — when to run this

---

## 1. Why a gate, not a dashboard

A single-trader local MVP can record many paper rows and very few real
ones. Without a gate, the temptation is to read a small sample as if it
were edge. That is the bias the system is meant to resist.

The gate's job is to be louder than the operator's enthusiasm:

- Below 5 qualifying rows: **NOT_READY**. Do not interpret outcomes.
- 5–19 rows: **VERY_LOW_CONFIDENCE**. Only inspect process errors.
- 20–49 rows: **LOW_CONFIDENCE**. Look for repeated operator mistakes,
  not profitability.
- 50+ rows: **REVIEWABLE**. Review process patterns. Still not real-
  money proof.

There is no `EDGE_PROVEN` band, by design. Paper outcomes never reach
"edge proven" — see section 6.

---

## 2. The gate equation

```
Paper_Calibration_Ready =
  Rows_With_Paper_Mode
× Rows_With_Reactor_Snapshot
× Rows_With_Outcome
× Rows_With_Process_Label
× Rows_With_Lesson
```

The reported `with_snapshot_and_outcome` is the conservative numerator:
a row only counts if it had a reactor snapshot recorded at decision
time *and* an outcome status that is not `UNKNOWN`. `fully_qualifying`
adds the process label and the lesson — that's what the operator should
actually drive toward.

Real-manual calibration uses the same equation but counts rows with
`trade_mode = REAL_MANUAL`. It is reported in its own block. If real
rows = 0 the status is `NO_REAL_OUTCOME_EVIDENCE` and no other claim
is made.

---

## 3. CLI usage

```powershell
python scripts/calibration_gate.py
python scripts/calibration_gate.py --json
python scripts/calibration_gate.py --db-path <path-to-mvp_local.db>
```

Sample text output (paper rows = 0):

```
Sleeping Passenger - Outcome Calibration Gate
db_path        : ...\runtime\mvp_local.db
db_available   : True

PAPER:
  status                       : NOT_READY
  message                      : Do not interpret paper outcomes yet.
  total rows                   : 0
  ...
  rows needed for next band    : 5

REAL:
  status                       : NO_REAL_OUTCOME_EVIDENCE
  message                      : No real-manual outcome rows recorded; calibration not applicable.
  ...
```

The JSON form carries the standard advisory stamps (`advisory_only`,
`execution_gate=LOCKED`, `broker_api_called=false`, `can_execute=false`,
`ai_execution_count=0`) and an explicit `no_claims` list.

---

## 4. Status thresholds (paper)

| Qualifying rows | Status | What the operator may do |
|---|---|---|
| < 5 | `NOT_READY` | Read process notes only. No outcome-level inference. |
| 5–19 | `VERY_LOW_CONFIDENCE` | Inspect *process* errors only. No edge claim. |
| 20–49 | `LOW_CONFIDENCE` | Track repeated operator mistakes. Still no profitability claim. |
| ≥ 50 | `REVIEWABLE` | Review process patterns and category-level decisions. Still not real-money proof. |

`rows_needed_next` is the integer count the operator needs to add to
reach the next band. Use it as a friction signal — not as a deadline.

---

## 5. Status thresholds (real-manual)

The same numeric bands apply with `trade_mode = REAL_MANUAL`. The
extra status `NO_REAL_OUTCOME_EVIDENCE` is reported when no real-manual
rows exist at all.

The real-manual gate is **not** meant to fast-track real-money
deployment. It exists so the operator can later compare process-quality
on real captures vs. process-quality on paper captures.

---

## 6. What the gate does NOT do

- It does **not** compute a hit rate.
- It does **not** compute expected value.
- It does **not** compute Sharpe / win rate / edge / slippage / fills.
- It does **not** unlock the execution gate.
- It does **not** authorize a trade.
- It does **not** call any broker.
- It does **not** claim "alpha", "edge", "real-money proof", or
  "profitability". The `no_claims` field is explicit.

If the script ever output a profitability claim, that would be a bug.
Treat it as a failed invariant and fix the script, not the assumption.

---

## 7. When to run

- **Daily** as part of the evening checklist (see
  `docs/PRIVATE_OPERATOR_DAILY_CHECKLIST.md` §4).
- **After any reconciliation pass.** Outcomes only count once their
  full reconciliation row is recorded.
- **Before any reflection that wants to claim "the system is working".**
  Read the gate before writing that sentence. Re-write the sentence to
  match the gate.

---

## 8. Safety invariants

```
ADVISORY_ONLY = true
HUMAN_EXECUTION_REQUIRED = true
execution_gate = LOCKED
BROKER_ORDER_PERMISSION = false
AI_EXECUTION = 0
broker_api_called = false
execution_permission = false
can_execute = false
PAPER_TRADE_ONLY = true (for paper rows)
REAL_CAPITAL_AT_RISK = false (for paper rows)
BROKER_ORDER_ID = "NONE"
EXECUTION_REAL = false
```

The gate carries these stamps in every JSON payload. Removing them
would be a regression.
