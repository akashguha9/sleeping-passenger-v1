# Pre-Real-Money Checklist

> One page. Run this before any day on which you intend to log
> real-money manual trades.
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `execution_permission = false` · `can_execute = false`
>
> Nothing in this checklist touches a broker, places an order, or grants
> execution permission. Every action that moves money is taken by the
> operator outside the app.

---

## 1. Preflight bundler (one command)

```powershell
python scripts/pre_real_money_preflight.py --json
```

Proceed only if `"ok": true`. If `"ok": false`, read `blocking_issues`,
fix them, re-run.

## 2. If preflight failed — diagnose individually

```powershell
python scripts/db_integrity_check.py --json
python scripts/local_security_audit.py --json
python scripts/source_refresh_audit.py --days 7 --json
python scripts/reconciliation_queue.py --json
python scripts/self_test_report.py --days 30 --json
```

## 3. Backup discipline

- Have you run `python scripts/backup_db.py` in the last 24 hours?
- Is the latest backup openable? (`db_integrity_check` reports this.)
- Off-machine copy: did you sync `runtime/backups/` to an external
  drive or encrypted cloud folder this week?

## 4. Source freshness

- `python scripts/run_live_refresh.py --source all --plan-only --json`
- For each implemented source: is `freshness_state` in `{fresh, stale}`,
  not `{overdue, failed}`?
- For sources you actually plan to lean on today, are they `fresh`?

## 5. Unreconciled-backlog gate

| Unreconciled count | State | Operator rule |
|---|---|---|
| 0–9 | clean | Proceed normally. |
| 10–24 | WARN | Proceed but clear queue within the week. |
| 25–49 | BLOCK | Reconcile first; no new real-money trades today. |
| 50+ | FULL REVIEW | Stop. Spend the day reconciling and writing lessons. |

The preflight encodes these thresholds; the discipline is yours.

## 6. Operator state self-check

Before logging a manual trade, write this in your head (or in the
journal if it helps):

- Sleep last night ≥ 6 hours?
- Emotional state neutral (no revenge, no FOMO, no euphoria)?
- Did I follow my own pre-trade checklist?
- Is this trade my own thesis, or did I copy it from a stream/tweet?
- If I lose 1R on this trade, will I still be calm tomorrow?

If any answer is no — do not log the trade. The MVP cannot enforce
this; the discipline is yours.

## 7. Journal fields before, lessons after

When you DO log a manual trade, fill these journal fields in the form:

- `thesis` — the one-line reason you took the trade.
- `invalidation_level` — the price / event / time that proves you wrong.
- `expected_horizon` — how long you expect the trade to take.
- `risk_reason` — why this size, not larger or smaller.
- `entry_reason` — what specifically triggered the entry.
- `exit_plan` — when / how you will exit (win OR loss).
- `confidence_before` — 0–1 (or 0–100), pre-trade.
- `emotional_state` — calm / fomo / revenge / etc.

Inside 1–3 trading days of the trade closing:

- Reconcile through `/reconciliation` or the API.
- Set `outcome_status`, `outcome_quality`, `process_error` (or `none`),
  `mistake_tags`, and a one-line `lesson`.

## 8. End-of-week ritual

```powershell
python scripts/self_test_report.py --period monthly --json
python scripts/backup_db.py --label weekly
```

Re-read the limitations section of the report. If it says
`no_trades_reconciled_yet` or `unreconciled_backlog_warn`, that is
your assignment for next week.

## 9. Things this checklist will not save you from

- Bad theses dressed up as good ones.
- Acting on echo (10 sources, 1 actual independent voice).
- Forcing trades because you ran the checklist and feel "ready".
- Emotional decisions that pass every mechanical check.

The checklist is the floor. Your judgment is the ceiling.

---

## Discipline gate formula

```
Manual_Trade_Allowed_By_Discipline =
    Preflight_OK
  × Journal_Fields_Ready
  × Source_Status_Known
  × Unreconciled_Backlog_Under_Limit
  × Operator_State_Not_Compromised
```

If any factor is zero, you do not log a real-money trade today.
