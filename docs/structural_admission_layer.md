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
