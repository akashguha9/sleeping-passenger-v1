# The Plumbing Alpha Case Study

Advisory-only. Not financial advice. No trade execution. All node
parameters below are illustrative framework inputs hardcoded in
`src/alpha/plumbing_case_study.py` — a deterministic offline
demonstrator, not researched financial estimates and not a stock
recommendation.

## Thesis

Humans need water. Homes require showers, sinks, toilets, pipes,
valves, drainage, repair, tools, distribution, and maintenance.
Plumbing is therefore a long-half-life residual-utility system:

```text
Durable Demand = Human Necessity × Frequency × Failure Cost
```

But "plumbing won't go away, therefore buy plumbing" is a model
breakdown: need persistence does not say who captures profit. The alpha
is not in "plumbing"; it is in the node that captures the leak.

## Value-chain decomposition

```text
water need → plumbing systems → raw materials → pipes → valves →
fittings → faucets → sinks/showers/toilets → fixing tape/sealants →
wrenches/tools → plumbers/contractors → distributors/hardware stores →
smart leak sensors → water meters → insurance/water-damage prevention
```

Each node is scored with:

```text
Node Attractiveness =
  (Necessity × Urgency × PricingPower × RepeatDemand × BottleneckStrength)
  / (1 + CommoditizationRisk + InputCostRisk)
```

## Conceptual node verdicts

| Node | Layer reading |
|---|---|
| Raw materials | Real demand but commodity pricing |
| Pipes | Permanent demand but possible commoditization |
| Valves | Control-node importance and failure-cost relevance |
| Fittings | High-count repeat component |
| Faucets | Interface layer with aesthetic premium |
| Sinks/showers/toilets | Fixture layer tied to renovation cycles |
| Fixing tape/sealants | Emergency consumable layer |
| Wrenches/tools | Enablement layer with professional trust |
| Plumbers/contractors | Labour scarcity and urgency pricing |
| Distributors/hardware stores | Inventory and access power |
| Smart leak sensors | Prevention/data layer and optional growth (optionality sidecar) |
| Water meters | Measurement layer with mandated replacement cycles |
| Insurance/water damage | Failure-cost monetization layer |

With the illustrative parameters, the ranking puts
**plumbers/contractors** (urgency pricing + labour bottleneck) and
**distributors** (access power + repeat demand) on top, and
**raw materials / pipes** (commoditization) at the bottom — the
framework's expected shape.

## Framework outputs (deterministic)

Produced by `build_plumbing_case_study()` and served at
`GET /alpha/case-studies/plumbing`:

1. **Casino vs food-chain**: `food_chain_heavy` — negligible meme
   energy, strong recurring economics.
2. **Half-life**: `human_necessity` class, decades-scale `t_1/2`
   (`S(t) = S0·e^(−λt)`, `t_1/2 = ln(2)/λ`).
3. **Residual utility**: high score with positive alpha proxy
   (`alpha_proxy ≈ U_residual − P_market`) — the core job ("move clean
   water in and waste water out") survives every stripped layer.
4. **Embedded proof**: `substrate` — plumbing companies are structurally
   built around the theme; the evidence (revenue segments, audited
   financials, shipped product) is the business, not a badge.
5. **Opportunity score (evidence-weighted v2)**: aggregated via
   `clamp(positive_core × (1 − penalty_core/100), 0, 100)` with
   confidence, trap flags, and why-not-higher/lower explanations; the
   verdict lands at `deep_research` — partly because narrative velocity
   and prediction-market confirmation are neutral stubs, and partly
   because the engine caps every verdict at `deep_research` until the
   replay harness provides outcome-backed `calibration_support`.
6. **Advisory containers per node**: each node gets an advisory-only
   container recommendation (watchlist / deep_research / …), never an
   instruction to trade.
7. **Value-chain graph** (`value_chain_graph` key): the same 13 nodes
   with explicit parents/children, captures-value-from and
   passes-cost-to edges, plus failure-cost and replacement-cycle math —
   insurance monetizes failure cost (95/100), plumbers monetize urgency
   and labour scarcity, raw materials stay commodity-priced.

## v3: the full intelligence stack

`build_plumbing_case_study_v3()` (served by the API and dashboard) runs
the complete pipeline — narrative snapshot fixture → prediction-market
stub → filing excerpt with negation-guarded parsing → triangulation →
journal-replay calibration state → evidence-weighted opportunity v2 →
alpha autopsy — and profiles three candidate nodes:

| Node | Residual class | Shape |
|---|---|---|
| Plumbers/contractors | apex_necessity | urgency + failure cost; fragmented local labour limits scalability |
| Valves | apex_necessity | bottleneck with industrial scalability; low-end commoditization pressure |
| Smart leak sensors | durable_utility | stronger narrative/catalyst and optionality; adoption and proof risk |

Under the isolated test journal, calibration_support is 0 and every
profile verdict honestly caps at research grade — position-candidate
verdicts unlock only when real reconciled outcomes flow through the
journal-to-replay bridge.

## What this case study is for

It exercises every framework module end-to-end with zero network
access, giving the MVP a deterministic reference answer to:

> Is this market signal only casino noise, or is it attached to
> unavoidable real-world utility, with durable half-life, hard proof,
> a profitable value-chain node, and a still-mispriced opportunity?
