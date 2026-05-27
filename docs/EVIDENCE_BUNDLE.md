# Evidence Bundle

**Sprint:** proof_loop_hardening_sprint, Phase 4.

This is the *single* place that ties a claimed readiness score to actual
artifacts on disk.  Nothing in this repo should ever quote a readiness
number without also quoting `N_real`, `calibration_status`, and
`evidence_status` from the manifest below.

> **Self-audit, not externally validated.**  Every score in the repo is
> the model's own audit.  No external validator has reviewed this
> codebase.  Until an external red-team / calibration audit completes,
> all readiness numbers must be read as self-reported.

## How to build it

```powershell
# Compute the manifest in memory (no writes)
python scripts/evidence_manifest.py

# Persist to runtime/release/evidence_manifest.json
python scripts/evidence_manifest.py --write
```

`scripts/calibration_corpus_status.py` and
`scripts/calibration_report.py` feed into it; the manifest itself is
read-only and never fabricates a metric.

## Evidence-status truth table

Let:

- `A` = has calibration report on disk
- `B` = has paper-trade ledger (corpus envelope) on disk
- `C` = `N_real` (real, calibratable rows)
- `D` = has demo video / demo notes on disk
- `E` = has screenshots / screenshot checklist on disk
- `F` = has Playwright e2e report on disk
- `G` = has pytest / safety report on disk
- `H` = has hosted uptime report on disk

| `evidence_status` | Required |
|---|---|
| `EMPTY` | none of `A,B,D,E,F,G` |
| `PARTIAL` | any of `A,B,D,E,F,G` |
| `SUFFICIENT_FOR_LOCAL_DEMO` | `A ∧ E ∧ G` |
| `SUFFICIENT_FOR_INVESTOR_DEMO` | `A ∧ D ∧ E ∧ F ∧ G ∧ C ≥ 20` |
| `SUFFICIENT_FOR_PRIVATE_BETA` | the above **and** `H` **and** `C ≥ 20` |

Hard rule: `SUFFICIENT_FOR_INVESTOR_DEMO` is never reported when
`C < 20`.  This is enforced in `scripts/evidence_manifest.py` and
covered by `tests/test_evidence_manifest.py`.

## Freshness penalty

Per Phase 7, *path existence alone is never full evidence.*  Each
artifact carries a `freshness` score:

```
freshness =
  0,                                          if missing
  1,                                          if age_days <= max_age_days
  max(0, 1 - (age_days - max_age_days) / max_age_days)   otherwise
```

`max_age_days` defaults are in `scripts/evidence_manifest.py`
(`DEFAULT_MAX_AGE_DAYS`).

## What this manifest does NOT do

- It does not invent metrics.
- It does not change `N_real`.
- It does not promote any score above its calibration ceiling.
- It does not call brokers, place orders, or contact any execution
  endpoint.  None exist in this codebase.

## Cross-references

- `docs/CALIBRATION_CORPUS.md` — how the corpus is built.
- `data/calibration_corpus/SCHEMA.md` — calibratability rule.
- `docs/PAPER_TRADE_LEDGER.md` — the operator-side ledger workflow.
- `docs/FINAL_SCORECARD.md` — the rolled-up score (must always cite
  `N_real`).
