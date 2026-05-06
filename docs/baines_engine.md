# BAINES Engine

`BAINES_ENGINE` is a passive classification layer for bargain, under-attended,
misclassified assets and signals. It sits between raw detection and durability
validation:

`Raw Signal -> Signal Conversion Monitor -> BAINES_ENGINE -> Murcielago Durability Validator -> Aventador Promotion Gate`

It never places trades, never overrides policy, and never bypasses chaos, risk,
durability, or operator-state constraints.

## Core Formula

```text
BainesScore =
    0.22 * RoleMismatchScore
  + 0.18 * MultiChannelScore
  + 0.15 * AttentionDiscount
  + 0.18 * RepeatabilityScore
  + 0.17 * DurabilityScore
  + 0.10 * CostEfficiencyScore
  - 0.08 * VolatilityPenalty
  - 0.07 * LiquidityPenalty
  - 0.10 * RealityGapPenalty
```

All scores are clamped to `[0.0, 1.0]`.

Supporting expressions:

```text
RoleMismatchScore = OutputPercentile - PriceExpectationPercentile
AttentionDiscount = 1 - AttentionScore
MultiChannelScore = sum(channel_scores) / 3
RepeatabilityScore = Persistence * Stability * HistoricalConversion
DurabilityScore = PerformanceAfterStress / max(PerformanceBeforeStress, epsilon)
BPM = ValidatedOutputScore / max(RiskAdjustedCost, epsilon)
DurableSignal = Signal * Repeatability * StressSurvival
UniversalBainesScore =
    ClassAdjusted(Output / Cost) * AttentionDiscount * DurabilityScore
```

## Thresholds

- `theta_baines = 0.70`
- `theta_repeatability = 0.60`
- `theta_durability = 0.65`
- `theta_multichannel = 0.55`
- `theta_attention_max = 0.70`
- `theta_role_mismatch = 0.20`

## Classification Rules

- `BAINES_VETOED_POLICY`: upstream policy veto active
- `BAINES_VETOED_CHAOS`: chaos veto active
- `BAINES_REJECTED`: score below `0.50`
- `BAINES_WATCHLIST`: score in `[0.50, 0.70)`
- `BAINES_VALIDATION_REQUIRED`: score above threshold but durability or repeatability still insufficient
- `BAINES_DURABLE_CANDIDATE`: score and supporting thresholds pass
- `BAINES_PROMOTION_ELIGIBLE`: only if downstream validation explicitly confirms promotion readiness

## Diagnostics Surface

The health report exposes:

- `baines_engine_available`
- `baines_engine_state`
- `baines_candidates_detected`
- `baines_durable_candidates`
- `baines_policy_vetoed`
- `baines_chaos_vetoed`
- `top_baines_candidate`
- `top_baines_score`

Each candidate also emits a `formula_trace` so operators can inspect the
scoring path without turning the engine into an action authority.
