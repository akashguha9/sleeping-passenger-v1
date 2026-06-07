# MVP Capability Scoreboard

> **Status:** honest capability ledger. A score may rise ONLY when backed by
> shipped code + at least one direct test, and a module counts as
> production-adjacent only when wired into runtime artifacts and user-visible only
> when integrated into the final synthesis / auditor.
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `execution_permission = false`

## Scoring rules

- No score increase without **code + tests**.
- Docs-only improves doctrine, NOT shipped capability.
- A module must have ≥1 direct test to count as shipped.
- A module must be wired into runtime artifacts to count as production-adjacent.
- A module must be integrated into final synthesis/auditor to count as user-visible.

## Scoreboard (2026-06-07 interpretation-defense upgrade)

| # | Segment | Prev | New | Δ | Evidence in code | Tests | Shipped? | Remaining gap |
|---|---|---:|---:|---:|---|---|---|---|
| 1 | Provenance / contamination defense | 9 | 9 | 0 | `fresh_discovery_contract.py` | `test_fresh_discovery_contract.py` | shipped | — |
| 2 | Fresh discovery isolation | 9 | 9 | 0 | `fresh_discovery_contract.py`, `isolated_model_lanes.build_clean_fresh_discovery_payload` | `test_isolated_model_lanes.py` | shipped | — |
| 3 | Five-model isolation | 8 | 8 | 0 | `isolated_model_lanes.py` | `test_isolated_model_lanes.py` | shipped | real LLM clients still injected, not built-in |
| 4 | Mechanical aggregation | 8 | 8 | 0 | `model_vote_aggregator.py` | `test_model_vote_aggregator.py` | shipped | — |
| 5 | Final auditor discipline | 8 | 8 | 0 | `daily_synthesis_pipeline.build_final_synthesis` + invention guard | `test_isolated_model_lanes.py`, integration | shipped | — |
| 6 | Interpretation quality scoring | 4 | 7 | +3 | `interpretation_quality_score.py`; wired into payload/lanes/aggregator/synthesis/artifacts | `test_interpretation_quality_score.py` + integration | **shipped** | reliability uses heuristics, not a per-source reliability ledger yet |
| 7 | Metric regime transfer risk | 5 | 7 | +2 | `metric_regime_transfer_risk.py`; wired through engine | `test_metric_regime_transfer_risk.py` + integration | **shipped** | comparison mode needs real target-regime feed |
| 8 | Adverse regime stress testing | 5 | 7 | +2 | `adverse_regime_stress_test.py`; wired through engine | `test_adverse_regime_stress_test.py` + integration | **shipped** | needs a live fundamentals feed to leave INSUFFICIENT_DATA in production |
| 9 | Narrative-vs-substance separation | 7 | 7 | 0 | `narrative_structure_divergence.py` (pre-existing) | existing | shipped | not yet wired into interpretation defense |
| 10 | Distribution / amplification illusion | 7 | 7 | 0 | `propagation_spread_estimator.py`, `echo_risk_engine.py` (pre-existing) | existing | shipped | P2: dedicated detector wired into IDS |
| 11 | Incentive awareness / who-benefits | 2 | 2 | 0 | none | — | not shipped | P2: `claim_expected_value_audit` |
| 12 | Audience-misinterpretation modeling | 2 | 2 | 0 | none | — | not shipped | P2: `audience_misinterpretation_risk` |
| 13 | Existing holding review (Channel B) | 6 | 6 | 0 | `daily_synthesis_pipeline.build_existing_holding_review` | integration | shipped | per-holding stress lane is future work |
| 14 | Moltbook / outcome learning | 6 | 7 | +1 | `build_moltbook_learning_review` now distils IDS lessons | integration | **shipped** | lessons not yet persisted to the Moltbook DB |
| 15 | Execution safety / advisory-only governance | 10 | 10 | 0 | `advisory_contract.py`, locks on every new surface | every new test asserts advisory_only / LOCKED | shipped (canonical) | preserve — never weaken |

### Unified new capability

| Capability | Prev | New | Δ | Evidence | Tests |
|---|---:|---:|---:|---|---|
| Interpretation Defense Engine (IDS = 0.45·IQS + 0.25·(100−MTR) + 0.30·(100−SFR)) | 0 | 7 | +7 | `interpretation_defense_engine.py` | `test_interpretation_defense_engine.py` + integration |

## Why these increases are real (not doctrine)

Segments 6–8 and the unified engine moved because there is now **shipped code**
(`scripts/interpretation_quality_score.py`, `metric_regime_transfer_risk.py`,
`adverse_regime_stress_test.py`, `interpretation_defense_engine.py`), **direct
tests** (5 new test files, 41 tests), **runtime artifacts**
(`runtime/<date>/interpretation_defense/*.json`,
`capability_upgrade_report.json`), and **pipeline integration** (clean payload →
lanes → aggregator → final auditor → Moltbook lessons). Each module can only
*demote* a candidate; none can promote, invent, or unlock execution.

Capped at 7 (not 10) honestly: the modules run on heuristics and, in production,
on partial data (fundamentals usually absent → `INSUFFICIENT_DATA`; regime
comparison needs a real target-regime feed). They become 8–9 only when wired to
live reliability/fundamentals/regime feeds.

## P2 expansion update (2026-06-07)

Shipped four P2 modules + an expanded IDS, all wired through payload → lanes →
aggregator → final auditor → Moltbook lessons → runtime artifacts, with tests.
Test hygiene: the `scripts/external/tribev2` empty-dir leftover was removed, so
`test_archived_code_isolation` is green (engineering reliability, NOT a trading
capability gain).

| # | Segment | Prev | New | Δ | Evidence in code | Tests | Shipped? | Why capped |
|---|---|---:|---:|---:|---|---|---|---|
| 6 | Interpretation quality scoring | 7 | 7 | 0 | `interpretation_quality_score.py` | existing | shipped | IQS feeds P2; it does not consume P2, so no honest increase |
| 10 | Distribution / amplification illusion | 7 | **8** | +1 | `distribution_amplification_detector.py` wired into expanded IDS | `test_distribution_amplification_detector.py` + P2 integration | **shipped+wired** | needs real attention feed to exceed 8 |
| 9 | Narrative-vs-substance separation | 7 | **8** | +1 | `narrative_substance_gap.py` unified into expanded IDS | `test_narrative_substance_gap.py` + integration | **shipped+wired** | needs real fundamentals feed |
| 11 | Incentive awareness / who-benefits | 2 | **6** | +4 | `incentive_who_benefits_analyzer.py` | `test_incentive_who_benefits_analyzer.py` + integration | **shipped+wired** | ownership/insider/liquidity data absent → heuristic only; not 7 |
| 12 | Audience-misinterpretation modeling | 2 | **6** | +4 | `audience_misinterpretation_risk.py` | `test_audience_misinterpretation_risk.py` + integration | **shipped+wired** | term-list + cross-signal heuristic; no calibration → not 7 |
| — | Unified IDS (expanded) | 7 | **8** | +1 | `interpretation_defense_engine.evaluate_candidate_expanded` (P2 affects expanded grade + aggregator override) | `test_expanded_interpretation_defense_engine.py` + integration | **shipped+wired** | heuristic + partial data → not 9 |
| 5 | Final auditor discipline | 8 | 8 | 0 | P2 board added but invention guard unchanged | integration | shipped | no new guard ⇒ no increase |
| 15 | Execution safety / advisory-only | 10 | 10 | 0 | every P2 surface stamped advisory_only, LOCKED | every P2 test | canonical | preserve |
| — | Full-suite reliability (test hygiene) | red | **green** | — | removed untracked empty-dir leftover | `test_archived_code_isolation.py` | n/a | hygiene only, not capability |

### Why P2 increases are real (not doctrine)

Four new modules (`distribution_amplification_detector.py`,
`narrative_substance_gap.py`, `incentive_who_benefits_analyzer.py`,
`audience_misinterpretation_risk.py`), an expanded IDS in
`interpretation_defense_engine.py`, **6 new test files**, runtime artifacts
under `runtime/<date>/interpretation_defense/p2/`, and the aggregator/auditor now
consume the **expanded** grade (not just P1). Each P2 module can only **demote**;
`test_expanded_interpretation_defense_engine.py::test_G` proves expanded IDS ≤ P1
IDS. Caps at 6–8 (not 9–10) are deliberate: no live attention / ownership /
fundamentals feeds and no historical calibration yet.

### Next highest-impact upgrade (capped components → 9 only with these)

1. Real live price/news/filing/**fundamentals** provider (lifts ARST, NSG, DA).
2. Current-holdings price reconciliation (Channel B holding stress lane).
3. Historical calibration / backtest for IDS grades (lifts every score's ceiling).
4. Sector-specific stress priors + real ownership/short-interest feed (lifts
   incentive/who-benefits past 6).
