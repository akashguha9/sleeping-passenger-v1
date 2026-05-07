# Chess Archetype Decision Layer

This layer adds deterministic chess-style decision review to the MVP pipeline. It does not create live execution authority. It classifies state, scores archetype fit, applies vetoes, checks hidden risk, validates durability, estimates multi-order consequences, and emits review-ready diagnostics.

Core formulas:

- `MVP Decision = State Classification × Archetype Fit × Multi-Order Consequence Quality × Veto Clearance`
- `Investable Signal = Detection × Positional Justification × Hidden Risk Clearance × Durability × Precision × Initiative × Execution Survivability × Multi-Order Consequence Quality − Chaos Cost − Maintenance Cost − Policy Risk − Operator Misfit`
- `FastTrack = MomentumSpike × MinimumValidation × RiskCap × Freshness × RepricingLag − CollapseRisk`
- `DurableSignal = Signal × StressSurvival × CounterplayReduction × Persistence × ConfirmationDepth`
- `ActionableSignal = ValidationDepth × Initiative × TimingWindow × Feasibility × Asymmetry − ResidualRisk`
- `ActionQuality = O1 + O2 + O3 + O4 − CollapseRisk − MaintenanceCost − PolicyRisk − OperatorMisfit`

Priority hierarchy:

1. Policy veto
2. Diablo chaos / heat / risk guards
3. Hidden risk / prophylaxis
4. Durability validation
5. Positional justification
6. Precision validation
7. Initiative promotion
8. Tempo fast-track
9. Execution / conversion
10. Review / learning

Runtime artifact:

- `runtime/chess_archetype_report.json`

Safety:

- diagnostic and simulation-only
- no live trading or brokerage behavior
- policy veto remains highest priority
