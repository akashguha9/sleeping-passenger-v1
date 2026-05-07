# Structural Admission Layer

Purpose: add a deterministic bottleneck admission layer between raw signal detection/tagging and downstream recommendation surfaces. This layer classifies, scores, rejects, explains, and reports only. It does not execute, place orders, or override policy.

Pipeline placement:

`Raw Signal Detection -> Signal Conversion / Tagging -> Structural Admission Layer -> Validation / Durability / Policy / Risk -> Action Report -> Health Report`

Core formulas preserved in code comments and logic:

```text
SystemAdmission = Utility * Structure * Readability * ContextFit
InterestingSignal != DeployableSignal
OwnershipValue = Attraction * UseCase * IdentityFit
ToolPerformance = f(Environment, Pressure, Oxygen, Constraint)
Failure = BrokenAssumption * EnvironmentShift
SignalBurnProfile = IgnitionSpeed * Duration * Stability * EnvironmentResistance
CorrectInference = CorrectVariable * CorrectInstrument
DecisionTrust = Observability * Auditability * Explainability
DecisionQuality = SignalQuality * OperatorClarity * EnvironmentQuality
AlignmentScore = Freshness * ExternalConfirmation * RegimeConsistency
ToolPower = PrimitiveUnderstanding * InterfaceLeverage
SignalMeaning = NodeValue * RelationshipStrength
SignalValidity = FinalState * TransitionQuality * ResolutionStrength
ToolFit = TaskContext * SpecializationMatch
```

Final admission logic:

```text
MVPDecisionQuality =
DomainFit
* EnvironmentFit
* MaterialDurability
* SignalHarmony
* TransitionQuality
* ValidationStrength
* TrustObservability
* OperatorClarity
* RealityAlignment
* PrimitiveUnderstanding
* UseCaseFit

AdmissionScore = min(
DomainFit,
EnvironmentFit,
MaterialDurability,
SignalHarmony,
TransitionQuality,
ValidationStrength,
TrustObservability,
OperatorClarity,
RealityAlignment,
PrimitiveUnderstanding,
UseCaseFit
)
```

Diagnostic score is weighted for explanation only. Admission still uses bottleneck logic.

Main components:
- Design Integrity Gate
- Domain-Instrument Mapper
- Environment / Regime Detector
- Engine Selector
- Signal Materiality Analyzer
- Burn Profile Estimator
- Signal Graph Engine
- Harmony / Dissonance Engine
- Progression Validator
- Gamaka Transition Engine
- Trapdoor Detector
- Trust Gate
- Operator Clarity Gate
- Reality Anchor Engine
- Primitive Competence Check
- Use-Case Fit Engine

Important doctrine:
- detection is not execution
- one weak layer can invalidate admission
- policy veto and chaos veto still outrank this layer
- fallback engines increase caution; they do not justify more risk

Current limitation:
- repo-native proxy inputs are used where the MVP does not yet expose a dedicated live source for a component
- this remains offline-first and advisory-only

Buyer and execution-fit extension:

```text
MVPDecisionQuality =
DomainFit
* EnvironmentFit
* MaterialDurability
* SignalHarmony
* TransitionQuality
* ValidationStrength
* TrustObservability
* OperatorClarity
* RealityAlignment
* PrimitiveUnderstanding
* UseCaseFit
* BuyerAlignment
* ExecutionSurvivability

AdmissionScore = min(
DomainFit,
EnvironmentFit,
MaterialDurability,
SignalHarmony,
TransitionQuality,
ValidationStrength,
TrustObservability,
OperatorClarity,
RealityAlignment,
PrimitiveUnderstanding,
UseCaseFit,
BuyerAlignment,
ExecutionSurvivability
)
```

Additional formulas now implemented:

```text
AssetValue = BuyerFit * UseCaseFit * TimingFit
DecisionTrust = Observability * Auditability * Explainability
SurvivalScore = PerformanceAfterStress / PerformanceBeforeStress
ValidatedSignal = SourceCredibility * ConfirmationDepth * Consistency
PricePressure = SignalForce * TransmissionPath * BuyerSensitivity
ExpectedMove = Sum(BuyerClass_i * ProbabilityAction_i * CapitalWeight_i)
InvestableSignal = Detection * Validation * Durability * BuyerAlignment * ExecutionSurvivability
```

Additional components:
- Buyer Type Engine
- Evaluation Model Router
- Source Credibility vs Validation Gate
- Peak Moment Detector
- Anchor Feature Classifier
- Behavioral Skin Layer
- Durability / Maintenance Cost Gate
- Surface vs Structure Classifier
- Force Flow / Pressure Transmission Engine
- Actor Response Prediction Engine
- Bull archetype routing

Runtime shape:
- existing compatibility remains under `structural_admission_state`
- richer additive state is exposed under `mvp_admission_layer`
- operator-facing next-step guidance is exposed under `operator_summary`

Threshold configuration:
- `config/structural_admission_config.json`

Extended doctrine:
- attraction is not admission
- credibility is not validation
- peak moment is not total quality
- cosmetic recovery is not structural recovery
- generalists explore; specialists validate
- policy veto and chaos veto still outrank every admission state
