# Dynamic Signal Metabolism Layer

This layer treats signals as dynamic inputs rather than static labels. It is a
classification, scoring, guardrail, and explanation surface only. It does not
place trades or override policy.

## Core Idea

```text
TradeOutcome = f(
    SignalRoute,
    ArrivalTiming,
    SignalInteraction,
    SignalTransformation,
    SignalIntensity,
    SignalStability,
    MarketState,
    SystemCompatibility
)
```

Working doctrine:

- Detection is inhalation.
- Validation is metabolism.
- Execution is the effect.
- Do not trade the THC. Check the CBD.

## Main Components

- `classify_signal_route`
- `compute_phase_arrival`
- `classify_signal_stage`
- `score_psychological_chemistry`
- `split_virality_vs_validity`
- `compute_signal_interaction`
- `compute_regime_factor`
- `compute_compatibility`
- `apply_high_intensity_guard`
- `classify_bull_archetype`
- `evaluate_signal_metabolism`
- `build_signal_metabolism_report`

## Key Formulas

```text
SignalEffect = RawSignal * ChannelModifier
PhaseExperience = sum(Input_i * ArrivalTime_i)
TransformedSignal = RawSignal * ProcessingPathway
PostImpact = Intensity * NarrativeDirection * EvidenceStability * MarketState
TruthScore = Evidence * Confirmation * SourceQuality
CombinedEffect = EffectA * EffectB * InteractionCoefficient
AdjustedSignal = RawSignal * StateFactor
Compatibility = Consistency * Familiarity * Stability
DistortionRisk = Intensity / Stability

dynamic_signal_score =
    route_reliability_prior
    * timing_alignment_score
    * transformation_quality_score
    * interaction_quality_score
    * evidence_stability_score
    * regime_factor
    * compatibility_score
    * guard_multiplier
```

Guard multiplier:

- `0.0` for hard block
- `0.4` for delay or confidence reduction
- `1.0` for allow

## Output Fields

Per candidate:

- `signal_route`
- `route_latency_profile`
- `route_reliability_prior`
- `phase_state`
- `timing_delta`
- `signal_stage`
- `priced_risk`
- `intensity_score`
- `narrative_direction_score`
- `evidence_stability_score`
- `virality_score`
- `truth_score`
- `validity_gap`
- `attention_truth_state`
- `interaction_score`
- `interaction_state`
- `regime_factor`
- `compatibility_score`
- `high_intensity_guard_triggered`
- `guard_action`
- `bull_archetype`
- `dynamic_signal_score`

## Runtime Artifact

When runtime writes are enabled, the report is written to:

- `runtime/signal_metabolism_report.json`

## Safety

- Policy veto remains supreme.
- Chaos and risk regime lockouts remain supreme.
- High-intensity low-stability signals are delayed or blocked.
- Virality never substitutes for truth.
