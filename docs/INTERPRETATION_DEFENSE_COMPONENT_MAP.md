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
| 14 | Signal Half-Life / Edge Durability Estimator | `signal_half_life_estimator` | `scripts/signal_half_life_estimator.py` (SHIPPED 2026-06-08, **P3**); lineage `asset_durability_filter.py`, `candidate_memory_decay.py`, `late_adoption_lockout.py` | **SHIPPED (heuristic)** — "snack vs signal vs asset" edge-durability + decay λ; layered into expanded IDS as a bounded demotion; `SNACK` caps at DEFENSIVE; `test_signal_half_life_estimator.py` | P3 (done; capped 7 — no live attention/fundamentals/crowding feed) |
| 15 | Signal Payoff-Capture / Value-Capture Estimator | `signal_payoff_capture_estimator` | `scripts/signal_payoff_capture_estimator.py` (SHIPPED 2026-06-08, **P3**); lineage `incentive_who_benefits_analyzer.py`, `false_negative_casino_monopoly_layer.py`, `asymmetry_survival_scorer.py` | **SHIPPED (heuristic)** — "gross is not net": structural position + margin capture + pricing power − claimant dilution; `WEAK_CAPTURE` caps at DEFENSIVE + `gross_not_net` flag; layered into expanded IDS; `test_signal_payoff_capture_estimator.py` | P3 (done; capped 7 — no live market-structure/capex/ownership feed) |
| 16 | Auditable Payoff-Capture Diagnostic | `payoff_capture_diagnostic` | `scripts/signal_payoff_capture_estimator.py::payoff_capture_diagnostic` (SHIPPED 2026-06-09) | **SHIPPED (explanatory-only)** — four sub-captures (gross→margin / profit→cash / cash→owner / bargaining) + `primary_value_leak` attribution + `owner_capture_confidence` + `false_house_risk` + `falsification_hint`; never changes risk/grade; `unknown`/`insufficient_evidence` when data absent | P1 of "harder-to-fool" arc (done) |

### 2026-06-09 reflection #3 → repo ("harder to fool": evidence / confidence / falsification)

| Reflection priority | Maps to | Status |
|---|---|---|
| P1 Payoff-Capture explanation card (sub-captures + leak) | `payoff_capture_diagnostic` (#16) | **SHIPPED 2026-06-09** |
| P2 Owner-capture confidence | `payoff_capture_diagnostic.owner_capture_confidence` | **SHIPPED 2026-06-09** |
| Layer 7 Falsification hooks | `payoff_capture_diagnostic.falsification_hint` | **SHIPPED 2026-06-09** |
| P3 False-house detector | `payoff_capture_diagnostic.false_house_risk` (explanatory flag) | **SHIPPED 2026-06-09** (flag-only; not a new penalty) |
| P4 Capture momentum (Δ over time) | — | doctrine (no per-ticker time-series feed; would be insufficient_evidence) |
| P5 / Layer 6 Demoter audit table + outcome calibration | — | doctrine (data-gated; calibration corpus = INSUFFICIENT_EVIDENCE) |
| Role / lane / research-depth labels (advisory-safe) | — | out of focus (portfolio-framing, not interpretation-defense) |

### 2026-06-08 reflection #2 concepts → repo (meal-box / casino / toll-gate / payoff capture)

| Reflection component | Maps to | Status |
|---|---|---|
| Payoff Stack + Payoff Dilution + Toll Gate + House Edge + Market Structure (8.10–8.13, 8.25) | `signal_payoff_capture_estimator` (#15) | **SHIPPED 2026-06-08** |
| Half-Life Clock (8.8) | `signal_half_life_estimator` (#14) | shipped (P3) |
| Cherry-Coke / Narrative Gap (8.6) | `narrative_substance_gap` (#2) | shipped (P2) |
| SEO Trap / Feed Risk (8.18–8.19) | `distribution_amplification_detector` (#11) | shipped (P2) |
| Casino Role / House Edge (8.9–8.10) | `incentive_who_benefits_analyzer` + `false_negative_casino_monopoly_layer` | shipped / existing |
| Speed-Limit / Actionability (8.14) | `candidate_executable_split` (CQS/EQS) | existing |
| Perception Filter (8.26) | `perception_control` + the IDS stack | existing |
| Role / Squad / Lane / Portion classifiers (8.1–8.4, 8.15, 8.20, 8.27) | — | **out of scope** (allocation/sizing = execution domain, LOCKED; doctrine-only) |

### 2026-06-08 reflection concepts → repo (game theory / half-life / casino × food-chain)

| Reflection module | Maps to | Status |
|---|---|---|
| Half-Life Estimator (Module 3) | `signal_half_life_estimator` (#14) | **SHIPPED 2026-06-08** |
| Incentive Cleanliness (Module 4) | `incentive_who_benefits_analyzer` (#6) | shipped (P2) |
| Casino Pull / Hype-Decay (Modules 5, 12) | `distribution_amplification_detector` (#11) | shipped (P2) |
| Narrative Premium (Module 11) | `narrative_substance_gap` (#2) | shipped (P2) |
| Objective Alignment / Audience misread (Modules 14, 8) | `audience_misinterpretation_risk` (#13) | shipped (P2) |
| Moneyball Mispricing (Module 9) | `composite_edge_score.py` + provenance lock | partial / existing |
| Threshold Proximity + Inflection (Modules 2, plus Insight 6–7) | `activation_trigger_tracker.py`, `tension_accumulation_tracker.py` | partial lineage (backlog) |
| Signal Value Engine (Module 1) | composite of #1–#14 IDS | conceptually the expanded IDS itself |
| Dating Funnel / Algorithmic GNH / Food-Chain / Movie Library (Modules 6,7,10,13,15) | — | **out of equity scope** (doctrine-only) |

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
