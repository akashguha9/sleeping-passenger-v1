# Closed-Loop Learning Model

## Purpose

The Sleeping Passenger MVP is a closed-loop advisory intelligence refinery for
**manual** decision quality. Its value compounds only if every signal can be
walked all the way to a lesson:

```
signal_event
  -> model / advisory report
  -> manual trade log
  -> reconciliation / outcome
  -> Moltbook entry
  -> lesson / recalibration candidate
  -> future rule candidate
```

A break anywhere in that chain is a leak. `closed_loop_learning_audit.py` walks
the chain over the canonical SQLite DB and reports where it is broken, plus the
ARC-style learning-efficiency score (see `LEARNING_EFFICIENCY.md`).

## Fields

| Field | Meaning |
|---|---|
| `closed_loop_coverage` | Fraction of reconciled operator trades whose chain is complete (loss → Moltbook, or not-a-loss). |
| `signals_without_outcomes` | `signal_events` with no reconciliation referencing their `event_id`. |
| `manual_trades_without_reconciliation` | Real operator trades with no reconciliation row (open, unrecorded risk). |
| `closed_losses_without_moltbook` | Closed losing trades not yet captured as a Moltbook lesson (from the bridge dry-run). |
| `moltbook_entries_without_trade_reference` | Loss-review Moltbook entries with a blank `manual_trade_log_id` (orphaned lessons). |
| `lessons_without_recalibration_candidate` | Moltbook entries with a blank `recalibration_note`. |
| `future_rule_candidates_count` | Moltbook entries with a non-blank `future_rule_update`. |
| `unresolved_repair_debt` | Sum of the broken-edge counts above. |
| `learning_efficiency` | Nested block (see `LEARNING_EFFICIENCY.md`). |
| `advisory_only_verified` / `human_execution_verified` / `broker_api_called_false_verified` / `ai_execution_count_zero_verified` | Invariant scans over canonical tables. |

## Scripts

- `scripts/closed_loop_learning_audit.py` — read-only audit. `--repair`
  delegates to the role-gated `moltbook_reconciliation_bridge.py --write`.
- Reuses `scripts/moltbook_reconciliation_bridge.py` for the canonical
  "closed loss → one Moltbook entry" detection.

## Tests

`tests/test_closed_loop_learning_audit.py`:
- runs safely on empty / missing DB;
- does not create execution state (row counts unchanged after a run);
- detects a closed loss with no Moltbook entry;
- verifies advisory-only invariants and flags an injected `broker_api_called`
  breach;
- learning-efficiency formula, repeat-penalty, and zero-loss safety.

## Failure modes

- **DB missing** → all counts default to zero, reported honestly (`db_available=False`).
- **Loss with no realized P/L and no prices** → the bridge degrades to "insufficient
  data" and does not invent a loss; such trades are not counted as missing-Moltbook.
- **Huge `signals_without_outcomes`** is expected: most signals never become trades.
  It measures funnel width, not a defect.

## Advisory-only safety note

Read-only by default. The only write path is `--repair`, which is gated through
`operator_audit_log.enforce` and only ever creates advisory Moltbook entries.
No broker order is placed; `broker_api_called` stays `False`,
`ai_execution_count` stays `0`, `execution_gate` stays `LOCKED`.

## How to verify locally

```powershell
python scripts\closed_loop_learning_audit.py
python -m pytest tests\test_closed_loop_learning_audit.py -q
```
