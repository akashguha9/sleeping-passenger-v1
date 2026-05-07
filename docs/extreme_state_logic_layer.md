# Extreme State Logic Layer

This layer formalizes the repo's extreme-state safety logic around conversion failure, silent chaos, symmetry traps, repeatability, and forced termination.

Core formulas implemented:

- `PerformanceCeiling = 0.25*Technique + 0.30*Structure + 0.20*Timing + 0.25*Repeatability`
- `ExecutionEfficiency = SequenceQuality * TimingPrecision * TransferEfficiency * ContactQuality`
- `StructuralAdvantage = 0.30*Access + 0.25*Angle + 0.20*TimingAccess + 0.25*ConstraintReduction`
- `UsableEdge = StructuralAdvantage * Repeatability`
- `Repeatability = SuccessfulRepetitions / max(TotalAttempts, 1)`
- `ConversionProbability = TriggerPresence * TimingWindow * OpponentWeakness`
- `ExecutableEdge = SignalStrength * ConversionTrigger * TimingWindow * ExitClarity`
- `SymmetryScore = 1 - abs(OwnStrength - OpponentCounterStrength)`
- `SilentChaos = 0.35*HighDuration + 0.25*NoTransition + 0.25*RisingCost + 0.15*LowVolatility`
- `LoopRisk = Stability * NoExit * LowTransition`
- `HoldingCost = 0.25*TimeCost + 0.20*MentalCost + 0.30*OpportunityCost + 0.25*RiskCost`

The layer is diagnostic only. It can classify, downgrade, terminate, or reject ideas in the report, but it cannot place trades or bypass policy, chaos, risk, or operator guards.
