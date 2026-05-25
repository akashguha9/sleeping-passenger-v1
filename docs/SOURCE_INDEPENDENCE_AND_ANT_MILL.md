# Source Independence & Ant-Mill Risk

## Purpose

Five models repeating one catalyst is **one signal wearing five masks**, not
five independent confirmations. Source independence matters more than model
count. When agreement is high but independence is low, the system is in an
*ant-mill* — a confirmation death-spiral that must trigger a contradiction
search, not a promotion.

## Fields / formulas

Per-model mention rows may carry: `model_name`, `ticker`, `catalyst_text`,
`catalyst_fingerprint`, `source_urls_or_refs`, `source_family`,
`timestamp_utc`, `model_agreement`.

```
source_independence_score = 1 - duplicate_catalysts / max(total_catalysts, 1)
model_agreement_score      = mean(explicit) OR max_catalyst_frequency / total
ant_mill_risk              = model_agreement_score * (1 - source_independence_score)
```

Output: `unique_catalyst_count`, `duplicate_catalyst_count`,
`source_independence_score`, `model_agreement_score`, `ant_mill_risk`,
`single_source_consensus`, `ai_echo_risk`, `high_agreement_low_independence`,
`promotion_downgrade_recommendation` (`downgrade` / `watch` / `no_change`),
`forced_contradiction_required`, `invalidation_question`, `human_review_required`.

## Scripts

- `scripts/source_independence_audit.py` — pure `analyze_catalysts(rows)` plus a
  DB-backed `build_report()` that expands `duplicate_fingerprints` into per-mention
  catalyst rows and groups by ticker. `--input model_reports.json` analyses a
  five-model synthesis batch.
- Reuses `scripts/complex_systems_diagnostics.detect_ant_mill` for the richer
  classification (so the two never drift) and `scripts/echo_risk_engine.py` for the
  weighted echo-risk view.

## Tests

`tests/test_source_independence_audit.py`:
- duplicate catalysts lower independence; unique catalysts raise it;
- high agreement + low independence raises ant-mill risk;
- ant-mill causes an advisory **downgrade**, never an execution block;
- single-source consensus is flagged;
- empty input → insufficient-data; output is advisory-only.

Plus engine coverage in `tests/test_complex_systems_diagnostics.py`
(`test_source_independence_echo_vs_independent`, `test_ant_mill_*`).

## Failure modes

- **No catalyst text/fingerprint** → that mention is dropped from the corpus;
  an empty corpus reports insufficient data, not false confidence.
- **Implicit agreement proxy** — when no explicit `model_agreement` is supplied,
  agreement is derived from concentration on the most-repeated catalyst. This is
  a conservative proxy; supply explicit values for higher fidelity.

## Advisory-only safety note

High ant-mill risk produces an advisory **downgrade** and a human-review flag.
It blocks no execution path because none exists. `can_execute` and
`execution_permission` are always `False`; `broker_api_called` is `False`.

## How to verify locally

```powershell
python scripts\source_independence_audit.py
python -m pytest tests\test_source_independence_audit.py -q
```
