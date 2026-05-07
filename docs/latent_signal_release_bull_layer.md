# Latent Signal Release Bull Layer

Purpose: add a deterministic release, collapse, durability, promotion, and bull-state layer to the MVP diagnostics spine without adding execution authority.

Core rules:
- Detection != Admission
- Cluster != Validation
- CollapseAnalysis != TradeSignal
- Promotion != Execution
- InvestableSignal = Detection * CollapseCoherence * Durability * ExecutionSurvivability * PolicyPermission

State machine:
- `MIURA`: raw dispersed detection
- `COLLAPSE_ANALYSIS`: controlled clustering only
- `MURCIELAGO`: durability validation
- `AVENTADOR`: promoted actionable candidate
- `GALLARDO`: execution-discipline ready, still human review only
- `ISLERO`: shock override
- `DIABLO`: chaos/policy veto
- `HURACAN`: fast-track review only

Key formulas implemented:

```text
ReleasePressure = Sum(Signal_i * Weight_i * Persistence_i * SourceQuality_i)

TriggerStrength =
0.30 * EventProximity
+ 0.25 * NarrativeAcceleration
+ 0.20 * PriceMoveIntensity
+ 0.15 * PredictionMarketDelta
+ 0.10 * SourceBurst

SignalTexture = Confidence * Persistence / max(Noise, epsilon)

OpportunityValue(t) = InitialEdge * exp(-DecayRate * t)

ValidationBuffer =
SourceDiversity
+ Persistence
+ CounterSignalResistance
+ MetadataClarity
- EchoChamberPenalty

SeparationStrength = MetadataClarity * SourceIndependence * ThemeDistance

FalseConvictionRisk = ClusterDensity / max(SourceIndependence, epsilon)

SignalZeta =
0.25 * Confidence
+ 0.30 * ValidationDepth
+ 0.25 * SourceDiversity
+ 0.20 * Persistence
- 0.20 * EchoChamberPenalty
- 0.15 * CircularCitationPenalty
- 0.15 * SameNarrativeOriginPenalty

ShockScore =
0.30 * VolatilityDelta
+ 0.25 * NewsIntensity
+ 0.20 * LiquidityStress
+ 0.15 * EventSurprise
+ 0.10 * SpreadExpansion

CollapseCoherence =
ThemeSimilarity
* SourceDiversity
* Persistence
* CounterSignalSurvival

DurableCluster =
CollapseCoherence
* StressSurvival
* SourceDiversity
* Persistence
* SignalZeta

ExecutionQuality =
PlanClarity
* RiskControl
* InvalidationClarity
* ExitDiscipline
* ReviewDiscipline
```

Config:
- `config/latent_signal_release_bull_config.json`

Runtime artifacts:
- `runtime/latent_signal_release_report.json`
- `runtime/signal_texture_report.json`
- `runtime/opportunity_half_life_report.json`
- `runtime/validation_buffer_report.json`
- `runtime/signal_zeta_report.json`
- `runtime/false_conviction_report.json`
- `runtime/collapse_analysis_report.json`
- `runtime/murcielago_durability_report.json`
- `runtime/aventador_promotion_report.json`
- `runtime/gallardo_execution_report.json`
- `runtime/bull_state_report.json`
- `runtime/bull_transition_log.json`

Fallback behavior:
- uses repo-native runtime proxies when dedicated live inputs do not exist
- stamps outputs with `data_quality=synthetic_or_runtime_fallback`
- never grants automatic execution authority
