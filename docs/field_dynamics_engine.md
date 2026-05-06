# Field Dynamics Engine

`field_dynamics_engine.py` adds a conservative Gauss / Maxwell / Lorentz layer to the MVP diagnostics spine.

It does not execute trades, bypass policy, or replace the existing Signal Conversion Monitor. It measures field pressure, interaction coherence, and directional readiness so the operator can see whether a signal environment is merely detected or structurally reviewable.

## Doctrine

- Detection is not admission.
- Pressure before validation.
- Interaction before conviction.
- Direction before execution.
- Policy veto outranks field logic.

## Formulas

### Gauss Field Pressure

`WeightedSignal_i = Signal_i × Weight_i × Persistence_i`

`FieldPressure = Σ WeightedSignal_i`

`BoundaryEffect = NetFlow_in - NetFlow_out`

`PressurePersistence = sustained_pressure_periods / observed_periods`

### Maxwell Field Interaction

`Divergence = |ExpectedCoupling - ObservedCoupling|`

`InteractionCoherence = max(0, 1 - DivergenceScore)`

### Lorentz / Fleming Execution Vector

`ExecutionVector = Direction × Magnitude × TimingAlignment`

`ExecutionClarity = DirectionalClarity × AlignmentScore × TimingFit`

### Valid Signal Rate

`ValidSignalRate = F_strength × I_coherence × E_clarity`

Where:

- `F_strength = normalized field pressure`
- `I_coherence = interaction coherence`
- `E_clarity = execution clarity`

### Trade Readiness

`TradeReadiness = FieldPressure × InteractionCoherence × ExecutionClarity × PolicyPermission`

## Runtime Outputs

Top-level health report fields:

- `field_dynamics_engine_available`
- `field_dynamics_engine_state`
- `valid_signal_rate`
- `trade_readiness`
- `field_dynamics_candidate_count`
- `field_dynamics_strong_field_count`
- `field_dynamics_divergent_field_count`
- `field_dynamics_actionable_under_policy_count`
- `field_dynamics_top_asset`
- `field_dynamics_report_path`

Nested dashboard:

- `gauss_maxwell_lorentz_state`
- `gauss_maxwell_lorentz_dashboard`

Runtime artifact:

- `runtime/field_dynamics_report.json`

## Safety

- Policy and chaos vetoes remain supreme.
- Existing SCM logic is preserved.
- The layer only emits advisory readiness and gating metadata.
- No automated execution or order placement is introduced.
