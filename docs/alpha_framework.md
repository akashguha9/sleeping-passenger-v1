# Alpha Framework — Reality-First Signal Separation

Advisory-only. Not financial advice. No trade execution. No broker
connections. The framework classifies and explains; humans decide.

## Core philosophy

Markets are casinos sitting on top of real-world food chains. Alpha
comes from identifying which narratives are backed by unavoidable
residual utility, then finding the quiet value-chain node that captures
the money before the obvious ticker becomes expensive.

The pipeline moves from `headline → ticker → emotional buy/no-buy` to:

```text
human need / narrative shock
→ upstream/downstream value-chain map
→ narrative velocity capture
→ prediction-market / event-probability confirmation
→ filing / hard-proof verification
→ casino vs food-chain separation
→ half-life estimation
→ residual-utility scoring
→ valuation/risk filter
→ advisory-only verdict
```

## Modules (`src/alpha/`)

### A. Casino vs food-chain classifier (`casino_food_chain.py`)

The casino layer is hype, speculation, social attention, aesthetics,
price momentum, meme energy, influencer narrative, options/volume
spikes. The food-chain layer is revenue, cash flow, customer demand,
suppliers, regulation, repeat need, economic necessity.

Both layers are scored 0–100 with a weighted sigmoid over bounded
inputs; missing inputs default to neutral 0.5 and are reported in
`missing_inputs`. The gap classifies the signal as `casino_heavy`,
`food_chain_heavy`, `balanced`, or `weak_signal`.

### B. Residual utility engine (`residual_utility.py`)

Residual utility is what remains after the story dies:

```text
U_residual = U_total − U_narrative − U_aesthetic − U_status − U_speculative
alpha_proxy ≈ U_residual − P_market
```

Scoring encodes: does this solve a recurring non-optional problem; would
customers stay without hype; is it cheaper/faster/safer/more necessary;
does demand repeat without promotion; does failure create urgency; is it
underpriced because it looks boring? (Ryanair is the stripped utility
layer of aviation; plumbing is civilization-level residual utility.)

### C. Half-life signal decay engine (`half_life.py`)

```text
S(t) = S0·e^(−λt)
t_1/2 = ln(2)/λ
```

Baseline half-lives per signal type (viral post: days → human necessity:
decades), stretched or shrunk within a bounded 0.5×–1.5× multiplier by
source quality, proof strength, and recurrence. TODO: calibrate
empirically once outcome data accumulates.

### D. Embedded proof detector (`embedded_proof.py`)

Separates **simulated flavour** (claims with weak evidence), **embedded
proof** (filings/contracts/products show real exposure — fruit pieces
are receipts), and **substrate** (the company is structurally built
around the theme — the yogurt *is* the base).

```text
proof_density = verified_evidence / max(1, narrative_claims)
```

Evidence kinds are weighted by how hard they are to fake (revenue
segments and audited financials > press releases and logos). Embedded
proof is evidence, not essence: strip it and re-score residual utility.

### E. Porter value-chain mapper (`value_chain.py`)

A broad thesis is not an investment until mapped to profit nodes:

```text
Node Attractiveness =
  (Necessity × Urgency × PricingPower × RepeatDemand × BottleneckStrength)
  / (1 + CommoditizationRisk + InputCostRisk)
```

(implemented as a geometric mean of the numerator factors so one dead
dimension collapses the node while the scale stays 0–100).

### F. Classic benchmark layer (`classic_benchmark.py`)

Classics are control samples: vanilla (ice cream), Margherita (pizza),
cash/card/UPI (payments), free cash flow (stocks), boring plumbing
(infrastructure).

```text
benchmark_edge = candidate_score − classic_benchmark_score
```

If novelty does not beat the classic, it is likely decoration.

### G. Compatibility / sequencing engine (`compatibility.py`)

Two apex assets can clash (vanilla on Margherita; one concentrated
semiconductor supply-chain bet). Quality is local; composition is global:

```text
Portfolio Value = Σ(w_i·Q_i) + Σ(w_i·w_j·C_ij)
```

with pairwise compatibility `C_ij ∈ [−1, 1]`: synergy, independence, or
interference/concentration. Outputs overlap risk and a sequencing
recommendation (`core_now | watch_later | hedge | avoid_stack | event_only`).

### H. Container / interface engine (`container.py`)

The same signal needs the right container — a cup is a controlled
experiment, a cone is commitment, a cup with a cone biscuit is stable
core plus optional upside. Advisory containers:

```text
ignore | watchlist | deep_research | event_trade_only |
small_position_candidate | core_candidate | avoid_trap | hedge_candidate
```

Deterministic rules over conviction, volatility, half-life, proof, and
valuation risk. Advisory classification only — never execution.

### I. Opportunity score aggregator (`opportunity.py`)

```text
Opportunity Score =
  (N × P × E × B × H × R_u × F)
  / (1 + V + R + C + D)
```

N narrative velocity, P probability confirmation, E embedded proof,
B node strength, H half-life, R_u residual utility, F food-chain score;
risks: V valuation, R regulatory/operational, C commoditization,
D casino distortion. Positive factors fold via geometric mean (a dead
factor sinks the score); missing components default to neutral 50 and
are reported. Output includes the verdict, drivers, and the disclaimer.

### Blind-test logic

The scorers consume anonymized facts only: no module accepts a ticker,
brand, founder, or sector-hype field as a scoring input. That is the
blind-test discipline — `True Signal = Observed Preference − Narrative
Bias` — applied structurally rather than as a separate scrubbing pass.

## Signal scaffolding (`signals.py`)

Offline-safe dataclasses define the ingestion contract:
`PredictionMarketSignal` (market vs model probability and edge),
`FilingSignal` (claims vs verified evidence), `NarrativeSignal`
(mention velocity / sentiment / source quality), `ValueChainSignal`.
`stub_*` factories return deterministic fixtures with `source =
"manual_stub"` so nothing offline can masquerade as live data. No live
Kalshi/Polymarket calls are made by this package.

Phase 2 wired the first two contracts to real producers:
`src/alpha/adapters/prediction_market_adapter.py` converts
Kalshi/Polymarket snapshots (from the read-only ingestion clients) into
`PredictionMarketSignal`s with bid/ask-mid probabilities and
spread-aware confidence, and `src/alpha/filing_parser.py` builds
`FilingSignal`s from parsed filing excerpts with line-level evidence
lineage.

## API surface (read-only, advisory-only)

```text
GET  /alpha/case-studies/plumbing          (v3 full stack)
POST /alpha/score                          (evidence-weighted v2)
POST /alpha/value-chain/map
POST /alpha/signal/decay
POST /alpha/filing/parse                   (Phase 2; negation guard in Phase 3)
POST /alpha/prediction-market/normalize    (Phase 2)
POST /alpha/replay/evaluate                (Phase 2)
POST /alpha/replay/from-journal            (Phase 3)
POST /alpha/autopsy                        (Phase 3)
```

Phase 3 ("final boss") documentation: `docs/alpha_framework_final_boss.md`,
`docs/alpha_journal_replay_bridge.md`,
`docs/alpha_triangulation_and_autopsy.md`.

All routes are pure deterministic computations over caller-supplied (or
hardcoded case-study) inputs: no DB writes, no network calls, the same
advisory stamps and token gating as the rest of the API.  See
`docs/alpha_framework_phase2.md` for the evidence-weighted scoring
(trap flags, why-not explanations, confidence, calibration gating),
`docs/alpha_filing_signal_parser.md` for filing evidence lineage, and
`docs/alpha_replay_and_calibration.md` for the replay harness.

## Dashboard

`src/dashboard/alpha_framework_view.py` renders the framework summary,
the plumbing value-chain table, node scores, opportunity components,
advisory verdicts, missing inputs, and the disclaimer as a section of
the Streamlit dashboard.

## Limitations

- All case-study node parameters are illustrative framework inputs, not
  researched financial estimates.
- Half-life multipliers, layer weights, and verdict thresholds are
  uncalibrated priors until outcome data exists.
- Prediction-market and filings ingestion are stubs; see TODOs in
  `src/alpha/signals.py`.
- Nothing in this framework places trades, sizes positions, or implies
  any expected or certain return.
