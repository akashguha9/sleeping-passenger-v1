# 2026-06-08 — Meal-Box / Casino / Toll-Gate Reflection (Payoff Capture)

> **Status:** strategy reflection + integration record. One module shipped
> (`signal_payoff_capture_estimator.py`); the rest is doctrine/backlog mapped in
> [../INTERPRETATION_DEFENSE_COMPONENT_MAP.md](../INTERPRETATION_DEFENSE_COMPONENT_MAP.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `execution_permission = false`

## 0. The reflection in one line

> *Gross is not net. The house owns the game, not the prediction. A large pie with
> too many claimants becomes thin slices — buy the slice that actually reaches the
> owner.*

A long forensic extraction that turned everyday consumption (meal boxes,
Coke/Pepsi distribution contracts, ramen modularity, casinos, Berlin club payoff
stacks, toll roads, Autobahn lanes, IPL/EPL squads, sponsor/ad pools, market
structure, Huxley's *Doors of Perception*) into a stock-selection architecture.

## 1. Most of it is already the MVP's spine — or out of scope

Mapping the reflection's 27 proposed components to the repo:

- **Half-life clock (8.8)** → `signal_half_life_estimator.py` (shipped 2026-06-08).
- **Cherry-Coke / narrative-vs-revenue gap (8.6)** → `narrative_substance_gap.py`.
- **SEO-trap / feed-risk (8.18–8.19)** → `distribution_amplification_detector.py`
  (HYPE_LED), provenance contract source tagging.
- **Casino role / house-edge (8.9–8.10)** → `incentive_who_benefits_analyzer.py`,
  `false_negative_casino_monopoly_layer.py`.
- **Speed-limit / actionability (8.14)** → `candidate_executable_split.py`
  (CQS/EQS), liquidity gates.
- **Perception filter (8.26)** → `perception_control.py`; the whole IDS stack.
- **Role / squad / lane / portion classifiers (8.1–8.4, 8.15, 8.20, 8.27)** →
  these are **portfolio-construction / allocation** concepts. Allocation and
  sizing are **out of advisory-demote-only scope** (execution is LOCKED), so they
  stay doctrine-only. The MVP scores and gates; it never sizes or allocates.

## 2. The one genuine gap → shipped

The existing demoters ask whether the thesis is *real* and whether it *decays*.
None asked the orthogonal structural question this reflection foregrounds:

> *Even if the thesis is true, does the **equity holder** actually capture the
> value — or is it diluted away by commodity competition, too many prior
> claimants (debt/suppliers/platform fees), capex/working-capital drag, or weak
> market structure?* ("Berlin club payoff stack": large gross, thin owner residual.)

**Shipped:** `scripts/signal_payoff_capture_estimator.py` — deterministic,
advisory-only, **demote-only** value-capture scorer wired into the expanded IDS
as a second P3 demotion (alongside half-life):

```
value_capture = 0.30·structural_position + 0.30·margin_capture
              + 0.20·pricing_power − 0.20·claimant_dilution
payoff_capture_risk = 100·(1 − value_capture)        # high = diluted
capture_grade ∈ {STRONG_CAPTURE, MODERATE_CAPTURE, WEAK_CAPTURE}
```

- `structural_position` from a market-structure feed (monopoly/platform/duopoly
  /oligopoly/.../commodity → pricing power), lifted by toll-gate signals
  (switching costs, distribution control); else an evidence-type proxy.
- `margin_capture` = residual that reaches the owner (gross/operating margin).
- `claimant_dilution` = debt + supplier power + platform-fee dependence + capex
  /working-capital drag (prior claims ahead of equity).
- `WEAK_CAPTURE` caps the grade at `DEFENSIVE_REVIEW`; a `gross_not_net` flag
  fires when margins are thin and dilution is high.

Integration: `evaluate_candidate_expanded` applies the calibrated P2 four-module
penalty first (untouched), then layers the two P3 demotions (half-life
`0.15·risk`, payoff-capture `0.12·risk`). All terms only subtract, so the
`test_G`/`test_J` invariant (expanded IDS ≤ P1 IDS) still holds. Tests:
`tests/test_signal_payoff_capture_estimator.py` (8) + integration `test_J`/`test_K`.

## 3. What this deliberately does NOT do

- No allocation, no position sizing, no role/squad assignment — those are
  execution-domain decisions, and execution is LOCKED. A high capture risk only
  *reduces* confidence; it never sizes, allocates, or unlocks anything.
- No fabricated market-structure / capex feeds → offline fundamental proxies,
  conservatively capped (honest ≤ 7/10 until real structure/ownership feeds).

## 4. Unresolved questions carried forward (from the reflection §9)

Module weighting; minimum data to classify market structure reliably; gathering
payoff-stack data when companies report only gross; valuing "house-like"
businesses without overpaying; the Narrative-Gap rejection threshold; and keeping
the system simple enough for Year-1 survival.
