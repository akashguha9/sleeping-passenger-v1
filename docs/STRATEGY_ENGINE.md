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

## Adaptive Opponent Model (`adaptive_opponent.py`)

Markets are adaptive opponents, not static scoreboards. The optional
`opponent` payload section runs the mentor's questions inside the
pipeline:

* **Weapon Map** — `WeaponScore = strength × reliability × durability −
  crowding/2`; a strong AND crowded weapon is flagged `overused`
  (predictability is attack surface).
* **Weak side + Minimum Viable Weakness** — `AttackROI = severity ×
  attack probability − cost to exploit` (improving weaknesses raise the
  attacker's cost): `fatal / exploitable_manageable / above_threshold`.
  A weakness does not need to become a strength; it needs to become
  expensive to attack.
* **Niche classifier** — beachhead · profitable_cage ·
  one_product_fragility · overvalued_niche_narrative ·
  underpriced_expansion_platform. Good company ≠ good stock.
* **Opponent Adaptation Index** — `OAI = (repricing + crowding +
  saturation) / 3·signal`: fresh → partially_recognized → crowded →
  exhausted, plus anti_consensus; `LiveEdge = 0.5^(age/half-life)`.
* **Market-awareness blind layers** (distinct from the bias triple-blind
  in `src/simulator/triple_blind.py`): 1 = hidden pattern, 2 = mutually
  known (variation game), 3 = crowded obvious trade with a neglected
  second/third-order node — bait the variation. Layer 0 = no edge.
* **Catalyst + 1** — the serve creates a predictable return:
  `PPV = p(first reaction) × E[lag repricing] − current lag reaction −
  error risk/2`; pre-positioning value lives in the lagging node.
* **Complete Game Score** — `mean(capabilities) − 1.5·variance`: a
  complete opponent punishes segmented games.

Pipeline gate: an `exhausted_edge` OAI or a `fatal` weak side caps the
investment state at watchlist (`EDGE_EXHAUSTED` / `FATAL_WEAK_SIDE`) —
the model must know when its own edge has become predictable. Existing
physics is reused, not rebuilt: edge decay = tyre half-life law,
second-order nodes = exposure graph, bait-vs-breakout = underground +
scrutineering, adaptive feedback = calibration bridge + dice audit.

## Self-Feed — the model feeds itself (`self_feed.py`)

The opponent model's biggest confessed limitation was that every input
was a caller judgement — yet the pipeline's own engines had ALREADY
computed most of them two steps earlier. `src/strategy/self_feed.py`
wires those engines into the opponent section automatically, with
provenance on every derived value (no hidden magic):

| Opponent input | Derived from |
|---|---|
| `adaptation.crowding`, `crowding` | `theme_mapper.crowding` |
| `adaptation.repricing_observed` | `theme_mapper.valuation_heat`, `risk_factors.price_already_ran` |
| `adaptation.narrative_saturation` | narrative state base (ignored 0.05 … overheated 0.90) blended 60/40 with dirty-air score |
| `adaptation.signal_strength` | strongest tyre `effective_signal_strength / 100` |
| `adaptation.recognition_age_days` / `edge_half_life_days` | tyre `signal_age_hours` / adjusted half-life |
| `weaknesses` | crash `risk_factors` (incl. the consent bridge's auto-injected fragilities) |
| `strengths`, `capabilities`, `durability` | exposure-resolver components (+ narrative velocity) |
| `attack_probability` | `0.5·crowding + 0.5·saturation` |
| `evidence_reliability` | `narrative_tracker.source_quality` |

**The adaptation gate now fires even when nobody asked.** A payload
with no `opponent` section gets one auto-derived (`OPPONENT_SELF_FED`);
a crowded, saturated, weak-signal trade is capped at watchlist on the
caller's own physics numbers (verified end-to-end in
`tests/test_self_feed.py::test_crowded_trade_capped_without_any_opponent_section`).

**Cross-exam asymmetry (anti-gaming).** A caller override toward
conservatism always wins, unchallenged. A more OPTIMISTIC override
loses to the engine-derived value, and the rejected override is
recorded in `opponent.self_feed.challenges` with its provenance
(`OPPONENT_OVERRIDE_CHALLENGED`). Omitting an engine-evidenced weakness
(severity ≥ 0.5) and claiming strengths above what exposure physics
shows are challenged the same way. Gaming the opponent section can only
make the verdict more conservative.

**Honesty rules.** A value is derived only when the engine's inputs
were genuinely present in the payload (an absent theme section proves
nothing about crowding). Purely self-fed data may cap the ladder only
when ≥ 3 of the 4 adaptation drivers are engine-backed; exhaustion is a
ratio over signal strength, so the cap additionally requires a MEASURED
signal — a defaulted denominator exploding the OAI is stamped
`SELF_FEED_LOW_COVERAGE` and warns without capping.
`{"self_feed": {"enabled": false}}` restores the caller-judgement-only
path.

**Wind-tunnel gate experiment.** New gates must earn trust:
`run_gate_experiment` (in `src/simulator/wind_tunnel.py`) replays the
same bars twice — self-feed on vs off — and compares forward returns on
the bars where the gate changed the verdict. In the tested series the
single capped bar carried a −11.1% forward return vs +6.1% on
undiverged bars (the cap dodged the losing bar); when the gate never
diverges the report says "insufficient evidence", not success. A/B
counterfactual replay measures gate value and never clears autotune.

## Counterfactual Wind Tunnel — the model doubts itself (`counterfactual_wind_tunnel.py`)

Self-feed made the model consistent with its own physics — but a gate
that fires on one history proves nothing about WHY it fired or whether
it would survive a different rally. `src/strategy/
counterfactual_wind_tunnel.py` perturbs, ablates, delays, and
regime-flips a payload's own evidence, then grades whether the verdict
survives. Opt-in: `{"counterfactual_audit": true}` attaches the report
at `result["counterfactual_wind_tunnel"]` (variants strip the flag —
the audit never audits itself; the verdict itself is never changed).

**Perturbation suite (graded, falsifiable).** 16 deterministic variants,
each with a directional expectation: ablations of crowding / heat /
weaknesses / exposure (`NOT_WORSE` — suppressing adverse evidence must
never worsen), signal delay +168h and source-quality degradation
(`NOT_BETTER` — stale or unreliable evidence must never read better),
optimistic opponent override (`CHALLENGED_NOT_BETTER`), conservative
override (`NOT_BETTER`, unchallenged), engines-dark fallback
(`NO_UNMEASURED_CAP` — exhaustion needs measurement; a caller-judged
FATAL_WEAK_SIDE cap may stand), and three regime probes: benign
(`CAP_SILENT`), hostile (`CAP_FIRES`), noisy (`WARN_NOT_CAP`).
Perturbations of absent sections are skipped, not graded.

```text
RobustnessScore = matched / graded
                  − 0.1 · [gate hangs on one input]      (fragility)
                  − 0.15 · anti-gaming breaches          (overconfidence)
```

**Causal gate attribution.** When the adaptation gate fired, each driver
(theme crowding, valuation heat, narrative saturation, signal weakness,
weak-side severity) is neutralized one at a time:
`GateAttribution(input) = gate(original) − gate(ablated)`.

* `NECESSARY_DRIVER` — ablation un-fires the gate;
* `SUFFICIENT_DRIVER` — alone (all others neutralized) it still fires;
* `REDUNDANT_SUPPORT` — gate holds, OAI moves;
* `PASSENGER_SIGNAL` — gate holds, OAI moves < 0.05 (it was in the
  explanation, not in the cause);
* `FRAGILE_SINGLE_POINT` — exactly one necessary driver controls the
  gate (flagged, warned, and charged the fragility penalty);
* `MISSING_BUT_REQUIRED` — input absent, role untestable.

**Worked example (tested verbatim,
`tests/test_counterfactual_wind_tunnel.py`).** The crowded fixture's
exhaustion cap: 14/14 graded counterfactuals matched → robustness 1.00,
gate margin +0.15 (`GATE_MARGIN_THIN`), all four OAI inputs
NECESSARY_DRIVER (a conjunction near the threshold), weak-side severity
a named PASSENGER_SIGNAL. The fatal-weak-side fixture: 14/14 matched but
the gate hangs on one input → robustness 0.90 after the
FRAGILE_SINGLE_POINT penalty, `weak_side_severity` both necessary and
sufficient.

**Anti-gaming: exposed, not denied.** No internal layer can verify the
world outside the payload. Optimistic opponent overrides are challenged
and cannot rescue a verdict (tested); but suppressing theme crowding,
valuation heat, or the narrative section, or inflating signals, DOES
improve the verdict — so the audit publishes exactly those fields in
`gameable_inputs` with `VERDICT_SENSITIVE_TO_CALLER_INPUT:*` warnings,
and each gameable field raises `false_negative_risk` (+0.05, cap 0.4).
Conservative-wins survives every probe: caller caution is honored,
never rewarded.

**Gate utility.** `classify_gate_utility` labels a wind-tunnel A/B
experiment `helpful / harmful / over_conservative (≥50% divergence and
capped win rate ≥0.6) / regime_dependent / neutral /
insufficient_evidence`. GateUtility is the capped-vs-undiverged forward
return difference; a gate that never diverged has proven nothing.

**How to read the numbers.** `robustness_score` is the fraction of
falsifiable counterfactual expectations that held, penalized for
fragility and overconfidence — 1.0 means "survived every alternative
history we constructed", not "true". `false_positive_risk` /
`false_negative_risk` are deterministic heuristic indicators (benign
regime capped → 0.85; thin gate margin → 0.25; gameable fields → +0.05
each), never fitted probabilities. Every report carries its tier
warnings (`SYNTHETIC_REPLAY_TIER`, `LOW_REAL_WORLD_CALIBRATION` until
real imported data flows). ADVISORY_ONLY: the audit annotates analysis;
it never changes the verdict, and no execution path exists anywhere.

## Edge Lifecycle Engine — detect live, underpriced acceleration before decay (`edge_lifecycle.py`)

The reflection's closing truth: *the MVP should not predict winners; it
should detect live underpriced acceleration before the edge decays
below threshold.* What already existed and is REUSED, not rebuilt:
half-life physics (signal tyres), threshold gates (cherry-pick ladder),
narrative phases (tracker), crowding (theme/OAI), belief gaps
(net_signal_value + Bayes + prediction radar), friction
(execution_friction), anti-streak discipline (dice audit + driver +
outcome quadrants), self-doubt (counterfactual wind tunnel). What was
genuinely missing — five components, one optional `lifecycle` payload
section:

* **Carrying capacity** — `G(t) ≤ K`, never `G(t) ≤ e`:
  `K = scale + (1−scale) · headroom(TAM evidence, optionality, pricing
  power, competition, regulation)`; states `early_runway → mid_curve →
  bending_toward_saturation → saturated` (3-period growth deceleration
  bends the curve early); `growth_quality = r × (K − G)` — tested: a
  60% grower near its ceiling scores below a 20% grower with runway;
  `fake_exponential` flags claimed growth that would overrun its own
  evidenced ceiling inside the horizon (an e^rt story on a
  K/(1+Ae^−rt) curve).
* **Acceleration path (brachistochrone)** — `mgh → ½mv²`: Path B
  `controlled_acceleration` (early conversion with evidence) beats
  Path A `reckless_drop` (momentum without support) and Path C
  `slow_straight_line`; `stalled_potential` is stored energy with no
  catalyst. `AccelerationEdge = catalyst × proximity × momentum /
  (friction + decay + crowding)`; `conversion = momentum / potential`.
* **Arbitrage convergence** — `net edge = gap × P(convergence) −
  friction − ½·break risk`; a gap > 0.1 with no named convergence
  catalyst (or P < 0.25) is a **value trap**; crowding halves the gap's
  half-life window.
* **Hedged edge** — `hedged = thesis − ½·unwanted beta − cost`;
  efficiency = risk reduced / cost; over-hedge (cost ≥ edge or
  efficiency < 1) kills the edge it protects; survival gates upside
  (`ruin_risk ≥ 0.5` → not viable). Structure recommendations only —
  no instrument is ever traded.
* **Thesis expiry clock** — `E(t) = E0·0.5^(t/h) > T ⇒ t_expiry =
  h·log₂(E0/T)`. Worked example (tested): E0 0.8, T 0.2, h 30d →
  **exactly 60 days to expiry**. Every thesis gets a death date.

**The Opportunity equation** reconciles them:

```text
Opportunity = (Runway × Acceleration × Underpricing)
              / (Decay + Crowding + Friction + Execution + Unhedged)
Verdicts: live_underpriced_acceleration · potential_without_catalyst ·
          priced_in · saturating_compounder · decayed_below_threshold ·
          watch_and_revalidate
```

**Self-fed, conservative-wins** (mirroring the self-feed asymmetry):
crowding from the theme mapper wins when higher than the caller's;
live edge from blended tyre grip wins when LOWER (a caller claiming
0.9 over a stale 120h social spike gets the tyre's ~0.01, with
provenance `signal_tyres.blended_grip_pct/100` — tested end-to-end);
priced belief defaults to the Bayes prior or prediction-market
probability. **Gate:** `decayed_below_threshold` → `EDGE_EXPIRED`,
`saturating_compounder` → `SATURATION_PRICED_IN`, both cap at
watchlist; the golden `LIVE_UNDERPRICED_ACCELERATION` stamp is a
research label that never promotes anything. ADVISORY_ONLY.

## Lifecycle Attribution + Calibration Ledger (`lifecycle_attribution.py`)

The lifecycle verdict now explains itself and answers for itself: *here
is the verdict, here is what caused it, here is what would change it,
and here is how we will know later whether it was right.*

**Attribution (causal sensitivity).** Sixteen single-assumption twists
rerun the PURE `assess_edge_lifecycle` function (no pipeline re-runs —
deliberately distinct from `counterfactual_wind_tunnel`, which perturbs
the physics payload and attributes the adaptation gate). `Δ_verdict =
rank(perturbed) − rank(baseline)` over the verdict ladder
(decayed 0 → golden 4) classifies every input:

* `VERDICT_CRITICAL` — removing the penalty promotes (it was binding);
* `KILL_SWITCH` — an adverse twist demotes (the assumption must hold);
* `SCORE_MOVER` — verdict holds, opportunity moves ≥ 0.5;
* `COSMETIC` — in the explanation, not the cause: its weight is
  unsupported by verdict evidence at this operating point.

`Fragility = flips / 16`; `Concentration = max|Δrank| / 4`. Fragility
≥ 0.25 stamps `LIFECYCLE_FRAGILE` (warn-only, never a cap): a golden
state with four kill switches is a different animal from a robust one.
Survival now gates the golden verdict — a declared hedge that is
over-hedged or ruin-exposed blocks `live_underpriced_acceleration`.

**Worked example (tested verbatim).** The golden fixture's kill
switches: `close_belief_gap`, `shrink_carrying_capacity`,
`weaken_convergence`, `raise_hedge_cost` (fragility 0.25 → stamped).
On the decayed fixture, `restore_live_edge` jumps rank 0 → 4
(concentration 1.0: one assumption controls the whole range) while
`extend_half_life` is COSMETIC — `t = h·log₂(E₀/T)` is zero for any h
once E₀ ≤ T; a longer half-life cannot rescue a dead edge. Honest audit
finding: `break_risk` is verdict-cosmetic at every tested operating
point — it moves the arbitrage net edge but never the verdict.

**Calibration ledger (falsifiability).** `entry_from_lifecycle` freezes
the prediction at entry (edge, expiry days, K, convergence probability,
hedge structure, fragility, kill switches, data tier);
`resolve_entry` scores it when the thesis resolves:

```text
CalibrationError = |E_pred − E_realized|
ExpiryError      = |t_pred − t_actual_death|  (+ expired-before-
                                               resolution flag)
K_error          = |K_est − K_realized| / K_realized
ConvergenceScore = P_pred − 1[converged]      (signed overconfidence)
HedgeEffect.     = drawdown avoided / (upside sacrificed + cost)
```

Unobserved outcomes stay `None` — never "fine". `summarize_ledger`
reports means, the expired-before-resolution rate, and the WORST data
tier present (one synthetic row keeps the whole summary
`synthetic_fixture`); below 10 records the status is
`require_more_data`. Synthetic rows prove the plumbing, never the
model; lifecycle weights stay doctrine-derived until the ledger is
scored on backtest or empirical tiers. ADVISORY_ONLY.

## Harder to fool — bottleneck K, safe belief gaps, outcome import, streak audit

Four discipline upgrades in one sprint (`edge_lifecycle.py` extensions
+ `outcome_import.py`):

**Carrying-capacity bottleneck decomposition.** Growth does not hit one
ceiling; it hits the TIGHTEST bottleneck first. An optional
`capacity.ceilings` dict (market, adoption, pricing, margin,
regulatory, capital, competition, execution, attention…) sets
`K_eff = min(K_blend, min_i(K_i))` with the `binding_constraint` named;
a ceiling below current scale means saturated, not impossible (K floors
at scale, utilization 1.0). A binding `attention`/`narrative` ceiling
is called what it is: a ceiling made of hype. Tested: a tight
competition ceiling exposes a fake-exponential narrative that the
blended K would have tolerated.

**Safe belief gap.** The golden state now demands the disciplined gap:

```text
safe_gap = (gap − uncertainty_band − ½·price_already_moved·gap)
           × evidence_quality
```

A 0.30 gap on 0.3-quality evidence with a 0.10 band is a 0.06 safe gap
— heat, not edge (`gap_unsupported` when raw > 0.1 collapses to
≤ 0.02). With no discipline inputs supplied, `safe_gap == gap`
(backwards compatible); with them, a wide gap must survive uncertainty,
price staleness, and evidence quality to reach
`live_underpriced_acceleration`.

**Resolved-outcome import** (`outcome_import.py`). The production
contract for real outcomes — no live feeds, just an honest JSON row
(entry/exit prices + benchmark + optional predictions):
`realized_alpha = R_asset − R_benchmark`, `prediction_error =
|predicted_edge − realized_alpha|`, `expiry_accuracy = |t_pred −
t_actual|`. Invalid rows fail safely into an errors list; unknown data
tiers collapse DOWNWARD to synthetic; < 10 rows reads
`require_more_data`. The mission's worked example imports exactly:
alpha +0.16, prediction error 0.02, expiry accuracy 13d.

**Streak audit — streak is not edge.** `audit_streak` decomposes a run
of resolved results: `streak_reliability = attributed wins / wins`
(a win counts as attributed only with a named mechanism),
`overconfidence_gap = stated confidence − win rate`, `hot_hand_risk =
trailing-streak share × (1 − reliability) + overconfidence`. Causal
confidence is capped by BOTH the realized record and the data tier
(synthetic 0.40 / backtest 0.60 / empirical 0.90): three eyes-closed
wins on fixtures yield causal confidence ≤ 0.40 with
`WINS_WITHOUT_ATTRIBUTION` + `HOT_HAND_RISK` — tested. The bridge
`streak_inputs_from_outcomes` feeds imported outcomes straight in.

## Risk Convergence — the doubt committee (`src/simulator/risk_convergence.py`)

The system grew eleven layers that can each raise warn-only findings —
signal redundancy, challenged overrides, calibration risk, fragile
verdicts, marginal expiry clocks, over-hedges, fake-exponential
ceilings, loaded dice. Each warned alone; none could see the others. A
thesis carrying five sub-threshold doubts sailed to buy_candidate
because no SINGLE gate fired: death by a thousand warns.

The committee convenes them, with the signal refiner's doctrine turned
inward — **doubts cluster like signals do; count root causes, not
echoes**:

* findings are grouped into root-cause families (`evidence_quality`,
  `integrity_gaming`, `calibration`, `structural_fragility`,
  `adaptation_pressure`, `timing_decay`); echoes within a family count
  ONCE (two integrity findings are one disease, not two);
* families a hard gate already adjudicated are excluded — no double
  jeopardy (an `EDGE_EXHAUSTED` cap already priced the crowding-side
  doubts);
* informational codes (`OPPONENT_SELF_FED`, `CONSENT_EVIDENCE_*`,
  `LIVE_UNDERPRICED_ACCELERATION`) are never doubts;
* the convergence rule, conservative-only:

```text
1 independent family   -> a question, not a verdict (warn only)
2 independent families -> cap at active_watch
3+ independent families -> cap at watchlist   (RISK_CONVERGENCE_CAP)
```

No single doubt was disqualifying — but independent doubts that arrive
together are not independent events for the thesis. The committee's
minutes (`result["risk_convergence"]`: findings with sources, families,
suppressed echo count, adjudicated exclusions, cap) ship with every
evaluation; with zero findings it reports itself idle. Worked example
(tested end-to-end): redundant backlog echoes + a challenged optimistic
override + a fragile golden lifecycle = three families → watchlist,
and the advisory router sees the post-cap state. ADVISORY_ONLY: the
committee can only ever LOWER a verdict.

## Limitations (honest)

* Trait scores, channel impacts, and probabilities the engines do not
  compute remain caller-supplied research inputs. The self-feed layer
  closes this gap only for the opponent section, and its derived values
  inherit the payload's own physics inputs — internally consistent, not
  independently sourced.
* The calibration ledger's resolution inputs (realized edge, actual
  edge death, K realized, convergence) must come from the operator or
  a future outcome-ingestion path; today's records are synthetic
  fixtures and are labeled as such everywhere they appear.
* Decomposed ceilings, uncertainty bands, and evidence quality are
  caller-judged; the outcome importer accepts whatever the operator
  resolves and can only label its tier honestly — it cannot verify
  provenance.
* Carrying capacity is a normalized proxy from caller-judged TAM
  evidence, not a fitted market-size model; the expiry clock inherits
  tyre half-life constants, which are doctrine-derived. Arbitrage
  convergence probabilities and hedge exposures are research judgements
  the engine structures, never sources.
* The counterfactual audit stresses the payload it was given; it cannot
  detect evidence the caller withheld (it can only show which withheld
  evidence WOULD have mattered). Its risk numbers are doctrine-derived
  heuristics on synthetic/fixture-tier data.
* Weights, bands, and thresholds are doctrine-derived, not empirically
  calibrated (no labeled outcome data exists).
* Node classification is deterministic trait matching, not learned; the
  unclassified guard limits but does not eliminate metaphor overfit.
* Verdict labels are analytical categories. ADVISORY_ONLY, no execution,
  human judgement required.
