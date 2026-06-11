# Strategy Engine — Narrative-to-Stock Game Theory

`src/strategy/` turns Sleeping Passenger's pipeline into a complete
narrative-to-stock research chain. **The MVP does not pick stocks
directly; it traces narrative probability into economic payoff nodes** —
then classifies the strategic role, evaluates node payoff quality, models
state transitions, attacks the thesis, adjusts for competition density,
and only then produces a research verdict.

The final question is not "is this company good?" but **"is this company
in the right node, with the right weapon, at the right inflection, with
enough durability to survive attack?"**

All verdict classes (BUY/WATCHLIST/REJECT/…) are **research
classifications for the advisory journal — never instructions**. There is
no execution path anywhere in this system.

## Pipeline

```text
narrative shock (existing: src/simulator/narrative_radar.py)
  → mechanism gate            (mechanism.py — no mechanism, no trade)
  → doctrine filter           (doctrine_filter.py — pre-pre game rejects)
  → value chain / candidates  (existing: src/consent + src/simulator
                               exposure_graph.py tiers; position score here)
  → predator node classifier  (predator_nodes.py)
  → competition density       (competition_density.py)
  → node payoff matrix        (node_payoff.py — casino/food-chain/
                               half-life/threshold/inflection)
  → chess promotion           (chess_promotion.py — dynamic table)
  → underground breakout      (underground.py)
  → distribution intelligence (distribution.py)
  → backhand defence          (backhand.py — strongest bear attack)
  → final decision engine     (final_decision.py — hard rules + bands)
```

Exposed at `POST /strategy/evaluate` and `GET /strategy/doctrine`.

## Design doctrine

* The MVP does not pick stocks directly; it traces narrative probability
  into economic payoff nodes.
* **No mechanism, no trade.** A narrative must change cash flow, demand,
  supply, margins, regulation, cost of capital, multiple, or risk —
  otherwise `narrative_value = 0` and the doctrine filter rejects it.
* The best stock may not be named in the headline. It may be feeding the
  company named in the headline.
* Apex predators are not universally dominant; they are dominant within
  nodes. Nine nodes (orca, great white, tiger shark, sperm whale, giant
  squid, bluefin tuna, elephant seal, leopard seal, crocodile) are
  assigned by weighted trait matching — weak traits stay **unclassified**
  rather than force-fitting the metaphor.
* A node is not valuable by itself. It becomes valuable only when odds,
  hierarchy, edge durability, threshold condition, and inflection timing
  align: `EV = p·Upside − (1−p)·Downside − Cost_of_Waiting`;
  `Durable_Edge = Strength × (1 − e^(−half_life/36mo)) × Defensibility`.
* A company is not only a piece on the board; it is a possible state
  transition. Promotion option value is time-discounted and
  blocker/dilution/execution-penalized; **fake queens** (self-declared
  platforms without network effects, ecosystem, mobility, and retention)
  are demoted by evidence.
* The model's backhand becomes strong by repeatedly receiving the
  strongest bear-case attack. An untested thesis earns zero survival
  credit; an unresolved existential attack caps any score.
* Nadal's greatness is pressure-adjusted by the monsters he had to beat;
  companies are judged the same way (era ×0.6–1.4, opponents ×0.6–1.4).
* Underground is not automatically undervalued; attention is not value
  until it converts. Seven verdicts from BREAKOUT_READY to
  BURIED_FOR_REASON; viral half-life < 30 days is a **Temporary
  Pavilion**, never a durable thesis.
* Raw numbers are meaningless without distribution context. Bell curves
  locate normality (z-scores, percentile bands inside *node-validated*
  peer universes — crocodiles are never compared to bluefin); fat-tail
  logic detects nonlinear breakout potential. Fake outliers (one-off
  data, undersized peers) are penalized, never celebrated.
* European and contemporary museum aesthetics are not decoration; they
  are cognition. The **Transparent Score Panel**
  (`frontend/src/components/TransparentScorePanel.tsx`) is the
  Cartier-Foundation glass structure: every verdict decomposed into
  visible contributors and penalties, never a naked number. Existing
  components map onto the museum metaphors: Evidence Cabinet = consent
  evidence ledger, Dark Room = crash wall / scrutineering panels,
  Inflection Clock = tyre half-life physics, Archive Ledger = decision
  telemetry.

## The Stewards' Room — unified verdict (cross-engine reconciliation)

When a candidate payload carries a `strategy` section,
`evaluate_candidate_payload` runs the strategy chain *inside* the
simulator pipeline and reconciles all engines into ONE verdict
(`src/simulator/unified_verdict.py`):

* **Most conservative engine wins.** Engine verdicts map onto a single
  conservatism scale; disagreement never averages up, it resolves down.
* **Disagreement is information.** Every cross-engine contradiction
  (physics vs strategy, consent vs strategy BUY, crash wall vs BUY,
  buried-noise vs high composite) is a first-class cited output — the
  reflection's Contradiction Card ("market says X, data says Y"),
  rendered by `frontend/src/components/ContradictionCard.tsx`. Material
  splits place the verdict under **CONTRADICTION_HOLD** pending human
  resolution.
* **Self-report is cross-examined** (`src/strategy/cross_exam.py`):
  backhand evidence-strength claims are checked against actual evidence
  volume, hidden-asset traits against visibility claims, probability
  shocks against the prediction-market delta actually present, and
  threshold claims against the meal-box invalidation. Credibility is
  asymmetric: a discredited strategy section may still DOWNGRADE the
  unified verdict but can never upgrade it — gaming the inputs only
  makes the system more conservative.
* Telemetry records the post-unification state, so replay sees what the
  operator saw. Interrupt states (pit stop, black flag) outrank the
  stewards entirely.

This closes the confirmation-bias hole: with three engines and no
reconciliation, an operator could act on whichever verdict agreed with
them. Now there is one verdict, and the disagreements are on the record.

## Hard rules (caps override scores)

No BUY if: threshold uncrossed · existential bear case unresolved · no
mechanism · evidence too weak · negative casino EV despite upside ·
prey-like and deteriorating food chain · fake-outlier metrics · invalid
peer universe · thesis never attacked. Score bands: ≥8.5 high-conviction,
7.0–8.4 strong watchlist, 5.5–6.9 monitor, 4.0–5.4 weak, <4.0 reject.

## Match OS (temporal discipline)

Pre-pre game = doctrine filter; pre-game = battlefield map (strongest
bear attack, node risks, missing thresholds); in-game = re-evaluation
with simulator hysteresis/telemetry; post-game = outcome resolution via
the existing calibration bridge (weight changes are recommendation-only).
The `lifecycle` block of every result records all four stages.

## Limitations (honest)

* All trait scores, channel impacts, and probabilities are
  caller-supplied research inputs — the engine structures judgement, it
  does not source data.
* Weights, bands, and thresholds are doctrine-derived, not empirically
  calibrated (no labeled outcome data exists).
* Node classification is deterministic trait matching, not learned; the
  unclassified guard limits but does not eliminate metaphor overfit.
* Verdict labels are analytical categories. ADVISORY_ONLY, no execution,
  human judgement required.
