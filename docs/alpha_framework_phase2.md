# Alpha Framework — Phase 2: Evidence-Linked Intelligence

Advisory-only. Not financial advice. No trade execution. Scores and
verdicts are research-classification outputs, never trading
instructions.

Phase 1 built the deterministic framework with mostly neutral stubs.
Phase 2 converts the stubs into evidence-linked, replayable components:

| Upgrade | Module | What changed |
|---|---|---|
| A | `src/alpha/adapters/prediction_market_adapter.py` | Kalshi/Polymarket/manual quotes → normalized `PredictionMarketSignal` |
| B | `src/alpha/filing_parser.py` | Filing excerpts → evidence with lineage and hardness weights |
| C | `src/alpha/opportunity.py` (`aggregate_opportunity_score_v2`) | Evidence-weighted score, trap flags, why-not explanations, confidence |
| D | `src/alpha/replay.py` | Replayable signal-quality harness (precision@k, Brier, calibration) |
| E | `src/alpha/value_chain_graph.py` | Graph relationships + failure-cost/replacement-cycle math |
| F | API routes + dashboard | `/alpha/filing/parse`, `/alpha/prediction-market/normalize`, `/alpha/replay/evaluate`, richer `/alpha/score`, diagnostics panels |

## A. Prediction-market normalization

```text
p_mid = (bid + ask) / 2            yes_bid derived as 1 − no_ask when absent
spread = ask − bid
edge = p_model − p_market
confidence = 100 × (1 − min(1, spread / spread_cap)) × source_quality
```

Fallback ladder (each step lowers confidence): two-sided quote →
implied probability (×0.70) → last price (×0.55) → neutral 0.5 with
confidence 0 and `missing_inputs += ["market_probability"]`. Source
quality: kalshi 0.90, polymarket 0.80, manual_stub 0.50. The adapter
performs no network I/O — it consumes snapshots already fetched by the
read-only ingestion clients (or their deterministic mock fixtures).

The probability edge feeds only the probability-confirmation component
(`50 + 100 × edge × confidence/100`, clamped 0–100) — an event/catalyst
signal. It never inflates residual utility or food-chain reality.

## B. Filing evidence lineage

Deterministic keyword parsing over excerpt lines (10-K, 10-Q, annual
report, earnings call, investor presentation, manual excerpt). Every
matched item retains lineage: category, claim, evidence text, source
type, hardness weight, confidence, line number, source date.

Hardness weights (how hard the evidence kind is to fake):

```text
audited_revenue_segment 1.00   contract_or_backlog 0.90
cash_flow_statement 0.90       regulatory_approval 0.85
capex_commitment 0.75          risk_disclosure 0.70
earnings_call_claim 0.55       investor_presentation_claim 0.45
marketing_claim 0.25           logo_or_collaboration_claim 0.15
```

scaled by a source-type multiplier (10-K 1.00 → investor presentation
0.45; unknown sources 0.40 and reported in `missing_inputs`).

```text
proof_density        = weighted_verified_evidence / max(1, narrative_claim_count)
embedded_proof_score = 100 × min(1, proof_density)
substrate_score      = 100 × min(1, Σ substrate evidence fractions)
```

Risk categories (risk_disclosure, customer_concentration,
supplier_dependency, litigation_or_regulatory_risk,
going_concern_or_liquidity_risk) are scored separately into
`filing_risk_disclosure_score` and *penalize* opportunity instead of
proving the theme. Marketing-cue lines ("world-class",
"market-leading", …) are counted as claims, never as evidence.

## C. Evidence-weighted opportunity score (v2)

```text
positive_core = geometric_mean(N, P, E, B, H, R_u, F)
penalty_core  = weighted_mean(valuation, regulatory, commoditization,
                              casino_distortion, evidence_gap_risk,
                              filing_risk_disclosure_score)
opportunity_score = clamp(positive_core × (1 − penalty_core / 100), 0, 100)
confidence = weighted_mean(evidence_quality, input_completeness,
                           source_quality, calibration_support,
                           deterministic_replayability)
```

Trap flags (deterministic thresholds): `high_casino_low_food_chain`,
`high_narrative_low_proof`, `short_half_life_high_valuation`,
`strong_theme_weak_node_capture`, `high_probability_edge_low_liquidity`,
`filing_claim_without_hard_evidence`, `risk_disclosure_overhang`,
`overconcentrated_portfolio_exposure`.

Conservatism rules, in order:
1. casino/narrative trap shapes → `avoid_trap`;
2. half-life under 30 days → `event_trade_only`;
3. evidence quality < 40 → verdict capped at `deep_research`;
4. narrative velocity < 30 → capped at `deep_research` (real but
   unnoticed is research, not a position call);
5. **calibration_support < 10 → capped at `deep_research`** — an
   engine with no outcome-backed calibration may research, never size.
   Replay-harness `calibration_support` is the only key that unlocks
   position-candidate verdicts;
6. input completeness < 50% → capped at `watchlist`.

`why_not_higher` / `why_not_lower` enumerate the exact drivers, so a
verdict is always explainable in one read.

## D–F

See `docs/alpha_replay_and_calibration.md` (replay metrics and
calibration limits) and `docs/alpha_filing_signal_parser.md` (parser
details). The value-chain graph adds parents/children/
captures_value_from/passes_cost_to edges plus:

```text
Node Attractiveness =
  100 × normalize(
    Necessity × Urgency × PricingPower × RepeatDemand × BottleneckStrength
    × FailureCost × ReplacementCycle
    /
    (1 + CommoditizationRisk + InputCostRisk + SubstitutionRisk)
  )
```

(geometric mean of the seven positive factors over the risk
denominator). For plumbing: insurance monetizes failure cost,
plumbers monetize urgency + labour scarcity, raw materials stay
commodity-priced — the graph makes the "who captures the leak" answer
explicit.

## Advisory boundary

Every endpoint is a pure computation with the standard advisory stamps;
all POST routes sit behind the strict mutation token gate. Nothing
here connects to a broker, places an order, sizes a position, or
estimates returns. Replay metrics measure historical advisory signal
quality only. Treating any score in this framework as a trading
instruction is a misuse of the system.
