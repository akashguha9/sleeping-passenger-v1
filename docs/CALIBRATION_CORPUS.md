# Calibration Corpus

**Sprint:** Calibration Corpus + Hosted Canary, Phase 1.

The calibration gate has historically reported `INSUFFICIENT_EVIDENCE`
because the repository carried no labelled outcome corpus.  This sprint
adds the curation pipeline that builds one — honestly.

> **No fake calibration.** If real evidence is insufficient, the gate
> reports `INSUFFICIENT_EVIDENCE` and `predictive_claim_allowed=false`.
> The pipeline NEVER fabricates rows, never marks demo/fixture rows as
> real evidence, and never opens a broker / order endpoint.

## Build a corpus

```bash
# 1. Dry-run from local SQLite (no network, no writes)
python scripts/curate_calibration_corpus.py --dry-run \
    --from-sqlite runtime/mvp_local.db

# 2. Same, but persist the envelope
python scripts/curate_calibration_corpus.py --write \
    --from-sqlite runtime/mvp_local.db \
    --output runtime/release/calibration_corpus.json

# 3. Opt-in: include public Polymarket closed markets
python scripts/curate_calibration_corpus.py --write \
    --from-sqlite runtime/mvp_local.db \
    --include-polymarket-closed --max-records 250
```

External requests are GET-only, 8-second timeout, no credentials,
redacted logs.  The script makes ZERO network calls without
`--include-polymarket-closed`.

## What counts as evidence

| Source | `source` value | Counts toward `N_real`? |
|---|---|---|
| Quarantined demo rows | — | No (excluded by the SQLite query) |
| Real manual trade + reconciliation (WIN/LOSS) | `manual_trade` | Yes |
| Polymarket public closed markets | `polymarket_closed` | Yes |
| Test fixture | `fixture_test_only` | **No** |
| Any record with `provenance.mock_fallback=true` | any | **No** |

Records are deduplicated by the SHA-256 of
`source | source_record_id | asset_or_market | signal_timestamp_utc |
outcome_timestamp_utc | outcome_definition`.

## Running the gate against the corpus

```bash
python scripts/calibration_report.py \
    --corpus runtime/release/calibration_corpus.json
```

The gate emits `runtime/release/calibration_report.json` with:

* `n_total`, `n_real`, `n_fixture`, `n_mock`
* `brier_score`, `ece`, `mce`, `base_rate`, `sharpness`
* `evidence_status` (`INSUFFICIENT_EVIDENCE` | `MEASURABLE`)
* `calibration_status` (`INSUFFICIENT_EVIDENCE` | `MEASURED_PASS` | `MEASURED_FAIL`)
* `predictive_claim_allowed` — only true when ALL of:
  * `n_real ≥ 200`
  * `brier_score ≤ 0.25`
  * `ece ≤ 0.10`
  * `mce ≤ 0.25`
* Advisory safety stamps (`advisory_status`, `execution_gate`,
  `broker_api_called`, `ai_execution_count`).

## Today's honest verdict

The repository's local SQLite currently contains 3 real (non-quarantined)
manual trades with WIN/LOSS reconciliations.  None of them carry a
historical `model_probability` — the scoring stack did not snapshot
predictions per trade.  So `N_real` for calibration math is **0** unless
you opt in to Polymarket closed markets.  The gate correctly reports
`INSUFFICIENT_EVIDENCE` and refuses any predictive claim.

Calibration becomes measurable once:

1. The scoring stack snapshots `model_probability` per signal at the
   time of advisory (a separate workstream), OR
2. The operator runs `--include-polymarket-closed` to seed the corpus
   with public-API outcomes (still honestly stamped
   `source=polymarket_closed`, not fabricated).
