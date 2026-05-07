# False Negative Casino Monopoly Layer

Purpose: add a conservative advisory layer that audits hidden upside, role misfit, deception, chaos, staged restraint, and recurrence without creating any execution authority. Detection is not admission. Policy veto, chaos, heat, and existing risk controls still outrank every score in this layer.

Module list:
- `scripts/false_negative_casino_monopoly_layer.py`

Core formulas:
- `StabilizerScore = 0.20*coverage + 0.20*availability + 0.20*continuity + 0.20*low_error_rate + 0.20*friction_reduction`
- `RoleMisfitRisk = CapabilityStrength - CurrentRoleFit`
- `FalseNegativeRisk = role_misfit + context_misfit + metric_blindness + structural_value_unmeasured + asymmetric_upside`
- `BlindSpotRisk = 1 - DetectionCoverage`
- `DoubleBlind = Misperception * Overconfidence`
- `FoodChainRank = 0.25*information_advantage + 0.20*capital_strength + 0.20*timing_advantage + 0.20*discipline + 0.15*rule_awareness`
- `ClusterPower = asset_count * synergy * control * persistence * cashflow_potential`
- `ScalePermission = validation * control * cashflow_potential * durability * execution_survivability`
- `ReEntryScore = signal_strength + stability + probe_success + follow_through - chaos - deception_risk - false_break_risk`
- `FalseBreakRisk = initial_signal_strength - follow_through + deception_risk + chaos + low_participation_quality`
- `ShockScore = surprise * impact * rule_change`
- `CycleStrength = 0.35*gcd_consistency + 0.25*low_interval_variance + 0.20*repeated_interval_ratio + 0.20*modular_consistency`
- `InvestableSignal = Detection * Validation * Durability * ExecutionSurvivability * TableQuality * TruthProbability * RoleFit * ClusterPower - ChaosPenalty - DeceptionPenalty - FalseBreakPenalty - OverconfidencePenalty`

State hierarchy:
- `policy veto > chaos/risk/heat guards > joker/shock > jail mode > durability/validation > momentum > raw signal`
- `JAIL -> PROBE -> CONFIRM -> DEPLOY`
- No direct jump from `JAIL` to `DEPLOY`

Policy-veto hierarchy:
- If `policy_veto=true`, then `can_deploy_capital=false` and `allow_new_risk=false`
- This layer can lower confidence, force restraint, and request recheck
- This layer cannot authorize execution, override policy, or bypass chaos locks

Examples:
- Sean Longstaff: low visible output with high continuity and friction reduction becomes `GLUE_ASSET`
- Joelinton: low current role fit with stronger alternate role becomes `MISCAST` or `SEVERE_MISCAST`
- Monopoly jail: `Jail Mode` is strategic no-new-risk restraint, not inactivity theater
- Joker: shock override forces reclassification and can escalate to `MODEL_RESET_REQUIRED`
- Diablo: chaos veto outranks momentum and forces `DIABLO`
- GCD recurrence: repeated intervals strengthen rhythm detection without promoting weak evidence
