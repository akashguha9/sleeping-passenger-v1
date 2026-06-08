# 2026-06-08 — Game Theory / Half-Life / Threshold / Incentives Reflection

> **Status:** strategy reflection + integration record. One module shipped
> (`signal_half_life_estimator.py`); the rest is doctrine/backlog mapped in
> [../INTERPRETATION_DEFENSE_COMPONENT_MAP.md](../INTERPRETATION_DEFENSE_COMPONENT_MAP.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `execution_permission = false`

## 0. The reflection in one line

> *The house is whoever controls the payoff function; half-life tells you whether
> attention is a snack, a signal, or an asset; price activation, durability, and
> who-benefits — not the spike.*

A long forensic extraction across game theory (chess/cricket formats, WWE
stipulations, Werewolf/Hunger Games/Bird Box archetypes), Moneyball mispricing,
IPL auction portfolio construction, Bhutan GNH, algorithmic feeds, dating-app
funnels, and the **casino × food-chain** model. It distils to one integrated
scoring thesis:

> Every signal should be priced by **who benefits**, **who is extracted**,
> **whether value crosses a threshold**, **how long the value lasts (half-life)**,
> and **whether incentives improve or degrade flourishing**.

## 1. Why most of this is already the MVP's spine

The MVP is already an **interpretation-defense** engine. Mapping the reflection's
15 proposed modules to the repo (full table in the component map):

- **Incentive cleanliness / who-benefits** → `incentive_who_benefits_analyzer.py`
  (P2, shipped 2026-06-07).
- **Distribution amplification / casino-pull / hype-decay** →
  `distribution_amplification_detector.py` (P2, shipped).
- **Narrative premium vs substance** → `narrative_substance_gap.py` (P2, shipped).
- **Objective-mismatch / audience misread** → `audience_misinterpretation_risk.py`
  (P2, shipped).
- **Mispricing edge (Moneyball)** → `composite_edge_score.py`, the fresh-discovery
  contract + isolated lanes (provenance defense).
- **Stress / adverse-regime survival** → `adverse_regime_stress_test.py` (P1).
- **Threshold / activation / inflection** → partial lineage in
  `activation_trigger_tracker.py`, `tension_accumulation_tracker.py`.
- **Durability classes** → `asset_durability_filter.py`, `candidate_memory_decay.py`.

Cross-domain modules (Dating Funnel Evaluator, Algorithmic GNH, Food-Chain
Position Classifier, Movie Simulation Library, Sports Asset Pricing) are
**out of equity scope** and stay doctrine-only.

## 2. The one genuine gap → shipped

The four P2 modules score *hype*, *narrative*, *incentive*, and *audience*. None
scored the reflection's headline new variable: **temporal durability / half-life**
— "is this edge a snack, a signal, or an asset?" A short-half-life catalyst (a
one-day price pop, a momentum/meme spike) benefits the *house* (churn) more than
the holder; a long-half-life catalyst (a structural contract win, durable
re-rating) compounds.

**Shipped:** `scripts/signal_half_life_estimator.py` — a deterministic,
advisory-only, **demote-only** edge-durability scorer wired into the expanded
interpretation-defense engine as a P3 layer:

```
durability = 0.30·structural_prior + 0.25·fundamental_backing
           + 0.15·falsifiability + 0.15·catalyst_language_bias
           − 0.25·attention_decay − 0.15·crowding
short_half_life_risk = 100·(1 − durability)        # high = snack
half_life_class ∈ {DURABLE, SIGNAL, SNACK}
lambda_per_day = ln(2) / half_life_days            # reported, advisory
```

Integration: `evaluate_candidate_expanded` applies the P2 four-module penalty
first (calibrated math untouched), then layers a bounded half-life demotion
(`0.15·short_half_life_risk`). A `SNACK` class caps the grade at
`DEFENSIVE_REVIEW`. It can only **subtract** — `test_G` (expanded ≤ P1) still
holds — and a non-live candidate is never scored as live. Tests:
`tests/test_signal_half_life_estimator.py` (8) + two integration tests in
`tests/test_expanded_interpretation_defense_engine.py`.

## 3. What this deliberately does NOT do

- No real-money sizing, no broker route, no execution unlock. A high
  short-half-life risk *reduces* confidence; it never authorises anything.
- No new fresh-discovery candidates — the half-life layer only annotates the
  clean payload that the provenance contract already vetted.
- No live attention/fundamentals/crowding feed yet → offline evidence-type
  proxies, conservatively capped (so the score honestly stays ≤ 8/10).

## 4. Unresolved questions carried forward (from the reflection §9)

Weight calibration across threshold × half-life × incentive cleanliness; early
half-life estimation before decay data exists; "useful short half-life" vs
"predatory short half-life"; and the meta-question — *how do we keep the MVP
itself from becoming a casino house?* (answer so far: every layer can only
demote, never promote or extract).
