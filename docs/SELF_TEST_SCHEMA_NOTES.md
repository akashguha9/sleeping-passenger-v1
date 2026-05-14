# Self-Test Schema Notes — Manual Journal & Reconciliation

> Companion to [SELF_TEST_BOTTLENECK_AUDIT.md](SELF_TEST_BOTTLENECK_AUDIT.md),
> [DIAGNOSTIC_FRAMEWORK_ROADMAP.md](DIAGNOSTIC_FRAMEWORK_ROADMAP.md), and
> [LOCAL_SELF_TEST_RUNBOOK.md](LOCAL_SELF_TEST_RUNBOOK.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `execution_permission = false` · `can_execute = false`

## 0. Why this exists

The backend has good diagnostics
(`signal_sensitivity_diagnostics`, `toxic_signal_quarantine`,
`continuity_mode`, `self_test_journal_quality`, `self_test_report`),
but the operator-facing schema does **not** yet capture the disciplined
decision data those diagnostics need.

A self-test must answer six months later:

- Was this profitable trade a good decision or a lucky one?
- Did I size the position because of risk reason X, or because of fear?
- Did I take it because the thesis confirmed, or because I was bored?
- Did the loss come from market noise, or from a process error?

Without **invalidation level, expected horizon, risk reason, entry
reason, exit plan, confidence-before, emotional state, mistake tags,
and a written lesson** captured at decision time and at reconciliation,
the operator cannot attribute outcomes to skill vs. luck vs. process
error. That is the bottleneck this schema upgrade fixes.

## 1. Current `manual_trades` columns (before this sprint)

Defined in [`scripts/persistence.py`](../scripts/persistence.py):

| Column | Type | Notes |
|---|---|---|
| trade_id | TEXT PK | uuid stamp |
| event_id | TEXT NOT NULL | links to signal |
| ticker | TEXT NOT NULL | |
| side | TEXT NOT NULL | BUY / SELL |
| quantity | REAL NOT NULL | |
| price | REAL NOT NULL | |
| executed_at | TEXT NOT NULL | utc iso8601 |
| thesis | TEXT default '' | freeform |
| notes | TEXT default '' | freeform |
| logged_by | TEXT default 'human' | |
| leverage | REAL default 1.0 | record-only |
| execution_mode | TEXT default 'HUMAN_ONLY' | invariant |
| ai_execution_count | INTEGER default 0 | invariant |
| advisory_status | TEXT default 'ADVISORY_ONLY' | invariant |
| human_review_required | INTEGER default 1 | invariant |
| broker_order_id | TEXT default 'NONE' | invariant |
| broker_api_called | INTEGER default 0 | invariant |

What's missing: every "would I make this decision again?" field.

## 2. Current `reconciliation_results` columns (before this sprint)

| Column | Type | Notes |
|---|---|---|
| reconciliation_id | TEXT PK | |
| trade_id | TEXT NOT NULL | |
| event_id | TEXT NOT NULL | |
| reconciled_at | TEXT NOT NULL | |
| actual_fill_price | REAL NOT NULL | |
| actual_quantity | REAL NOT NULL | |
| outcome_notes | TEXT default '' | freeform |
| pnl_estimate | REAL default 0.0 | operator-entered, not broker-verified |
| outcome_status | TEXT default 'UNKNOWN' | WIN/LOSS/BREAKEVEN/UNKNOWN |
| execution_mode | TEXT | invariant |
| ai_execution_count | INTEGER | invariant |
| advisory_status | TEXT | invariant |
| human_review_required | INTEGER | invariant |

What's missing: the "was the loss a process error or market noise?"
distinction, plus a place to record the lesson learned.

## 3. Missing self-test fields — added in this sprint

### 3.1 `manual_trades` additive columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| invalidation_level | TEXT | `''` | the price/level at which the thesis is wrong |
| expected_horizon | TEXT | `''` | hours / days / weeks the operator expects to hold |
| risk_reason | TEXT | `''` | why this size is acceptable to lose |
| entry_reason | TEXT | `''` | structural reason for entering (vs. emotional pull) |
| exit_plan | TEXT | `''` | how the trade will be closed (TP, stop, time-based) |
| confidence_before | REAL | NULL | 0..1 (or 0..100) — operator's self-rated confidence at entry |
| emotional_state | TEXT | `''` | one-word tag: calm / fomo / fear / revenge / bored / euphoric |
| mistake_tags | TEXT | `''` | comma-separated tags or JSON; intentionally permissive |
| lesson | TEXT | `''` | one-line takeaway operator wants future-self to read |

### 3.2 `reconciliation_results` additive columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| outcome_quality | TEXT | `''` | good_decision / bad_decision / lucky / unlucky / process_error |
| process_error | TEXT | `''` | optional code: e.g. `no_invalidation` / `oversized` / `late_entry` |
| process_error_notes | TEXT | `''` | freeform why-it-happened |
| mistake_tags | TEXT | `''` | tags duplicated here so reconciliation can stand alone |
| lesson | TEXT | `''` | reconciliation-time lesson (may differ from entry-time guess) |

## 4. Migration plan

Strategy: **additive migration only**.

- Each new column is added through the existing
  `_additive_migrations(conn)` helper in
  [`scripts/persistence.py`](../scripts/persistence.py).
- For each `(table, column, ddl)` tuple, the helper:
  1. reads `PRAGMA table_info(<table>)`,
  2. only runs `ALTER TABLE ... ADD COLUMN ...` if the column is absent,
  3. swallows `sqlite3.OperationalError` so repeated runs are safe.
- `CREATE TABLE ... IF NOT EXISTS` continues to drive fresh installs;
  the new columns are declared inline in the `_SCHEMA_SQL` block so
  brand-new DBs do not need the migration helper to fire.
- Reconciliation columns are only added when the
  `reconciliation_results` table is present; the migration tolerates a
  missing table without raising.

### 4.1 Non-destructive guarantees

- **No DROP** of any column or table.
- **No DELETE** of any existing row.
- **No rewrite** of `runtime/mvp_local.db`.
- **No reordering** — SQLite always appends new columns at the end.
- **No NOT NULL on new columns** — every new column either defaults to
  the empty string or allows NULL. Existing rows therefore remain
  legal after migration without any backfill.

### 4.2 Backwards compatibility

- All API parameters for the new fields are optional.
- Frontend payloads that omit the new fields still validate.
- `_to_dict()` in persistence normalises rows so that older readers
  that ignore unknown keys keep working.
- The new columns are not part of any UNIQUE or NOT NULL constraint.
- `confidence_before` accepts NULL (no value yet entered) or a numeric
  value in [0, 1] (preferred) or [0, 100]. The journal-quality scorer
  treats either scale as filled.

### 4.3 Idempotency

- A second call to `init_schema()` is a no-op for the new columns.
- Re-running the migration on a DB that already has the new columns
  silently does nothing.
- Test `tests/test_manual_trade_journal_schema.py` proves all of the
  above on a tmp_path DB without touching `runtime/mvp_local.db`.

## 5. Why this matters for 1–2 year self-testing

The Learning_Readiness formula in
[`scripts/self_test_journal_quality.py`](../scripts/self_test_journal_quality.py):

    Learning_Readiness =
          Thesis
        × Invalidation
        × Horizon
        × Risk_Rationale
        × Outcome_Log
        × Reflection

is **multiplicative** — a single missing factor zeroes the score. With
only `thesis`, `notes`, and `outcome_status` available, no entry can
score above ~0.0 on Invalidation × Horizon × Risk_Rationale ×
Reflection, so every manual trade was marked `learning_ready=False`.

After this sprint:

- the journal-quality helper can read the new fields directly from the
  DB and stop returning "missing_fields" for every row;
- `self_test_report.py` can compute real
  `average_learning_readiness`, `learning_ready_count`,
  `missing_field_distribution`, `emotional_state_distribution`,
  `confidence_before_average`, `mistake_tags_distribution`,
  `outcome_quality_distribution`, and `process_error_distribution`;
- the frontend Manual Trade Log form has somewhere to write the
  disciplined data — the schema is no longer the limiter.

This converts backend diagnostics into operator behaviour change.

## 6. Out of scope for this sprint

- Hosted deployment / Postgres / broker integration / private-beta auth
  / paid-API live calls.
- Frontend test tooling (Vitest/RTL/Playwright) install — requires
  operator approval.
- Removal of any existing column.
- Mistake-taxonomy migration to a normalized `mistake_tags` table
  (current freeform string is intentionally permissive; a future sprint
  can normalise once we know what tags the operator actually uses).
