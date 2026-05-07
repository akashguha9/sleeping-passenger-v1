# Pre-Execution Scan Engine

`scripts/pre_execution_scan_engine.py` adds a Rodri-style pre-execution intelligence layer to the MVP diagnostics pipeline.

## Purpose

The real decision begins before the ball arrives.

This layer maps the environment before action:

- scan quality
- mini-map quality
- pressure direction and trap formation
- board control
- optionality
- turn safety
- hidden preconditions
- timing viability

It is diagnostic and admission logic only. It does not execute trades, place orders, manage wallets, or deploy capital.

## Doctrine

- Elite execution begins before the event arrives.
- Detection is not execution.
- Shoulder checks are environmental telemetry.
- Surprise is an execution tax.
- Board control beats perfect prediction.
- Hidden preconditions cap visible execution quality.
- `DIABLO` chaos veto and `ISLERO` shock override all scan outputs.
- `HURACAN` fast-track cannot bypass scan, validation, board-control, policy, or chaos gates.

## Governing Formula

- `PreExecutionPermission = PolicyPass * ChaosPass * ShockPass * ScanQuality * MiniMapQuality * PressureAwareness * BoardControl * Optionality * TimingViability * Validation * Durability * ExecutionReadiness`

## Core Formulas

- `PreScanQuality = 0.25 * ScanFrequencyEffect + 0.30 * ScanAccuracy + 0.25 * ContextFreshness + 0.20 * ScanRecencyScore`
- `AdjustedSurpriseRisk = RawSurpriseRisk * (1 - 0.35 * ScanFrequencyEffect)`
- `MiniMapQuality = 0.25 * ActorCoverage + 0.25 * SpatialCoverage + 0.25 * ExitLaneQuality + 0.25 * CollisionSafety`
- `MiniMapGeometric = geometric(ActorCoverage, SpatialCoverage, ExitLaneQuality, CollisionSafety)`
- `BoardControlScore = 0.45 * CriticalSquareCoverage + 0.25 * (1 - ExposureRatio) + 0.30 * ContainmentStrength`
- `OptionalityScore = 0.35 * SafeActionRatio + 0.25 * BestActionQuality + 0.20 * FallbackQuality + 0.20 * RecycleQuality`
- `HiddenPreconditionsScore = geometric(PreScanQuality, MiniMapQuality, BoardControl, Optionality, PressureAwareness)`
- `ExecutionCeiling = HiddenPreconditionsScore * ExecutionReadiness`
- `FinalPreExecutionScore = min(weighted_geometric_final_raw, ExecutionCeiling + 0.05)`
- `FailureRisk = clamp01(PressureSpeed - AwarenessSpeed + 0.50)`
- `UnsafeActionRisk = RawSignalStrength * (1 - HiddenPreconditionsScore) * (1 - ValidationScore)`

## Report Output

Runtime artifact:

- `runtime/pre_execution_scan_report.json`

Compact health-report fields:

- `pre_execution_scan_state`
- `pre_execution_scan_readiness`
- `pre_execution_pressure_state`
- `pre_execution_turn_decision`
- `pre_execution_surprise_band`
- `pre_execution_board_control_state`
- `pre_execution_decision`
- `pre_execution_archetype`
- `pre_execution_score`
- `pre_execution_action_permission`
- `pre_execution_report_path`

CLI summary line:

- `pre_execution_scan=state=..., readiness=..., pressure=..., turn=..., decision=..., score=...`

## Archetypes

- `MIURA_BLIND_RAW_SIGNAL`
- `MURCIELAGO_MAPPED_UNDER_PRESSURE`
- `AVENTADOR_PREPARED_ACTIONABLE`
- `GALLARDO_CLEAN_EXECUTION_READY`
- `ISLERO_SHOCK_REMAP`
- `DIABLO_CHAOS_NO_TURN`
- `HURACAN_FAST_TRACK_WITH_SCAN_FLOOR`

## Limitations

- Inputs are derived from existing seeded or runtime-safe signal rows unless richer telemetry is available.
- The layer is deterministic and offline-safe.
- No live trading, broker integration, wallet handling, or private-key logic is added.
