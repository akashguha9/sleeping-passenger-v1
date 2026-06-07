# Interpretation Defense — Framework Component Map

> **Status:** mapping document. NOT implementation.
> Companion to [reflections/2026-06-07_interpretation_defense_reflection.md](reflections/2026-06-07_interpretation_defense_reflection.md)
> and [FRAMEWORK_COMPONENT_MAP.md](FRAMEWORK_COMPONENT_MAP.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `execution_permission = false` · `can_execute = false`

## 0. Purpose

The 2026-06-07 reflection argues the MVP's edge is **interpretation defense**:
detecting context failure, narrative-vs-substance gaps, distribution illusions,
audience misinterpretation, and stress fragility before any signal becomes
advisory output. This document is the firebreak between that thesis and code —
it maps each proposed component to a professional engineering name, the existing
repo overlap, an honest implementation status, and a priority. Nothing here
grants execution permission; the advisory lock is canonical and outranks it.

Scope note: this is an **equity advisory MVP**. Marketing/consumer/crypto-only
components (category salience, algorithmic exposure, embodied utility, meme-coin
honeypots) are retained as doctrine but are low-priority for the equity surface
and stay document-only unless a concrete equity use-case appears.

## 1. Component-to-Repo Mapping

| # | Reflection concept | Professional name | Existing overlap | Status | Priority |
|---|---|---|---|---|---|
| 1 | Interpretation Quality Score | `interpretation_quality_score` | `scripts/interpretation_quality_score.py` (SHIPPED 2026-06-07) | **SHIPPED** — IQS over provenance/context/reliability/ambiguity/contradiction; wired into payload→lanes→aggregator→auditor→artifacts; tests in `test_interpretation_quality_score.py` | P1 (done) |
| 2 | Narrative-Substance Gap Detector | `narrative_substance_gap` | `scripts/narrative_substance_gap.py` (SHIPPED 2026-06-07, P2); lineage `narrative_structure_divergence.py` | **SHIPPED** — payload-level NSG wired into expanded IDS; `test_narrative_substance_gap.py` | P0 (done) |
| 3 | Economic Honeypot / Exit-Liquidity Detector | `economic_honeypot_detector` | none (crypto out of equity scope); closest `regime_translation_tester.py` (liquidity stressor) | **MISSING** | P3 (doc-only) |
| 4 | Category Salience Estimator | `audience_category_salience` | none (marketing-domain) | **MISSING** | P3 (doc-only) |
| 5 | Algorithmic Exposure Mapper | `exposure_bias_mapper` | `attention_proxy_engine.py` (spread proxy only) | **MISSING** | P3 (doc-only) |
| 6 | Fear-ROI Conversion Layer / Who-Benefits | `incentive_who_benefits_analyzer` | `scripts/incentive_who_benefits_analyzer.py` (SHIPPED 2026-06-07, P2); lineage `asymmetry_survival_scorer.py` | **SHIPPED (heuristic)** — "who profits if I believe this" firewall + exit-liquidity risk; `test_incentive_who_benefits_analyzer.py` | P2 (done; capped 6 — no ownership feed) |
| 7 | Luck Surface Area Tracker | `opportunity_exposure_tracker` | none; closest `lpc_luck_cost_engine.py` (past luck attribution) | **MISSING** | P2/P3 |
| 8 | Metric Transfer Risk Module | `metric_regime_transfer_risk` | `scripts/metric_regime_transfer_risk.py` (SHIPPED 2026-06-07); lineage `regime_translation_tester.py` | **SHIPPED** — payload-level regime transfer risk (comparison + self-anchor modes); tests in `test_metric_regime_transfer_risk.py` | P1 (done) |
| 9 | Stress Test Layer | `adverse_regime_stress_test` | `scripts/adverse_regime_stress_test.py` (SHIPPED 2026-06-07); lineage `regime_translation_tester.py`, `tail_loss_governor.py` | **SHIPPED** — data-aware survival/stress with honest INSUFFICIENT_DATA; tests in `test_adverse_regime_stress_test.py` | P1 (done) |
| 10 | Embodied Utility Layer | `consumer_sensory_utility` | none; closest `experience_mode_report.py` | **MISSING** | P3 (doc-only) |
| 11 | Distribution Amplification Detector | `distribution_amplification_detector` | `scripts/distribution_amplification_detector.py` (SHIPPED 2026-06-07, P2); lineage `propagation_spread_estimator.py`, `echo_risk_engine.py` | **SHIPPED** — attention-vs-substance ratio + HYPE_LED; wired into expanded IDS; `test_distribution_amplification_detector.py` | P0 (done) |
| 12 | Ecosystem Revenue Map | `ecosystem_revenue_decomposition` | none; closest `signal_field_geometry.py` | **MISSING** | P2 |
| 13 | Audience Misinterpretation Risk Score | `audience_misinterpretation_risk` | `scripts/audience_misinterpretation_risk.py` (SHIPPED 2026-06-07, P2) | **SHIPPED (heuristic)** — per-audience misread risk + operator-misread flag; wired into expanded IDS; `test_audience_misinterpretation_risk.py` | P2 (done; capped 6 — no calibration) |

## 2. Already-shipped interpretation-defense surface (context)

The reflection's thesis is substantially *already* the MVP's spine. Beyond the
13: `silence_filter`, `signal_buoyancy_engine`, `survivorship_bias_corrector`,
`late_adoption_lockout`, `crowding_detector`, `model_disagreement`,
`ai_report_ingestion`, and — most directly — `fresh_discovery_contract`,
`isolated_model_lanes`, and `model_vote_aggregator` (the 2026-06-07 isolation
refactor) are interpretation-defense / provenance-defense layers.

## 3. Priority ladder (equity MVP)

- **P0 — preserve/extend (already canonical):** `narrative_substance_gap` (#2),
  `distribution_amplification_detector` (#11), and the provenance lock
  (fresh-discovery contract + isolated lanes).
- **P1 — high-value, deterministic, no execution risk:**
  `interpretation_quality_score` (#1), `metric_regime_transfer_risk` (#8),
  `adverse_regime_stress_test` (#9).
- **P2 — useful, easy to overengineer:** `claim_expected_value_audit` (#6),
  `audience_misinterpretation_risk` (#13), `ecosystem_revenue_decomposition`
  (#12), `opportunity_exposure_tracker` (#7).
- **P3 — document-only / out of equity scope:** economic honeypot (#3),
  category salience (#4), exposure mapper (#5), embodied utility (#10).

## 4. Naming + safety rules

Same anti-theatre and safety rules as [FRAMEWORK_COMPONENT_MAP.md](FRAMEWORK_COMPONENT_MAP.md):
each name must describe a measurable mechanism + testable output + plain-English
meaning. Every new surface, if built, must carry the canonical advisory stamps
(`advisory_status=ADVISORY_ONLY`, `execution_gate=LOCKED`,
`broker_api_called=false`, `ai_execution_count=0`,
`execution_permission=false`, `can_execute=false`) and must never create a
`/execute|/buy|/sell|/order|/broker` route. A high interpretation-risk score must
*reduce* confidence, never unlock anything.
