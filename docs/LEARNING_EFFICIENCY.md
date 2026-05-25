# Learning Efficiency

## Purpose

ARC-style intelligence is **learning efficiency**, not signal volume. The
question is not "how many signals did we ingest?" but "did each closed loss
become a lesson, and did we stop repeating it?" The learning-efficiency block
turns that into a number.

## Fields / formulas

```
lesson_conversion_rate    = moltbook_lesson_count / max(closed_loss_count, 1)
repeat_error_rate         = repeat_mistake_count  / max(moltbook_lesson_count, 1)
learning_efficiency_score = lesson_conversion_rate * (1 - repeat_error_rate)
```

| Field | Meaning |
|---|---|
| `closed_loss_count` | Closed losing operator trades (loss candidates + insufficient-data losses). |
| `moltbook_lesson_count` | Loss-review Moltbook entries. |
| `recalibration_candidate_count` | Entries with a non-blank `recalibration_note`. |
| `future_rule_candidate_count` | Entries with a non-blank `future_rule_update`. |
| `repeat_mistake_count` | Repeated `(ticker, mistake_type)` pairs (count − 1 per group). |
| `no_loss_history` | `True` when there are no closed losses yet. |

**Zero-loss safety:** with no losses and no lessons, the score is reported as a
neutral `1.0` with `no_loss_history=True` rather than a misleading `0.0`.

## Scripts

- Folded into `scripts/closed_loop_learning_audit.py` (`compute_learning_efficiency`
  pure function + `learning_efficiency` block in the report). No separate module
  is added, to avoid bloat.

## Tests

`tests/test_closed_loop_learning_audit.py`:
- `test_learning_efficiency_formula` — conversion + repeat + score compute correctly;
- `test_learning_efficiency_repeats_penalize_score` — repeats lower the score;
- `test_learning_efficiency_zero_loss_is_safe` — no-loss case is safe and bounded.

## Failure modes

- **Lessons without losses** (e.g. signal-decision entries) — `repeat_error_rate`
  uses `moltbook_lesson_count` as the denominator; only loss-review entries are
  counted as lessons here, keeping the ratio meaningful.

## Advisory-only safety note

Pure computation over canonical counts. No DB writes, no broker calls; the parent
audit carries the advisory-only stamps.

## How to verify locally

```powershell
python scripts\closed_loop_learning_audit.py --json
python -m pytest tests\test_closed_loop_learning_audit.py -q
```
