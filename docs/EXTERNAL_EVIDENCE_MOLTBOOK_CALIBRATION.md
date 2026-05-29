# External Evidence — Persistence + Moltbook Calibration

`EXTERNAL_EVIDENCE_MOLTBOOK_CALIBRATION`

This document describes how advisory external evidence is **persisted at signal
time** and **calibrated after the close** so per-source reliability weights
`w_b` can be learned honestly — without ever affecting real-money sizing or
authorizing execution.

It is the outcome-time companion to
[`EXTERNAL_ADVISORY_EVIDENCE_PIPELINE.md`](EXTERNAL_ADVISORY_EVIDENCE_PIPELINE.md),
which covers the signal-time enrichment stage.

---

## 1. Why external evidence must be persisted at signal time

The advisory enrichment stage produces an `external_evidence` bundle during
daily synthesis. Before this sprint, that bundle was rendered into the prompt
and then discarded. Nothing recorded **what evidence existed at the moment a
signal was generated**, so it was impossible to later ask "did source X's
forecast-at-time-t actually help once the trade closed?".

Calibration is only meaningful against an immutable record of the forecast as
it stood *before* the outcome was known. Persisting a snapshot at signal time
is therefore a precondition for any honest learning loop.

## 2. Why learning happens only after closed outcomes

External evidence is judged **only** once the realized outcome is known. There
is no pre-outcome self-confirmation: a snapshot can never mark *itself*
helpful. The recorder enforces this with two hard gates:

- **Open trades never learn** → `OUTCOME_NOT_FINAL`.
- **Missing entry/exit prices never learn** → `INSUFFICIENT_OUTCOME_DATA`
  (P/L is never invented).

Only a closed trade with a real entry+exit price produces a learning record.

## 3. SQLite is canonical; JSONL is not

All three tables live in the canonical DB `runtime/mvp_local.db` (reusing
`scripts/persistence.py`'s `DB_PATH` / `_get_conn` conventions — no parallel
database). Every persistence summary reports `canonical_store="SQLITE"` and
`jsonl_is_canonical=false`. JSONL is never made canonical for this data.

## 4. Tables

### 4.1 `external_evidence_snapshots` — immutable evidence-at-time-t

One row per accepted/rejected/error evidence item. Key columns:
`snapshot_id` (UNIQUE, deterministic), `signal_id`, `daily_run_id`,
`candidate_id`, `ticker`, `source_name`, `evidence_type`, `route_decision`,
`execution_permission`, the scoring fields (`score_delta`, `alignment_score`,
`reliability_weight`, `router_multiplier`, `evidence_quality`,
`confidence_raw`, `confidence_calibrated`, `downside_risk`, `noise_penalty`,
`alignment_bonus`, `downside_penalty`), `payload_json` (full normalized
payload), `payload_summary` (compact, frontend-safe), and the outcome-link
columns (`outcome_known`, `outcome_trade_id`, `outcome_realized_return_pct`, …).

`snapshot_id` is deterministic:

```
snapshot_id = SHA256(
    daily_run_id | signal_id | ticker | source_name | evidence_type
    | generated_at_utc_bucket | route_decision
)
generated_at_utc_bucket = YYYY-MM-DDTHH:MMZ   (minute bucket — stable on re-run)
```

`signal_id` falls back to `candidate_id`; if both are missing the remaining
(ticker, daily_run_id, source_name) components keep the hash unique. Re-running
the same synthesis is an idempotent no-op (`INSERT OR IGNORE` on the UNIQUE id).

### 4.2 `external_evidence_outcomes` — one learning record per linked close

Key columns: `learning_id` (UNIQUE, deterministic), `snapshot_id`, `trade_id`,
`ticker`, `source_name`, prices + `realized_return_pct`, `outcome_y_0_or_1`,
the evidence fields copied from the snapshot, the derived
`forecast_direction` / `actual_direction` / `direction_correct` /
`forecast_error_pct`, the four learning flags
(`evidence_helped`, `evidence_harmed`, `false_confidence`,
`risk_reducer_helped`), the `calibration_bucket`, and the pre/post weight +
sample-count snapshot.

```
learning_id = SHA256(snapshot_id | trade_id | exit_timestamp_utc | outcome_event_type)
```

### 4.3 `external_evidence_calibration_buckets` — per-source running weights

Keyed by `bucket_id = source_name|evidence_type|route_decision|confidence_band`.
Stores the running counts (`sample_count`, `help_count`, `harm_count`,
`false_confidence_count`), the derived rates, `raw_reliability`,
`sample_multiplier`, `advisory_weight`, and the hard flags
`real_money_weight_allowed=0` / `real_money_sizing_impact='PROHIBITED'`.

## 5. Mathematical formulas

### Realized outcome

```
R_actual            = (P_exit - P_entry) / P_entry
realized_return_pct = 100 * R_actual
```

### Directions

```
actual_direction =
   +1 if realized_return_pct > +THETA_ACTUAL   (THETA_ACTUAL = 0.25%)
   -1 if realized_return_pct < -THETA_ACTUAL
    0 otherwise

forecast_direction =
   from KRONOS_FORECAST_RETURN_PCT, with THETA_FORECAST = 0.50%
       +1 if > +0.50, -1 if < -0.50, else 0
   else from alignment_score, with THETA_ALIGNMENT = 0.10
       +1 if > +0.10, -1 if < -0.10, else 0
   else 0

direction_correct =
    1 if forecast_direction != 0 and actual_direction != 0
         and forecast_direction == actual_direction
    0 otherwise
```

### Forecast error

```
forecast_error_pct = |forecast_return_pct - realized_return_pct|   (or NULL if no forecast)
```

### Learning flags

```
evidence_helped = 1 if any of:
  A. route in {WATCH, ACCEPTED, ADVISORY_CONTEXT_ONLY}
     and score_delta > 0 and direction_correct = 1 and realized_return_pct > 0
  B. score_delta < 0 and realized_return_pct < 0           (risk reducer)
  C. route = REJECT and realized_return_pct < 0            (veto support)

evidence_harmed = 1 if any of:
  A. score_delta > 0 and realized_return_pct < 0
  B. score_delta < 0 and realized_return_pct > MISSED_OPPORTUNITY_THRESHOLD (+2.0%)

false_confidence = 1 if:
  score_delta > 0 and confidence_calibrated >= 0.50 and realized_return_pct < 0

risk_reducer_helped = 1 if:
  score_delta < 0 and realized_return_pct < 0
```

### Confidence band

```
COLD if confidence_calibrated is null
LOW  if < 0.35
MID  if 0.35 <= c < 0.65
HIGH if >= 0.65
```

### Per-bucket weight update

```
n_b = sample count   h_b = help count   x_b = harm count   f_b = false-confidence count

H_b = h_b / max(n_b, 1)
X_b = x_b / max(n_b, 1)
F_b = f_b / max(n_b, 1)

Rel_b = clip(0.50 + 0.75*(H_b - 0.50) - 1.00*X_b - 0.75*F_b, 0.10, 1.25)

sample_multiplier_b =
   0.50 if n_b < 30
   0.75 if 30 <= n_b < 50
   1.00 if n_b >= 50

w_b = clip(Rel_b * sample_multiplier_b, 0.10, 1.25)
```

The weight is deliberately conservative: a small sample is haircut hard, harm
and false-confidence are penalized more than help is rewarded, and the floor
keeps a bad source from being zeroed out (so it is never silently dropped).

## 6. Safety limits

- **No execution.** Nothing here places, modifies, or cancels a broker order;
  no BUY/SELL/ENTER/EXIT is ever generated.
- **No real-money sizing.** `real_money_weight_allowed` is **always 0** and
  `real_money_sizing_impact` is **always `PROHIBITED`**, regardless of sample
  size. Even at `n_b >= 50` the operator must explicitly approve any future
  real-money use — that approval is **not** part of this sprint.
- **No DIABLO / CHAOS_VETO / NO_NEW_RISK override.** Calibration only reads
  closed outcomes; it cannot touch the safety classes.
- **No broker calls.** No broker library is imported anywhere in these modules.
- **Fail-safe.** Any persistence or learning failure degrades to `ERROR_SAFE`
  with zero decision impact and never blocks the daily run.

Every row and every return value carries `advisory_only`,
`human_execution_required`, `execution_gate='LOCKED'`, `broker_api_called=0`,
`ai_execution_count=0`.

## 7. Backfill usage

`scripts/external_evidence_calibration_backfill.py` links already-closed
reconciled trades to existing snapshots. **Dry-run by default**; `--apply`
required to write.

```
python scripts/external_evidence_calibration_backfill.py                # dry-run
python scripts/external_evidence_calibration_backfill.py --apply        # write (idempotent)
python scripts/external_evidence_calibration_backfill.py --limit 50
python scripts/external_evidence_calibration_backfill.py --trade-id T123
python scripts/external_evidence_calibration_backfill.py --source-name kronos
python scripts/external_evidence_calibration_backfill.py --since 2026-01-01
```

It reads closed rows in `reconciliation_results` joined to `manual_trades`
(entry price + ticker), never touches trade rows or open trades, never changes
execution permissions, and only writes outcome/calibration records. A second
`--apply` run creates zero duplicates. `--source-name` selects trades that have
at least one snapshot from that source.

## 8. Current limitations

- Calibration weights feed **future paper analysis only** — they are not yet
  read back into the signal-time score-delta math.
- Real-money sizing remains prohibited; there is no operator approval flow yet.
- No frontend card displays snapshots/outcomes/weights.
- Live adapters (including Kronos) remain disabled by default, so a default
  daily run persists zero snapshots until an operator opts in.
- Per-source calibration thresholds (`THETA_*`, sample tiers) are global
  constants, not yet per-source tuned.
- Paper-trade sample sizes are far below the `n_b >= 50` tier in practice, so
  most buckets sit at the `0.50` small-sample haircut.

## 9. Next sprint after this one

1. **Read calibrated `w_b` back into the score-delta** as an advisory-only
   prior (still paper-only, still clamped).
2. **Frontend evidence card**: surface snapshots, outcomes, and per-source
   reliability — read-only, advisory-only copy.
3. **Operator approval flow** for any real-money use of a mature bucket
   (`n_b >= 50`), gated behind explicit, audited consent — still not part of
   automatic sizing.
4. **Per-source threshold tuning** once enough closed outcomes exist.
