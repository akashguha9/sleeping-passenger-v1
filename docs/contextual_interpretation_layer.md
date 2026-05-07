# Contextual Interpretation Layer

This layer is optional and flag-gated through `run_diagnostics_pipeline.py`.

Core contracts:

- `InterpretedSignal = f(RawSignal, ContextProfile, OperatorLens, Environment)`
- `InterpretationDrift = max(Meaning_i) - min(Meaning_i)`
- `ChaosRisk ∝ InterpretationDrift`
- `ExecutableSignal = Compress(Validate(Interpret(RawSignal, ContextProfile, OperatorLens)))`

When enabled:

1. Raw/runtime-compatible signals receive a `ContextProfile`.
2. Retail, Institution, Momentum, MarketMaker, Contrarian, and Whale lenses interpret the same raw signal.
3. Interpretation drift is scored and can trigger a Diablo-style chaos veto.
4. Downstream review layers receive interpreted payloads with `validation_input_mode=INTERPRETED_PAYLOAD`.
5. Runtime artifacts are written under `runtime/`:
   - `context_profile_report.json`
   - `interpretation_packet_report.json`
   - `interpretation_drift_report.json`
   - `reality_rendering_report.json`
   - `interpretation_failure_log.jsonl`
   - `contextual_interpretation_summary.json`

This layer is diagnostic only. It does not grant live execution, capital deployment, or policy bypass authority.
