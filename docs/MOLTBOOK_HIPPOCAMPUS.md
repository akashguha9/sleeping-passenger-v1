# Moltbook — the MVP's Hippocampus

## Purpose

Moltbook is episodic learning memory: the place where a *closed losing* manual
trade becomes exactly **one** advisory-only learning entry. If the loop's
hippocampus doesn't form a memory from a loss, the operator is doomed to repeat
it. Winning, flat, open, unreconciled, and fake/demo trades never create
loss-learning entries.

This behaviour already exists and is hardened; this doc is the operator-facing
map of it.

## Fields (canonical `moltbook_entries`)

`entry_id`, `event_id`, `ticker`, `original_signal_thesis`,
`ai_interpretation`, `user_reflection`, `final_human_decision`,
`manual_trade_log_id`, `outcome`, `mistake_type`, `lesson_learned`,
`bias_detected`, `recalibration_note`, `future_rule_update`, `logged_at`,
`advisory_status` (=`ADVISORY_ONLY`), `human_review_required` (=1),
`execution_mode` (=`HUMAN_ONLY`), `ai_execution_count` (=0).

Loss-review `mistake_type` values: `trade_loss`, `manual_exit_loss`,
`stop_loss_breach` (separate from the 12 signal-decision `MISTAKE_CATEGORIES`).

## Scripts

- `scripts/moltbook_reconciliation_bridge.py` — closed losing trade → one
  Moltbook entry. Read-only unless `--write`; idempotent (dedup by
  `manual_trade_log_id` → reconciliation_id → ticker+event). Provenance-gated by
  `manual_trade_origin.is_user_manual_trade` so probe/seed/import rows are excluded.
- `scripts/moltbook_api.py` — canonical SQLite write + JSONL audit mirror, with
  a test-isolation sentinel so monkeypatched tests can never leak into the
  runtime DB.
- `scripts/moltbook_cleanup_fake_seed.py` — narrow, idempotent removal of the
  historical fake SPY "Thesis A" seed rows (ADMIN-gated `--apply`).
- `scripts/closed_loop_learning_audit.py` — reports `closed_losses_without_moltbook`.

## Tests

- `tests/test_moltbook_reconciliation_bridge.py` — one entry per loss, no
  duplicates on rerun, non-loss/open/probe excluded, insufficient-data degrades
  to no entry, dry-run writes nothing.
- `tests/test_moltbook_truth_isolation.py`, `tests/test_moltbook_schema.py`,
  `tests/test_moltbook_api.py` — schema + truth isolation.

## Failure modes

- **Duplicate creation** — prevented by three dedup index sets; a rerun reports
  `skipped_duplicate` and creates nothing.
- **Fake trade creating a memory** — prevented by the provenance gate; demo /
  seed / fixture rows are not user-manual trades.
- **P/L invention** — refused; a loss with neither realized P/L nor entry+exit
  prices yields no entry (`skipped_insufficient_data`).

## Advisory-only safety note

Every entry carries `advisory_status=ADVISORY_ONLY`,
`execution_mode=HUMAN_ONLY`, `human_review_required=True`, `ai_execution_count=0`.
The bridge never places, modifies, or cancels a broker order. SQLite is
canonical; the JSONL mirror is audit-only.

## How to verify locally

```powershell
python scripts\moltbook_reconciliation_bridge.py            # dry-run
python -m pytest tests\test_moltbook_reconciliation_bridge.py -q
```
