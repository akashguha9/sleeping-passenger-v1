# Games Layer — Identify the Game Before Choosing the Move

`src/games/` adds the classification layer the pipeline lacked: **the
edge is not more data; it is knowing what game the data belongs to.**
Everything is ADVISORY_ONLY — staged actions are research labels, never
instructions, and no execution path exists anywhere in this system.

## Why it exists

The simulator scored every thesis through one lens. But the same signal
means different things in different decision environments: a hot
narrative is fuel in a politics/regulation game (SHASN) and a hazard in
a cash-flow game (Pallanguzhi). And the repo emitted ONE score where two
were needed: a hyperreal meme asset can be tradeable and uninvestable at
once — collapsing that into one number is the exact error the Simulacra
layer names.

## The three classifiers

### 1. Game archetypes (`game_classifier.py`)

Eight decision environments, classified per thesis layer (macro / sector
/ company / signal / reality) from normalized features — a **nested
stack**, never a single label. Weak feature matches stay `unclassified`
(metaphor-overfit guard). Each archetype carries signal-interpretation
weights that blend confidence-weighted across the stack:

| Archetype | Decision environment | Interpretation shift |
|---|---|---|
| snakes_and_ladders | exogenous shocks/catalysts, no move choice | catalysts ×1.4 |
| ludo | stochastic strategy: the edge is the choice after the roll | neutral |
| chaturanga | competitive strategy, minimax, moats | fundamentals ×1.2 |
| bagh_bandi | predator-prey power vs containment | hyperreality ×1.1 |
| pallanguzhi | resource/cash flow | fundamentals ×1.4, narrative ×0.5 |
| carrom | execution, slippage, timing | neutral |
| shasn | politics, regulation, coalitions, narrative-as-resource | narrative ×1.3 |
| simulacra | belief about belief; the scoreboard is the game | narrative ×1.4, hyperreality ×1.5 |

### 2. Dice profiles (`dice_profiles.py`)

Every signal source is an uncertainty engine: `precision` (audited
filings), `d4/d6/d10/d20` by variance, `d100` (prediction markets —
tradable belief, not truth), `rounded` (noisy chatter),
`loaded_possible` (manipulation suspected; confidence capped at 0.25),
`non_transitive` (regime-dependent). Plus:

* **Loaded-die detector** — total-variation distance of observed
  outcomes vs expectation (`bias = Σ|obs−exp|/2`, threshold 0.20),
  with a 30-observation floor so an odd handful of rolls stays an
  anecdote, never a bias finding.
* **Regime matchups** — `regime_matchup` answers who wins *in this
  regime* and fires a NON-TRANSITIVE warning when the winner flips
  across regimes: absolute-ranking talk becomes a category error.

### 3. Reality anchor (`reality_anchor.py`)

```text
RAS = directness + auditability + confirmation + cash-flow link
      − narrative dependency                      (each 0–1)
SimulacraLayer ∈ {reflection, distortion, masking_absence, hyperreality}

InvestmentScore   = fundamentals × reality anchor × payoff asymmetry
TradeabilityScore = narrative momentum × liquidity × reflexivity
DangerScore       = hyperreality × leverage × weak cash flow × crowding
```

Four classifications: `reality_anchored_opportunity` (boring evidence
beats exciting simulation), `tradeable_but_dangerous`, `aligned`,
`weak_both`.

## Pipeline integration

An optional `games` payload section flows through
`evaluate_candidate_payload`:

* the nested game stack and dice profiles land in `result["games"]` and
  the dominant game becomes a **calibration telemetry segment** (the
  wind tunnel can measure per-game drift);
* `danger_score ≥ 5` fails the **reality gate**: the investment ladder
  state is capped at watchlist (`REALITY_GATE_CAPPED`) while
  tradeability stays visible — classified, not censored;
* any `loaded_possible` die or a positive loaded-die test stamps
  `LOADED_DICE_SUSPECTED`;
* the **advisory action router** (`advisory_router.py`) translates the
  final verdict into the staged vocabulary — Reject · Watch · Research
  More · Paper Trade · Buy Candidate · Hold · Exit Candidate — with
  three overrides: contradiction holds always route to Research More,
  tradeable-but-dangerous blocks investment-grade actions, and demotion
  from a candidate state routes to Exit Candidate.

## Worked example (the reflection's own)

```text
Stack: macro=shasn, company=pallanguzhi, signal=ludo, reality=simulacra
Dice:  filings=precision, social=rounded, prediction_market=d100,
       narrative_push=loaded_possible
Route: Watch / Research More / Paper Trade depending on thresholds
```

Verified end-to-end in `tests/test_games_layer.py::
test_reflection_worked_example_end_to_end`.

## What already existed (not rebuilt)

Casino EV, food-chain power, half-life decay, threshold gates,
inflection, red-team, triple-blind, predator-prey, and politics/narrative
layers predate this module (see STRATEGY_ENGINE.md and
MARKET_PHYSICS_SIMULATOR.md). The games layer adds classification and
interpretation on top — it does not duplicate scoring.

## Limitations (honest)

* Features, reliabilities, and reality components are caller-supplied
  research judgements; the layer structures interpretation, it does not
  source data.
* Interpretation weights are doctrine-derived, not fitted; the
  `dominant_game` telemetry segment exists precisely so the wind tunnel
  and calibration bridge can someday measure them.
* Archetype classification is deterministic trait matching; the
  unclassified guard limits but does not eliminate metaphor overfit.
