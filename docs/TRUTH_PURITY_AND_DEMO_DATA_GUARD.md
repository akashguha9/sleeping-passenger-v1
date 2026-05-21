# Truth Purity & Demo-Data Guard

## Purpose

**Fake data in canonical memory is system poisoning.** A demo SPY row or a
"Persistence above 0.8" placeholder thesis sitting in the runtime SQLite DB
silently corrupts every downstream learning metric. The truth-purity audit is a
read-only release gate that scans canonical truth for pollution and fails the
gate when any is found.

## Fields

| Field | Meaning |
|---|---|
| `truth_purity_score` | Clean fraction of scanned rows (1.0 = pristine). |
| `fake_rows_detected` | Count of polluted rows across scanned tables. |
| `affected_tables` | Tables containing pollution. |
| `pollution_examples` | Up to 20 examples with table, id, ticker, reason. |
| `release_gate_passed` | `True` only when zero fake rows and DB present. |
| `recommended_cleanup_command` | The explicit, role-gated cleanup to run. |

## Detection signatures (shared, never drift)

- FABRIC / FABRIC_SPY / FABRIC_QQQ demo event_ids and tickers;
- the `Persistence above 0.8` and `Thesis A` fake thesis fragments;
- `SEED_` / `DEMO_` / `TEST_` / `FIXTURE_` event-id prefixes (from
  `manual_trade_origin.FAKE_EVENT_ID_PREFIXES`);
- fake operator trades via `manual_trade_origin.is_fake_manual_trade_row`;
- loss-review Moltbook entries with a **blank** `manual_trade_log_id`
  (an orphaned, untraceable lesson).

## Scripts

- `scripts/runtime_truth_purity_audit.py` — read-only scan + release gate.
- `scripts/moltbook_cleanup_fake_seed.py --apply` — narrow Moltbook seed removal
  (ADMIN-gated).
- `scripts/quarantine_fake_manual_trades.py` — quarantines fake trades.

Detection and cleanup deliberately import the **same** vocabulary so a row that
the audit flags is exactly a row the cleanup targets.

## Tests

`tests/test_runtime_truth_purity_audit.py`:
- clean DB passes; FABRIC/demo rows detected; fake rows cannot silently pass the
  release gate; orphaned loss-review entry flagged; the audit never deletes data;
  missing DB fails the gate closed; advisory-only stamps present.

## Failure modes

- **DB missing** → gate fails **closed** (cannot verify purity ≠ verified clean).
- **New pollution shape** → add the signature to `manual_trade_origin` so both
  audit and cleanup see it; never widen one without the other.

## Advisory-only safety note

The audit is strictly read-only — it **detects but never deletes**. Cleanup is a
separate, explicit, role-gated invocation. No broker calls; advisory stamps
present on every output.

## How to verify locally

```powershell
python scripts\runtime_truth_purity_audit.py
python -m pytest tests\test_runtime_truth_purity_audit.py -q
```
