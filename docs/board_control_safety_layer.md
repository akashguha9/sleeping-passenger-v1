# Board Control Safety Layer

`scripts/board_control_safety_layer.py` adds a board-aware admission and guardrail layer to the MVP diagnostics pipeline.

## Purpose

This layer does not try to predict more. It checks whether a signal can safely move through the board:

- board control
- critical-square exposure
- weakest-path failure
- local clearance versus global clearance
- hidden execution drift
- baseline violation
- review theater
- operator-state degradation
- conversion failure
- protective friction quality

It is diagnostic and admission logic only. It does not execute trades, place orders, manage wallets, or deploy capital.

## Doctrine

- Prediction is not enough.
- Local clearance is not global clearance.
- Visible calm is not enough.
- A true signal may still not deserve action.
- Durable fallback beats fragile cleverness under pressure.
- The board must be covered before execution.
- Policy veto remains supreme.

## Module Flow

1. Board-control scoring
2. Critical-square exposure
3. Weakest-path audit
4. Local-versus-global clearance guard
5. Feedback integrity and review-theater detection
6. Premise testing and self-audit
7. Contextual interpretation guard
8. Hidden-disturbance and baseline-violation checks
9. Error clustering and fallback switching
10. Pressure tool filtering
11. Ritual and mechanical cue auditing
12. Operator-state telemetry
13. Conversion-failure analysis
14. Protective-friction classification
15. Final action admission

## Core Formulas

- `BoardControlScore = CriticalSquareControl * ResponseLineOpenness * ContainmentStrength * CoreProtection - AccessSurfaceExposure * ACCESS_SURFACE_PENALTY_WEIGHT`
- `CriticalSquareExposure = Impact * Access * (1 - Reversibility) * (1 - ProtectiveFriction)`
- `WeakestPathScore = min(path_strength_i)`
- `FeedbackIntegrityScore = RootCauseSpecificity * OwnershipClarity * VerifiableAction * DeadlineClarity - BlameAvoidancePenalty`
- `ReviewTheaterScore = mean(VagueLanguage, NoOwner, NoDeadline, NoVerifiableChange)`
- `SelfAuditScore = PremiseConfidence * BoundaryIntegrity * EvidenceStrength * ExposureAwareness * ActionDiscipline`
- `PremiseQualityScore = mean(EvidenceStrength, AlternativeHypothesisCoverage, SourceQuality, ContradictionCheck, AssumptionTransparency)`
- `OutcomeQualityScore = PremiseQualityScore * ProcessQualityScore * ExecutionQualityScore`
- `TargetedIntentProbability = SignalSpecificity * TimingAlignment * ConsequenceScore * TargetRepetition * PatternContextAlignment - GeneralHabitEvidence`
- `HostilityProbability = TargetedIntentProbability * NegativeConsequenceScore * AdversarialContextScore`
- `ActionWorthinessScore = SignalTruthScore * StrategicRelevance * ExpectedBenefit * PatternContextAlignment - ReactionCost`
- `HiddenDisturbanceScore = max(0, CurrentErrorRate - BaselineErrorRate) * PressureStateScore * DisturbanceSensitivity`
- `ExecutionDriftScore = max(0, CurrentErrorRate - BaselineErrorRate)`
- `ToolReliability = BaseSkill * OperatorState * PressureFit * RecentSuccessRate`
- `PrecisionReadiness = weighted_mean(Food, Hydration, Sleep, Warmup, InverseStress) - AlcoholPenalty`
- `InvestableSignal = Detection * Validation * Durability * ExecutionSurvivability * BoardControl * GlobalClearance * OperatorReadiness - WeakestPathPenalty - HiddenDriftPenalty - CriticalSquarePenalty`

## Reason Codes

Representative reason codes emitted by the layer:

- `CRITICAL_SQUARE_EXPOSED`
- `GLOBAL_CLEARANCE_BLOCKED`
- `WEAKEST_PATH_EXPOSED`
- `REVIEW_THEATER_DETECTED`
- `PREMISE_CORRUPTION_RISK`
- `HIDDEN_EXECUTION_DRIFT`
- `MICRO_CHAOS_DETECTED`
- `TOUCH_DECEPTION_UNSTABLE`
- `DURABLE_FALLBACK_REQUIRED`
- `MECHANICAL_CUE_REQUIRED`
- `OPERATOR_STATE_UNSTABLE`
- `CONVERSION_FAILURE_HIGH`
- `PROTECTIVE_FRICTION_REQUIRED`

Every report also includes `formula_trace` and `transition_log` so the blocking path is auditable.

## Bull-State Mapping

- `MIURA`: raw or premise-corrupted signal
- `MURCIELAGO`: durability testing, fallback, or hidden-disturbance containment
- `AVENTADOR`: globally cleared promoted signal
- `GALLARDO`: disciplined execution-mode readiness
- `ISLERO`: shock or forced reclassification
- `DIABLO`: veto, chaos, weak containment, or no-new-risk state
- `HURACAN`: fast-track only when validation, board coverage, and risk caps all pass

`HURACAN` does not bypass policy, chaos, validation, or fallback gates.

## Health Report Fields

The pipeline health report adds compact additive board-control fields:

- `board_control_score`
- `critical_square_exposure`
- `weakest_path_score`
- `local_global_clearance_gap`
- `feedback_integrity_score`
- `review_theater_score`
- `hidden_disturbance_score`
- `execution_drift_score`
- `baseline_violation_flag`
- `error_cluster_type`
- `board_control_active_mode`
- `board_control_disabled_tools`
- `operator_precision_readiness`
- `ritual_effectiveness_score`
- `conversion_failure_score`
- `protective_friction_score`
- `board_control_final_state`
- `board_control_bull_state`
- `board_control_promotion_allowed`
- `board_control_action_allowed`
- `board_control_fallback_required`
- `board_control_recommended_next_action`
- `board_control_report_path`

The CLI summary also emits a compact string:

- `board_control_safety=state=..., score=..., weakest_path=..., hidden_drift=..., action=...`

## Limitations

- The runtime report is derived from the repo's existing seeded or runtime-safe signal rows unless richer telemetry is present.
- The layer is conservative and worst-case oriented by design.
- This is not a second execution authority path. It is a read-only board-safety report.
- No live trading, broker integration, wallet handling, or private-key logic is added.
