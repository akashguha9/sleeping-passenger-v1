from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        BOARD_CONTROL_SAFETY_REPORT_PATH,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        BOARD_CONTROL_SAFETY_REPORT_PATH,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )


EPSILON = 1e-9
ACCESS_SURFACE_PENALTY_WEIGHT = 0.50
EVIDENCE_THRESHOLD = 0.50


class BoardControlState(str, Enum):
    PARTIAL_CLEARANCE_ONLY = "PARTIAL_CLEARANCE_ONLY"
    CRITICAL_SQUARE_EXPOSED = "CRITICAL_SQUARE_EXPOSED"
    FAILURE_CONTAINMENT_WEAK = "FAILURE_CONTAINMENT_WEAK"
    REVIEW_THEATER_DETECTED = "REVIEW_THEATER_DETECTED"
    PROTECTIVE_FRICTION_REQUIRED = "PROTECTIVE_FRICTION_REQUIRED"
    GLOBAL_CLEARANCE_BLOCKED = "GLOBAL_CLEARANCE_BLOCKED"
    VISIBLE_CONTROL_PASSED = "VISIBLE_CONTROL_PASSED"
    HIDDEN_EXECUTION_DRIFT = "HIDDEN_EXECUTION_DRIFT"
    MICRO_CHAOS_DETECTED = "MICRO_CHAOS_DETECTED"
    TOUCH_DECEPTION_UNSTABLE = "TOUCH_DECEPTION_UNSTABLE"
    DURABLE_FALLBACK_REQUIRED = "DURABLE_FALLBACK_REQUIRED"
    BASELINE_VIOLATION = "BASELINE_VIOLATION"
    RITUAL_INSUFFICIENT = "RITUAL_INSUFFICIENT"
    MECHANICAL_CUE_REQUIRED = "MECHANICAL_CUE_REQUIRED"
    OPERATOR_STATE_UNSTABLE = "OPERATOR_STATE_UNSTABLE"
    PREMISE_CORRUPTION_RISK = "PREMISE_CORRUPTION_RISK"
    WEAKEST_PATH_EXPOSED = "WEAKEST_PATH_EXPOSED"
    ACTION_WORTHINESS_LOW = "ACTION_WORTHINESS_LOW"
    CONVERSION_FAILURE_HIGH = "CONVERSION_FAILURE_HIGH"
    BOARD_CONTROL_ACCEPTABLE = "BOARD_CONTROL_ACCEPTABLE"
    NO_BOARD_RISK_DETECTED = "NO_BOARD_RISK_DETECTED"


class RecommendedAction(str, Enum):
    BLOCK_PROMOTION = "BLOCK_PROMOTION"
    REQUIRE_MORE_EVIDENCE = "REQUIRE_MORE_EVIDENCE"
    ADD_PROTECTIVE_FRICTION = "ADD_PROTECTIVE_FRICTION"
    ACTIVATE_DURABLE_FALLBACK = "ACTIVATE_DURABLE_FALLBACK"
    DISABLE_PRECISION_TOOLS = "DISABLE_PRECISION_TOOLS"
    REQUIRE_MECHANICAL_CUE = "REQUIRE_MECHANICAL_CUE"
    RUN_SELF_AUDIT = "RUN_SELF_AUDIT"
    HOLD_NO_ACTION = "HOLD_NO_ACTION"
    ALLOW_LOW_RISK_PROBE = "ALLOW_LOW_RISK_PROBE"
    ALLOW_RESTRICTED_EXECUTION = "ALLOW_RESTRICTED_EXECUTION"
    ALLOW_FULL_EXECUTION = "ALLOW_FULL_EXECUTION"
    ESCALATE_TO_MANUAL_REVIEW = "ESCALATE_TO_MANUAL_REVIEW"


class BullBoardState(str, Enum):
    MIURA = "MIURA"
    MURCIELAGO = "MURCIELAGO"
    AVENTADOR = "AVENTADOR"
    GALLARDO = "GALLARDO"
    ISLERO = "ISLERO"
    DIABLO = "DIABLO"
    HURACAN = "HURACAN"


@dataclass(slots=True)
class BoardControlInput:
    signal_id: str
    timestamp: str | None
    critical_square_control: float
    response_line_openness: float
    containment_strength: float
    core_protection: float
    access_surface_exposure: float
    impact_score: float
    access_score: float
    reversibility_score: float
    protective_friction_score: float
    detection_score: float
    validation_score: float
    durability_score: float
    execution_survivability_score: float
    policy_veto: bool
    chaos_veto: bool
    heat_risk_score: float
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PathGateInput:
    path_name: str
    admission_gate_strength: float
    validation_gate_strength: float
    execution_gate_strength: float
    containment_gate_strength: float
    reversibility_strength: float


@dataclass(slots=True)
class ClearanceLayerInput:
    layer_name: str
    clearance_passed: bool
    clearance_score: float
    critical: bool


@dataclass(slots=True)
class FeedbackIntegrityInput:
    root_cause_specificity: float
    ownership_clarity: float
    verifiable_action_score: float
    deadline_clarity: float
    blame_avoidance_penalty: float
    vague_language_score: float
    no_owner_score: float
    no_deadline_score: float
    no_verifiable_change_score: float


@dataclass(slots=True)
class SelfAuditInput:
    premise_confidence: float
    boundary_integrity: float
    evidence_strength: float
    exposure_awareness: float
    action_discipline: float
    alternative_hypotheses_present: bool
    avoidable_opening_reconstructed: bool
    fallback_mode_considered: bool


@dataclass(slots=True)
class PremiseTestingInput:
    evidence_strength: float
    alternative_hypothesis_coverage: float
    source_quality: float
    contradiction_check: float
    assumption_transparency: float
    process_quality_score: float
    execution_quality_score: float


@dataclass(slots=True)
class ContextualInterpretationGuardInput:
    pattern_strength: float
    context_relevance: float
    signal_specificity: float
    consequence_score: float
    repetition_score: float
    cross_context_persistence: float
    source_consistency: float
    time_persistence: float
    timing_alignment: float
    target_repetition: float
    general_habit_evidence: float
    negative_consequence_score: float
    adversarial_context_score: float
    signal_truth_score: float
    strategic_relevance: float
    expected_benefit: float
    reaction_cost: float


@dataclass(slots=True)
class HiddenDisturbanceInput:
    baseline_error_rate: float
    current_error_rate: float
    pressure_state_score: float
    disturbance_sensitivity: float
    visible_reaction_score: float


@dataclass(slots=True)
class BaselineViolationInput:
    baseline_error_rate: float
    current_error_rate: float
    baseline_threshold: float


@dataclass(slots=True)
class ErrorEventInput:
    error_type: str
    tool_type: str
    sequence_index: int | None
    pressure_state: str
    context_label: str


@dataclass(slots=True)
class FallbackSwitchingInput:
    precision_tool_error_count: int
    fallback_activation_threshold: int


@dataclass(slots=True)
class PressureToolInput:
    tool_name: str
    tool_category: str
    base_skill: float
    operator_state_score: float
    pressure_fit_score: float
    recent_success_rate: float
    tool_fragility_score: float
    pressure_state_score: float
    threshold: float


@dataclass(slots=True)
class RitualEffectivenessInput:
    ritual_completed: bool
    pre_ritual_error_rate: float
    post_ritual_error_rate: float
    baseline_error_rate: float
    threshold: float


@dataclass(slots=True)
class MechanicalCueInput:
    cue_selected: str | None
    cue_type: str | None
    cue_adherence_score: float
    post_cue_execution_quality: float
    ritual_insufficient: bool
    mental_reset_score: float
    operator_state_score: float


@dataclass(slots=True)
class OperatorStateTelemetryInput:
    food_state_score: float
    hydration_score: float
    alcohol_penalty: float
    sleep_quality_score: float
    stress_score: float
    warmup_quality_score: float


@dataclass(slots=True)
class ConversionFailureInput:
    capability_score: float
    hinge_points_won: int
    hinge_points_played: int
    final_phase_error_rate: float
    baseline_error_rate: float
    deuce_points_won: int
    deuce_points_played: int
    lead_protection_successes: int
    lead_protection_attempts: int
    pressure_points_won: int
    pressure_points_played: int
    threshold: float


@dataclass(slots=True)
class ProtectiveFrictionInput:
    friction_location: str
    critical_path_flag: bool
    risk_reduction_score: float
    opportunity_drag_score: float
    critical_square_exposure: float
    protective_friction_score: float


@dataclass(slots=True)
class ActionAdmissionResult:
    investable_signal_score: float
    admission_tier: str
    promotion_allowed: bool
    action_allowed: bool
    fallback_required: bool
    precision_tools_allowed: bool
    feedback_learning_valid: bool
    bull_state: str
    recommended_next_action: str
    reason_codes: list[str]
    formula_trace: dict[str, float]


@dataclass(slots=True)
class BoardControlSafetyReport:
    signal_id: str
    timestamp: str | None
    input_summary: dict[str, Any]
    premise_quality_score: float
    board_control_score: float
    critical_square_exposure: float
    weakest_path_score: float
    local_global_clearance_gap: float
    feedback_integrity_score: float
    review_theater_score: float
    self_audit_score: float
    hidden_disturbance_score: float
    execution_drift_score: float
    baseline_violation_flag: bool
    error_cluster_type: str
    active_mode: str
    disabled_tools: list[str]
    allowed_tools: list[str]
    operator_precision_readiness: float
    ritual_effectiveness_score: float
    conversion_failure_score: float
    protective_friction_score: float
    investable_signal_score: float
    final_state: str
    bull_state: str
    promotion_allowed: bool
    action_allowed: bool
    fallback_required: bool
    precision_tools_allowed: bool
    feedback_learning_valid: bool
    reason_codes: list[str]
    recommended_next_action: str
    formula_trace: dict[str, float]
    transition_log: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    if abs(float(b)) <= EPSILON:
        return float(default)
    return float(a) / float(b)


def weighted_mean(
    values: dict[str, float], weights: dict[str, float] | None = None
) -> float:
    if not values:
        return 0.0
    if weights is None:
        return clamp01(sum(clamp01(v) for v in values.values()) / len(values))
    total_weight = sum(max(0.0, float(w)) for w in weights.values())
    if total_weight <= EPSILON:
        return 0.0
    numerator = 0.0
    for key, value in values.items():
        numerator += clamp01(value) * max(0.0, float(weights.get(key, 0.0)))
    return clamp01(numerator / total_weight)


def compute_board_control_score(payload: BoardControlInput) -> tuple[float, list[str]]:
    score = clamp01(
        clamp01(payload.critical_square_control)
        * clamp01(payload.response_line_openness)
        * clamp01(payload.containment_strength)
        * clamp01(payload.core_protection)
        - clamp01(payload.access_surface_exposure) * ACCESS_SURFACE_PENALTY_WEIGHT
    )
    if score < 0.35:
        return score, [BoardControlState.CRITICAL_SQUARE_EXPOSED.value]
    if payload.containment_strength < 0.40:
        return score, [BoardControlState.FAILURE_CONTAINMENT_WEAK.value]
    if score < 0.60:
        return score, [BoardControlState.PROTECTIVE_FRICTION_REQUIRED.value]
    return score, [BoardControlState.BOARD_CONTROL_ACCEPTABLE.value]


def compute_critical_square_exposure(payload: BoardControlInput) -> tuple[float, list[str]]:
    irreversibility = 1.0 - clamp01(payload.reversibility_score)
    low_friction = 1.0 - clamp01(payload.protective_friction_score)
    exposure = clamp01(
        clamp01(payload.impact_score)
        * clamp01(payload.access_score)
        * irreversibility
        * low_friction
    )
    reasons: list[str] = []
    if payload.impact_score >= 0.70:
        reasons.append("HIGH_IMPACT_NODE")
    if payload.access_score >= 0.70:
        reasons.append("HIGH_ACCESS_SURFACE")
    if irreversibility >= 0.70:
        reasons.append("LOW_REVERSIBILITY")
    if low_friction >= 0.60:
        reasons.append("LOW_PROTECTIVE_FRICTION")
    if exposure >= 0.70:
        reasons.append(BoardControlState.CRITICAL_SQUARE_EXPOSED.value)
    return exposure, reasons


def compute_path_strength(path: PathGateInput) -> tuple[float, list[str]]:
    gate_map = {
        "WEAK_ADMISSION_GATE": clamp01(path.admission_gate_strength),
        "WEAK_VALIDATION_GATE": clamp01(path.validation_gate_strength),
        "WEAK_EXECUTION_GATE": clamp01(path.execution_gate_strength),
        "WEAK_CONTAINMENT_GATE": clamp01(path.containment_gate_strength),
        "LOW_REVERSIBILITY": clamp01(path.reversibility_strength),
    }
    weakest_reason, weakest_strength = min(gate_map.items(), key=lambda item: item[1])
    return weakest_strength, [weakest_reason]


def audit_weakest_path(paths: list[PathGateInput]) -> tuple[float, list[str]]:
    if not paths:
        return 0.0, [BoardControlState.WEAKEST_PATH_EXPOSED.value]
    weakest = 1.0
    reasons: list[str] = []
    for path in paths:
        strength, path_reasons = compute_path_strength(path)
        if strength < weakest:
            weakest = strength
            reasons = path_reasons
    if weakest < 0.30:
        reasons.append(BoardControlState.WEAKEST_PATH_EXPOSED.value)
    elif weakest < 0.55:
        reasons.append(BoardControlState.PROTECTIVE_FRICTION_REQUIRED.value)
    return clamp01(weakest), list(dict.fromkeys(reasons))


def evaluate_clearance_guard(
    layers: list[ClearanceLayerInput],
) -> tuple[bool, float, float, float, list[str]]:
    if not layers:
        return False, 0.0, 0.0, 0.0, [BoardControlState.GLOBAL_CLEARANCE_BLOCKED.value]
    critical_layers = [layer for layer in layers if layer.critical]
    local_scores = [
        clamp01(layer.clearance_score) for layer in layers if layer.clearance_passed
    ]
    local_clearance_score = (
        sum(local_scores) / len(local_scores) if local_scores else 0.0
    )
    cleared_critical = sum(1 for layer in critical_layers if layer.clearance_passed)
    global_clearance = all(layer.clearance_passed for layer in critical_layers) if critical_layers else False
    global_clearance_score = safe_divide(cleared_critical, len(critical_layers), default=0.0)
    gap = clamp01(local_clearance_score) - clamp01(global_clearance_score)
    reasons: list[str] = []
    if local_clearance_score > 0.0 and not global_clearance:
        reasons.append("LOCAL_CLEAR_BUT_GLOBAL_RISK_REMAINS")
        reasons.append(BoardControlState.PARTIAL_CLEARANCE_ONLY.value)
    for layer in critical_layers:
        if layer.clearance_passed:
            continue
        mapping = {
            "containment_check": "MISSING_CONTAINMENT_CLEARANCE",
            "access_surface_check": "ACCESS_SURFACE_NOT_CLEARED",
            "execution_readiness": "EXECUTION_READINESS_NOT_CLEARED",
            "operator_state_check": "OPERATOR_STATE_NOT_CLEARED",
        }
        if layer.layer_name in mapping:
            reasons.append(mapping[layer.layer_name])
    if local_clearance_score >= 0.70 and global_clearance_score < 0.70:
        reasons.append(BoardControlState.GLOBAL_CLEARANCE_BLOCKED.value)
    return (
        global_clearance,
        clamp01(local_clearance_score),
        clamp01(global_clearance_score),
        gap,
        list(dict.fromkeys(reasons)),
    )


def evaluate_feedback_integrity(
    payload: FeedbackIntegrityInput,
) -> tuple[float, float, list[str], bool]:
    feedback_integrity_score = clamp01(
        clamp01(payload.root_cause_specificity)
        * clamp01(payload.ownership_clarity)
        * clamp01(payload.verifiable_action_score)
        * clamp01(payload.deadline_clarity)
        - clamp01(payload.blame_avoidance_penalty)
    )
    review_theater_score = clamp01(
        (
            clamp01(payload.vague_language_score)
            + clamp01(payload.no_owner_score)
            + clamp01(payload.no_deadline_score)
            + clamp01(payload.no_verifiable_change_score)
        )
        / 4.0
    )
    reasons: list[str] = []
    if payload.vague_language_score >= 0.50:
        reasons.append("VAGUE_LANGUAGE")
    if payload.no_owner_score >= 0.50:
        reasons.append("NO_OWNER")
    if payload.no_deadline_score >= 0.50:
        reasons.append("NO_DEADLINE")
    if payload.no_verifiable_change_score >= 0.50:
        reasons.append("NO_VERIFIABLE_CHANGE")
    if payload.blame_avoidance_penalty >= 0.40:
        reasons.append("BLAME_AVOIDANCE")
    if payload.root_cause_specificity < 0.40:
        reasons.append("ROOT_CAUSE_UNCLEAR")
    if review_theater_score >= 0.70:
        reasons.append(BoardControlState.REVIEW_THEATER_DETECTED.value)
    learning_valid = feedback_integrity_score >= 0.40 and review_theater_score <= 0.70
    return feedback_integrity_score, review_theater_score, list(dict.fromkeys(reasons)), learning_valid


def evaluate_self_audit(payload: SelfAuditInput) -> tuple[float, list[str], bool]:
    score = clamp01(
        clamp01(payload.premise_confidence)
        * clamp01(payload.boundary_integrity)
        * clamp01(payload.evidence_strength)
        * clamp01(payload.exposure_awareness)
        * clamp01(payload.action_discipline)
    )
    reasons: list[str] = []
    action_allowed = True
    if payload.premise_confidence < 0.45:
        reasons.extend(["PREMISE_UNTESTED", BoardControlState.PREMISE_CORRUPTION_RISK.value])
        action_allowed = False
    if not payload.alternative_hypotheses_present:
        reasons.append("ALTERNATIVE_HYPOTHESES_MISSING")
        action_allowed = False
    if payload.evidence_strength < EVIDENCE_THRESHOLD:
        reasons.append("EVIDENCE_BELOW_THRESHOLD")
        action_allowed = False
    if not payload.avoidable_opening_reconstructed:
        reasons.append("EXPOSURE_NOT_RECONSTRUCTED")
    if not payload.fallback_mode_considered:
        reasons.append("FALLBACK_NOT_CONSIDERED")
    if score < 0.50:
        reasons.append("ACTION_TOO_EARLY")
        action_allowed = False
    return score, list(dict.fromkeys(reasons)), action_allowed


def evaluate_premise_testing(payload: PremiseTestingInput) -> tuple[float, float, list[str]]:
    premise_quality_score = weighted_mean(
        {
            "evidence_strength": payload.evidence_strength,
            "alternative_hypothesis_coverage": payload.alternative_hypothesis_coverage,
            "source_quality": payload.source_quality,
            "contradiction_check": payload.contradiction_check,
            "assumption_transparency": payload.assumption_transparency,
        }
    )
    outcome_quality_score = clamp01(
        premise_quality_score
        * clamp01(payload.process_quality_score)
        * clamp01(payload.execution_quality_score)
    )
    reasons: list[str] = []
    if payload.evidence_strength < 0.50:
        reasons.append("LOW_EVIDENCE_STRENGTH")
    if payload.alternative_hypothesis_coverage < 0.50:
        reasons.append("NO_ALTERNATIVE_HYPOTHESIS")
    if payload.source_quality < 0.50:
        reasons.append("SOURCE_QUALITY_WEAK")
    if payload.contradiction_check < 0.50:
        reasons.append("CONTRADICTIONS_UNRESOLVED")
    if payload.assumption_transparency < 0.50:
        reasons.append("ASSUMPTIONS_UNCLEAR")
    if premise_quality_score < 0.50:
        reasons.append(BoardControlState.PREMISE_CORRUPTION_RISK.value)
    return premise_quality_score, outcome_quality_score, list(dict.fromkeys(reasons))


def evaluate_contextual_interpretation_guard(
    payload: ContextualInterpretationGuardInput,
) -> tuple[float, float, float, float, list[str]]:
    signal_durability = weighted_mean(
        {
            "repetition_score": payload.repetition_score,
            "cross_context_persistence": payload.cross_context_persistence,
            "source_consistency": payload.source_consistency,
            "time_persistence": payload.time_persistence,
        }
    )
    pattern_context_alignment = weighted_mean(
        {
            "pattern_strength": payload.pattern_strength,
            "context_relevance": payload.context_relevance,
        }
    )
    targeted_intent_probability = clamp01(
        clamp01(payload.signal_specificity)
        * clamp01(payload.timing_alignment)
        * clamp01(payload.consequence_score)
        * clamp01(payload.target_repetition)
        * pattern_context_alignment
        - clamp01(payload.general_habit_evidence)
    )
    hostility_probability = clamp01(
        targeted_intent_probability
        * clamp01(payload.negative_consequence_score)
        * clamp01(payload.adversarial_context_score)
    )
    action_worthiness_score = clamp01(
        clamp01(payload.signal_truth_score)
        * clamp01(payload.strategic_relevance)
        * clamp01(payload.expected_benefit)
        * max(pattern_context_alignment, 0.25)
        - clamp01(payload.reaction_cost)
    )
    reasons: list[str] = []
    if payload.repetition_score < 0.40 or payload.pattern_strength < 0.40:
        reasons.append("SINGLE_SIGNAL_ONLY")
    else:
        reasons.append("PATTERN_CONFIRMED")
    if signal_durability >= 0.70 and hostility_probability < 0.40:
        reasons.append("DURABLE_NOT_HOSTILE")
    if payload.general_habit_evidence >= 0.50:
        reasons.append("GENERAL_PATTERN_NOT_TARGETED")
    if payload.reaction_cost >= 0.55:
        reasons.append("HIGH_REACTION_COST")
    if payload.strategic_relevance < 0.45:
        reasons.append("LOW_STRATEGIC_RELEVANCE")
    return (
        signal_durability,
        targeted_intent_probability,
        hostility_probability,
        action_worthiness_score,
        list(dict.fromkeys(reasons)),
    )


def evaluate_hidden_disturbance(
    payload: HiddenDisturbanceInput,
) -> tuple[float, float, list[str]]:
    error_rate_delta = max(0.0, clamp01(payload.current_error_rate) - clamp01(payload.baseline_error_rate))
    hidden_disturbance_score = clamp01(
        error_rate_delta
        * clamp01(payload.pressure_state_score)
        * clamp01(payload.disturbance_sensitivity)
    )
    reasons: list[str] = []
    if payload.visible_reaction_score <= 0.20 and hidden_disturbance_score >= 0.60:
        reasons.extend(
            [
                "VISIBLE_CONTROL_BUT_OUTPUT_DRIFT",
                BoardControlState.HIDDEN_EXECUTION_DRIFT.value,
            ]
        )
    if error_rate_delta > 0.0:
        reasons.append("ERROR_RATE_ABOVE_BASELINE")
    if payload.pressure_state_score >= 0.60:
        reasons.append("PRESSURE_AMPLIFIED_DRIFT")
    if payload.disturbance_sensitivity >= 0.60:
        reasons.append("DISTURBANCE_NOT_NEUTRALIZED")
    if hidden_disturbance_score >= 0.75:
        reasons.append(BoardControlState.MICRO_CHAOS_DETECTED.value)
    return error_rate_delta, hidden_disturbance_score, list(dict.fromkeys(reasons))


def evaluate_baseline_violation(
    payload: BaselineViolationInput,
) -> tuple[float, bool, list[str]]:
    execution_drift_score = clamp01(
        max(0.0, clamp01(payload.current_error_rate) - clamp01(payload.baseline_error_rate))
    )
    baseline_violation_flag = (
        clamp01(payload.current_error_rate)
        >= clamp01(payload.baseline_error_rate) + clamp01(payload.baseline_threshold)
    )
    reasons: list[str] = []
    if baseline_violation_flag:
        reasons.extend(["BASELINE_BREACHED", "ABNORMAL_ERROR_SPIKE", "RESTRICTED_MODE_REQUIRED"])
    if execution_drift_score >= 0.70:
        reasons.extend([BoardControlState.HIDDEN_EXECUTION_DRIFT.value, "OUTPUT_NOT_RECOVERED"])
    return execution_drift_score, baseline_violation_flag, list(dict.fromkeys(reasons))


def classify_error_cluster(
    events: list[ErrorEventInput],
) -> tuple[str, float, list[str], dict[str, int]]:
    if not events:
        return BoardControlState.NO_BOARD_RISK_DETECTED.value, 0.0, [], {}
    counts: dict[str, int] = {}
    for event in events:
        counts[event.tool_type] = counts.get(event.tool_type, 0) + 1
    total_errors = sum(counts.values())
    dominant_tool, dominant_count = max(counts.items(), key=lambda item: item[1])
    clustered_failure_likelihood = clamp01(safe_divide(dominant_count, total_errors, default=0.0))
    reasons: list[str] = []
    if clustered_failure_likelihood >= 0.50:
        reasons.extend(["REPEATED_TOOL_FAILURE", "PRESSURE_CLUSTER_DETECTED"])
    if dominant_tool in {"precision", "touch", "deception"} and dominant_count >= 2:
        reasons.extend(["TOUCH_TOOL_UNSTABLE", "FAILURE_NOT_RANDOM"])
        return (
            BoardControlState.TOUCH_DECEPTION_UNSTABLE.value,
            clustered_failure_likelihood,
            list(dict.fromkeys(reasons)),
            counts,
        )
    cluster_type = (
        "PRESSURE_CLUSTER_DETECTED"
        if clustered_failure_likelihood >= 0.50
        else BoardControlState.NO_BOARD_RISK_DETECTED.value
    )
    return cluster_type, clustered_failure_likelihood, list(dict.fromkeys(reasons)), counts


def evaluate_fallback_switching(
    payload: FallbackSwitchingInput,
) -> tuple[str, bool, list[str], list[str], list[str]]:
    if payload.precision_tool_error_count >= payload.fallback_activation_threshold:
        return (
            BoardControlState.DURABLE_FALLBACK_REQUIRED.value,
            True,
            ["PRECISION", "DECEPTION", "HIGH_VOLATILITY"],
            ["DURABLE", "EMERGENCY"],
            [
                "PRECISION_TOOL_FAILURE_THRESHOLD_BREACHED",
                "TOUCH_DECEPTION_DISABLED",
                "DURABLE_MODE_ACTIVATED",
                "REPEATED_SELF_INFLICTED_ENTRY_ERROR",
            ],
        )
    return (
        BoardControlState.BOARD_CONTROL_ACCEPTABLE.value,
        False,
        [],
        ["PRECISION", "DURABLE", "EMERGENCY"],
        [],
    )


def evaluate_pressure_tool(tool: PressureToolInput) -> tuple[float, bool, list[str]]:
    tool_reliability = clamp01(
        clamp01(tool.base_skill)
        * clamp01(tool.operator_state_score)
        * clamp01(tool.pressure_fit_score)
        * clamp01(tool.recent_success_rate)
    )
    allowed = tool_reliability >= clamp01(tool.threshold)
    reasons: list[str] = []
    if tool_reliability < clamp01(tool.threshold):
        reasons.append("TOOL_UNRELIABLE_UNDER_PRESSURE")
    if tool.operator_state_score < 0.50:
        reasons.append("OPERATOR_STATE_TOO_LOW")
    if tool.recent_success_rate < 0.50:
        reasons.append("RECENT_FAILURES_TOO_HIGH")
    if tool.tool_fragility_score > 0.70 and tool.pressure_state_score > 0.60:
        allowed = False
        reasons.append("FRAGILITY_COST_TOO_HIGH")
    return tool_reliability, allowed, list(dict.fromkeys(reasons))


def evaluate_ritual_effectiveness(
    payload: RitualEffectivenessInput,
) -> tuple[float, bool, list[str]]:
    ritual_effectiveness_score = clamp01(
        1.0
        - abs(
            clamp01(payload.post_ritual_error_rate)
            - clamp01(payload.baseline_error_rate)
        )
    )
    ritual_insufficient = bool(
        payload.ritual_completed
        and clamp01(payload.post_ritual_error_rate)
        > clamp01(payload.baseline_error_rate) + clamp01(payload.threshold)
    )
    reasons: list[str] = []
    if ritual_insufficient:
        reasons.extend(
            [
                "RITUAL_COMPLETED_BUT_OUTPUT_NOT_RESTORED",
                "MENTAL_RESET_NOT_ENOUGH",
                BoardControlState.MECHANICAL_CUE_REQUIRED.value,
                BoardControlState.RITUAL_INSUFFICIENT.value,
            ]
        )
    return ritual_effectiveness_score, ritual_insufficient, reasons


def evaluate_mechanical_cue(
    payload: MechanicalCueInput,
) -> tuple[float, bool, list[str]]:
    cue_stability = clamp01(
        clamp01(payload.mental_reset_score)
        * clamp01(payload.cue_adherence_score)
        * clamp01(payload.operator_state_score)
        * max(clamp01(payload.post_cue_execution_quality), 0.5)
    )
    cue_effective = (
        payload.cue_selected is not None
        and payload.cue_adherence_score >= 0.50
        and payload.post_cue_execution_quality >= 0.50
    )
    reasons: list[str] = []
    if payload.ritual_insufficient:
        reasons.append(BoardControlState.MECHANICAL_CUE_REQUIRED.value)
    if payload.cue_adherence_score < 0.50:
        reasons.append("CUE_ADHERENCE_TOO_LOW")
    return cue_stability, cue_effective, reasons


def evaluate_operator_state_telemetry(
    payload: OperatorStateTelemetryInput,
) -> tuple[float, list[str]]:
    inverse_stress_score = 1.0 - clamp01(payload.stress_score)
    precision_readiness_score = clamp01(
        weighted_mean(
            {
                "food_state_score": payload.food_state_score,
                "hydration_score": payload.hydration_score,
                "sleep_quality_score": payload.sleep_quality_score,
                "warmup_quality_score": payload.warmup_quality_score,
                "inverse_stress_score": inverse_stress_score,
            },
            {
                "food_state_score": 0.20,
                "hydration_score": 0.20,
                "sleep_quality_score": 0.20,
                "warmup_quality_score": 0.20,
                "inverse_stress_score": 0.20,
            },
        )
        - clamp01(payload.alcohol_penalty)
    )
    reasons: list[str] = []
    if payload.food_state_score < 0.50:
        reasons.append("LOW_FOOD_STATE")
    if payload.hydration_score < 0.50:
        reasons.append("LOW_HYDRATION")
    if payload.alcohol_penalty > 0.0:
        reasons.append("ALCOHOL_PENALTY")
    if payload.sleep_quality_score < 0.50:
        reasons.append("LOW_SLEEP")
    if payload.stress_score > 0.50:
        reasons.append("HIGH_STRESS")
    if payload.warmup_quality_score < 0.50:
        reasons.append("INSUFFICIENT_WARMUP")
    if precision_readiness_score < 0.50:
        reasons.append(BoardControlState.OPERATOR_STATE_UNSTABLE.value)
    return precision_readiness_score, list(dict.fromkeys(reasons))


def evaluate_conversion_failure(
    payload: ConversionFailureInput,
) -> tuple[float, dict[str, float], list[str]]:
    conversion_score = clamp01(
        safe_divide(payload.hinge_points_won, payload.hinge_points_played, 0.0)
    )
    deuce_conversion_rate = clamp01(
        safe_divide(payload.deuce_points_won, payload.deuce_points_played, 0.0)
    )
    lead_protection_rate = clamp01(
        safe_divide(
            payload.lead_protection_successes,
            payload.lead_protection_attempts,
            0.0,
        )
    )
    pressure_point_success_rate = clamp01(
        safe_divide(payload.pressure_points_won, payload.pressure_points_played, 0.0)
    )
    reasons: list[str] = []
    if payload.capability_score >= 0.65 and conversion_score < 0.45:
        reasons.extend(
            [
                "CAPABILITY_PRESENT_BUT_NOT_CONVERTED",
                BoardControlState.CONVERSION_FAILURE_HIGH.value,
            ]
        )
    if conversion_score < 0.45:
        reasons.append("HINGE_POINT_FAILURE")
    if payload.final_phase_error_rate > payload.baseline_error_rate + payload.threshold:
        reasons.extend(["FINAL_PHASE_ERROR_SPIKE", BoardControlState.HIDDEN_EXECUTION_DRIFT.value])
    if deuce_conversion_rate < 0.45:
        reasons.append("DEUCE_POINT_UNDERCONVERSION")
    failure_score = clamp01(
        0.35 * (1.0 - conversion_score)
        + 0.20 * (1.0 - deuce_conversion_rate)
        + 0.20 * (1.0 - lead_protection_rate)
        + 0.25 * (1.0 - pressure_point_success_rate)
    )
    return (
        failure_score,
        {
            "conversion_score": conversion_score,
            "deuce_conversion_rate": deuce_conversion_rate,
            "lead_protection_rate": lead_protection_rate,
            "pressure_point_success_rate": pressure_point_success_rate,
        },
        list(dict.fromkeys(reasons)),
    )


def classify_protective_friction(
    payload: ProtectiveFrictionInput,
) -> tuple[str, float, list[str]]:
    net_friction_value = clamp01(
        clamp01(payload.risk_reduction_score)
        - clamp01(payload.opportunity_drag_score)
        + 0.5
    )
    reasons: list[str] = []
    if payload.critical_path_flag and payload.risk_reduction_score > payload.opportunity_drag_score:
        state = BoardControlState.PROTECTIVE_FRICTION_REQUIRED.value
        reasons.append("FRICTION_PROTECTS_CRITICAL_PATH")
    elif (not payload.critical_path_flag) and payload.opportunity_drag_score > payload.risk_reduction_score:
        state = "BAD_OPERATIONAL_DRAG"
        reasons.extend(["FRICTION_ONLY_SLOWS_ACTION", "BAD_OPERATIONAL_DRAG"])
    else:
        state = BoardControlState.BOARD_CONTROL_ACCEPTABLE.value
    if payload.critical_square_exposure > 0.70 and payload.protective_friction_score < 0.50:
        state = BoardControlState.PROTECTIVE_FRICTION_REQUIRED.value
        reasons.append("CRITICAL_PATH_UNDERPROTECTED")
    if payload.opportunity_drag_score > 0.70:
        reasons.append("OPPORTUNITY_DRAG_TOO_HIGH")
    return state, net_friction_value, list(dict.fromkeys(reasons))


def evaluate_action_admission(
    *,
    detection_score: float,
    validation_score: float,
    durability_score: float,
    execution_survivability_score: float,
    board_control_score: float,
    global_clearance_score: float,
    operator_precision_readiness: float,
    weakest_path_score: float,
    hidden_disturbance_score: float,
    critical_square_exposure: float,
    premise_quality_score: float,
    policy_veto: bool,
    chaos_veto: bool,
    fallback_required: bool,
    review_theater_score: float,
) -> ActionAdmissionResult:
    weakest_path_penalty = 1.0 - clamp01(weakest_path_score)
    hidden_drift_penalty = clamp01(hidden_disturbance_score)
    critical_square_penalty = clamp01(critical_square_exposure)
    investable_signal_score = clamp01(
        clamp01(detection_score)
        * clamp01(validation_score)
        * clamp01(durability_score)
        * clamp01(execution_survivability_score)
        * clamp01(board_control_score)
        * clamp01(global_clearance_score)
        * clamp01(operator_precision_readiness)
        - weakest_path_penalty
        - hidden_drift_penalty
        - critical_square_penalty
    )

    promotion_allowed = True
    action_allowed = True
    precision_tools_allowed = clamp01(operator_precision_readiness) >= 0.50
    feedback_learning_valid = clamp01(review_theater_score) <= 0.70
    reasons: list[str] = []

    if clamp01(global_clearance_score) < 1.0:
        promotion_allowed = False
        reasons.append(BoardControlState.GLOBAL_CLEARANCE_BLOCKED.value)
    if weakest_path_score < 0.30:
        promotion_allowed = False
        reasons.append(BoardControlState.WEAKEST_PATH_EXPOSED.value)
    if critical_square_exposure > 0.85:
        promotion_allowed = False
        reasons.append(BoardControlState.CRITICAL_SQUARE_EXPOSED.value)
    if hidden_disturbance_score > 0.80 and not fallback_required:
        action_allowed = False
        reasons.append(BoardControlState.HIDDEN_EXECUTION_DRIFT.value)
    if premise_quality_score < 0.50:
        action_allowed = False
        reasons.append(BoardControlState.PREMISE_CORRUPTION_RISK.value)
    if operator_precision_readiness < 0.50:
        precision_tools_allowed = False
        reasons.append(BoardControlState.OPERATOR_STATE_UNSTABLE.value)
    if review_theater_score > 0.70:
        feedback_learning_valid = False
        reasons.append(BoardControlState.REVIEW_THEATER_DETECTED.value)
    if policy_veto or chaos_veto:
        action_allowed = False
        promotion_allowed = False
        reasons.append("POLICY_OR_CHAOS_VETO")

    if investable_signal_score < 0.35:
        admission_tier = "BLOCK"
        recommended_next_action = RecommendedAction.BLOCK_PROMOTION.value
        action_allowed = False
    elif investable_signal_score < 0.55:
        admission_tier = "HOLD_AND_COLLECT_EVIDENCE"
        recommended_next_action = RecommendedAction.REQUIRE_MORE_EVIDENCE.value
    elif investable_signal_score < 0.70:
        admission_tier = RecommendedAction.ALLOW_LOW_RISK_PROBE.value
        recommended_next_action = RecommendedAction.ALLOW_LOW_RISK_PROBE.value
    elif investable_signal_score < 0.85:
        admission_tier = RecommendedAction.ALLOW_RESTRICTED_EXECUTION.value
        recommended_next_action = RecommendedAction.ALLOW_RESTRICTED_EXECUTION.value
    else:
        admission_tier = RecommendedAction.ALLOW_FULL_EXECUTION.value
        recommended_next_action = RecommendedAction.ALLOW_FULL_EXECUTION.value

    if policy_veto or chaos_veto:
        bull_state = BullBoardState.DIABLO.value
    elif fallback_required:
        bull_state = BullBoardState.GALLARDO.value
    elif weakest_path_score < 0.30 or critical_square_exposure > 0.85:
        bull_state = BullBoardState.DIABLO.value
    elif premise_quality_score < 0.50:
        bull_state = BullBoardState.MIURA.value
    elif action_allowed and promotion_allowed and investable_signal_score >= 0.85:
        bull_state = BullBoardState.AVENTADOR.value
    elif action_allowed and promotion_allowed and investable_signal_score >= 0.70:
        bull_state = BullBoardState.HURACAN.value
    else:
        bull_state = BullBoardState.MURCIELAGO.value

    return ActionAdmissionResult(
        investable_signal_score=investable_signal_score,
        admission_tier=admission_tier,
        promotion_allowed=promotion_allowed,
        action_allowed=action_allowed,
        fallback_required=fallback_required,
        precision_tools_allowed=precision_tools_allowed,
        feedback_learning_valid=feedback_learning_valid,
        bull_state=bull_state,
        recommended_next_action=recommended_next_action,
        reason_codes=list(dict.fromkeys(reasons)),
        formula_trace={
            "weakest_path_penalty": weakest_path_penalty,
            "hidden_drift_penalty": hidden_drift_penalty,
            "critical_square_penalty": critical_square_penalty,
            "investable_signal_score": investable_signal_score,
        },
    )


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_board_control_input(
    row: dict[str, Any], runtime_state: dict[str, Any] | None = None
) -> BoardControlInput:
    runtime_payload = runtime_state if isinstance(runtime_state, dict) else {}
    execution_policy = runtime_payload.get("execution_policy", {})
    if not isinstance(execution_policy, dict):
        execution_policy = {}
    policy_state = str(
        row.get("policy_state")
        or runtime_payload.get("policy_state")
        or execution_policy.get("policy_state")
        or "RESTRICTED"
    ).upper()
    policy_veto = policy_state in {"RESTRICTED", "DO_NOT_DEPLOY", "BLOCKED"}
    chaos_veto = bool(
        row.get("chaos_veto")
        or row.get("chaos_flag")
        or runtime_payload.get("structural_admission", {}).get("structural_admission_class") == "CHAOS_VETO"
    )
    truth_probability = clamp01(_coerce_float(row.get("truth_probability"), 0.5))
    signal_strength = clamp01(
        _coerce_float(row.get("signal_strength_score"), _coerce_float(row.get("signal_strength"), 0.5))
    )
    chaos_intensity = clamp01(_coerce_float(row.get("chaos_intensity"), 0.35))
    bluff_risk = clamp01(_coerce_float(row.get("bluff_risk"), 0.10))
    hallucination_risk = clamp01(_coerce_float(row.get("hallucination_risk"), 0.05))
    durability_score = clamp01(
        _coerce_float(
            row.get("durability_score"),
            _coerce_float(runtime_payload.get("durability_score"), 0.45),
        )
    )
    execution_survivability_score = clamp01(
        _coerce_float(
            row.get("execution_survivability_score"),
            _coerce_float(row.get("execution_readiness_score"), 0.35),
        )
    )
    return BoardControlInput(
        signal_id=str(row.get("signal_id") or row.get("ticker") or row.get("symbol") or "UNKNOWN"),
        timestamp=row.get("timestamp"),
        critical_square_control=clamp01(_coerce_float(row.get("critical_square_control"), truth_probability)),
        response_line_openness=clamp01(_coerce_float(row.get("response_line_openness"), 1.0 - chaos_intensity)),
        containment_strength=clamp01(_coerce_float(row.get("containment_strength"), 1.0 - bluff_risk)),
        core_protection=clamp01(_coerce_float(row.get("core_protection"), 1.0 - hallucination_risk)),
        access_surface_exposure=clamp01(_coerce_float(row.get("access_surface_exposure"), chaos_intensity)),
        impact_score=clamp01(_coerce_float(row.get("impact_score"), signal_strength)),
        access_score=clamp01(_coerce_float(row.get("access_score"), _coerce_float(row.get("repricing_headroom_score"), 0.45))),
        reversibility_score=clamp01(_coerce_float(row.get("reversibility_score"), 0.45)),
        protective_friction_score=clamp01(_coerce_float(row.get("protective_friction_score"), 0.40)),
        detection_score=clamp01(_coerce_float(row.get("detection_score"), signal_strength)),
        validation_score=clamp01(_coerce_float(row.get("validation_score"), truth_probability)),
        durability_score=durability_score,
        execution_survivability_score=execution_survivability_score,
        policy_veto=policy_veto,
        chaos_veto=chaos_veto,
        heat_risk_score=clamp01(_coerce_float(row.get("heat_risk_score"), 0.20)),
        notes=list(row.get("notes", [])) if isinstance(row.get("notes"), list) else [],
    )


def _build_default_paths(payload: BoardControlInput) -> list[PathGateInput]:
    return [
        PathGateInput(
            path_name="primary_path",
            admission_gate_strength=payload.validation_score,
            validation_gate_strength=payload.validation_score,
            execution_gate_strength=payload.execution_survivability_score,
            containment_gate_strength=payload.containment_strength,
            reversibility_strength=payload.reversibility_score,
        )
    ]


def _build_default_clearance_layers(
    payload: BoardControlInput, operator_precision_readiness: float
) -> list[ClearanceLayerInput]:
    return [
        ClearanceLayerInput("source_validation", payload.validation_score >= 0.50, payload.validation_score, True),
        ClearanceLayerInput("cross_system_risk", not payload.chaos_veto, 1.0 - payload.heat_risk_score, True),
        ClearanceLayerInput("access_surface_check", payload.access_surface_exposure < 0.70, 1.0 - payload.access_surface_exposure, True),
        ClearanceLayerInput("containment_check", payload.containment_strength >= 0.50, payload.containment_strength, True),
        ClearanceLayerInput("execution_readiness", payload.execution_survivability_score >= 0.50, payload.execution_survivability_score, True),
        ClearanceLayerInput("reversibility_check", payload.reversibility_score >= 0.45, payload.reversibility_score, True),
        ClearanceLayerInput("operator_state_check", operator_precision_readiness >= 0.50, operator_precision_readiness, True),
    ]


class BoardControlSafetyLayer:
    def evaluate(
        self,
        board_input: BoardControlInput,
        *,
        path_inputs: list[PathGateInput],
        clearance_layers: list[ClearanceLayerInput],
        feedback_input: FeedbackIntegrityInput,
        self_audit_input: SelfAuditInput,
        premise_input: PremiseTestingInput,
        contextual_input: ContextualInterpretationGuardInput,
        hidden_input: HiddenDisturbanceInput,
        baseline_input: BaselineViolationInput,
        error_events: list[ErrorEventInput],
        fallback_input: FallbackSwitchingInput,
        pressure_tools: list[PressureToolInput],
        ritual_input: RitualEffectivenessInput,
        mechanical_input: MechanicalCueInput,
        operator_input: OperatorStateTelemetryInput,
        conversion_input: ConversionFailureInput,
        protective_friction_input: ProtectiveFrictionInput,
    ) -> BoardControlSafetyReport:
        reason_codes: list[str] = []
        transition_log: list[str] = []

        board_control_score, board_reasons = compute_board_control_score(board_input)
        reason_codes.extend(board_reasons)
        transition_log.append(f"Board control score={board_control_score:.3f}.")

        critical_square_exposure, critical_reasons = compute_critical_square_exposure(board_input)
        reason_codes.extend(critical_reasons)
        transition_log.append(f"Critical square exposure={critical_square_exposure:.3f}.")

        weakest_path_score, weakest_reasons = audit_weakest_path(path_inputs)
        reason_codes.extend(weakest_reasons)

        (
            global_clearance,
            local_clearance_score,
            global_clearance_score,
            local_global_clearance_gap,
            clearance_reasons,
        ) = evaluate_clearance_guard(clearance_layers)
        reason_codes.extend(clearance_reasons)

        (
            feedback_integrity_score,
            review_theater_score,
            feedback_reasons,
            learning_valid,
        ) = evaluate_feedback_integrity(feedback_input)
        reason_codes.extend(feedback_reasons)

        self_audit_score, self_audit_reasons, self_audit_action_allowed = evaluate_self_audit(self_audit_input)
        reason_codes.extend(self_audit_reasons)

        premise_quality_score, outcome_quality_score, premise_reasons = evaluate_premise_testing(premise_input)
        reason_codes.extend(premise_reasons)

        (
            signal_durability,
            targeted_intent_probability,
            hostility_probability,
            action_worthiness_score,
            contextual_reasons,
        ) = evaluate_contextual_interpretation_guard(contextual_input)
        reason_codes.extend(contextual_reasons)

        error_rate_delta, hidden_disturbance_score, hidden_reasons = evaluate_hidden_disturbance(hidden_input)
        reason_codes.extend(hidden_reasons)

        execution_drift_score, baseline_violation_flag, baseline_reasons = evaluate_baseline_violation(baseline_input)
        reason_codes.extend(baseline_reasons)

        error_cluster_type, clustered_failure_likelihood, cluster_reasons, tool_failure_counts = classify_error_cluster(error_events)
        reason_codes.extend(cluster_reasons)

        active_mode, fallback_required, disabled_tools, allowed_tools, fallback_reasons = evaluate_fallback_switching(fallback_input)
        reason_codes.extend(fallback_reasons)

        tool_results = [evaluate_pressure_tool(tool) for tool in pressure_tools]
        for _, _, tool_reasons in tool_results:
            reason_codes.extend(tool_reasons)

        ritual_effectiveness_score, ritual_insufficient, ritual_reasons = evaluate_ritual_effectiveness(ritual_input)
        reason_codes.extend(ritual_reasons)

        mechanical_cue_score, cue_effective, cue_reasons = evaluate_mechanical_cue(mechanical_input)
        reason_codes.extend(cue_reasons)

        operator_precision_readiness, operator_reasons = evaluate_operator_state_telemetry(operator_input)
        reason_codes.extend(operator_reasons)

        conversion_failure_score, conversion_metrics, conversion_reasons = evaluate_conversion_failure(conversion_input)
        reason_codes.extend(conversion_reasons)

        friction_state, protective_friction_score, protective_reasons = classify_protective_friction(protective_friction_input)
        reason_codes.extend(protective_reasons)

        if action_worthiness_score < 0.45:
            reason_codes.append(BoardControlState.ACTION_WORTHINESS_LOW.value)
        if ritual_insufficient and not cue_effective:
            transition_log.append("Ritual completed without recovery; mechanical cue remains required.")
        if signal_durability >= 0.70 and hostility_probability < 0.40:
            transition_log.append("Durability confirmed without hostile intent escalation.")

        admission = evaluate_action_admission(
            detection_score=board_input.detection_score,
            validation_score=board_input.validation_score,
            durability_score=board_input.durability_score,
            execution_survivability_score=board_input.execution_survivability_score,
            board_control_score=board_control_score,
            global_clearance_score=global_clearance_score,
            operator_precision_readiness=operator_precision_readiness,
            weakest_path_score=weakest_path_score,
            hidden_disturbance_score=hidden_disturbance_score,
            critical_square_exposure=critical_square_exposure,
            premise_quality_score=premise_quality_score,
            policy_veto=board_input.policy_veto,
            chaos_veto=board_input.chaos_veto,
            fallback_required=fallback_required,
            review_theater_score=review_theater_score,
        )
        reason_codes.extend(admission.reason_codes)

        precision_tools_allowed = (
            admission.precision_tools_allowed
            and operator_precision_readiness >= 0.60
            and not fallback_required
        )

        if board_input.policy_veto or board_input.chaos_veto:
            final_state = BoardControlState.GLOBAL_CLEARANCE_BLOCKED.value
        elif not global_clearance:
            final_state = (
                BoardControlState.GLOBAL_CLEARANCE_BLOCKED.value
                if local_clearance_score >= 0.70 and global_clearance_score < 0.70
                else BoardControlState.PARTIAL_CLEARANCE_ONLY.value
            )
        elif critical_square_exposure >= 0.85:
            final_state = BoardControlState.CRITICAL_SQUARE_EXPOSED.value
        elif weakest_path_score < 0.30:
            final_state = BoardControlState.WEAKEST_PATH_EXPOSED.value
        elif hidden_disturbance_score >= 0.75:
            final_state = BoardControlState.MICRO_CHAOS_DETECTED.value
        elif hidden_disturbance_score >= 0.60:
            final_state = BoardControlState.HIDDEN_EXECUTION_DRIFT.value
        elif baseline_violation_flag:
            final_state = BoardControlState.BASELINE_VIOLATION.value
        elif review_theater_score >= 0.70:
            final_state = BoardControlState.REVIEW_THEATER_DETECTED.value
        elif ritual_insufficient and not cue_effective:
            final_state = BoardControlState.MECHANICAL_CUE_REQUIRED.value
        elif fallback_required:
            final_state = BoardControlState.DURABLE_FALLBACK_REQUIRED.value
        elif error_cluster_type == BoardControlState.TOUCH_DECEPTION_UNSTABLE.value:
            final_state = BoardControlState.TOUCH_DECEPTION_UNSTABLE.value
        elif conversion_failure_score >= 0.60:
            final_state = BoardControlState.CONVERSION_FAILURE_HIGH.value
        elif action_worthiness_score < 0.45:
            final_state = BoardControlState.ACTION_WORTHINESS_LOW.value
        elif board_control_score < 0.60 or friction_state == BoardControlState.PROTECTIVE_FRICTION_REQUIRED.value:
            final_state = BoardControlState.PROTECTIVE_FRICTION_REQUIRED.value
        else:
            final_state = BoardControlState.BOARD_CONTROL_ACCEPTABLE.value

        recommended_next_action = admission.recommended_next_action
        if board_input.policy_veto or board_input.chaos_veto:
            recommended_next_action = RecommendedAction.BLOCK_PROMOTION.value
        elif hidden_disturbance_score > 0.80 and not fallback_required:
            recommended_next_action = RecommendedAction.ACTIVATE_DURABLE_FALLBACK.value
        elif ritual_insufficient and not cue_effective:
            recommended_next_action = RecommendedAction.REQUIRE_MECHANICAL_CUE.value
        elif review_theater_score > 0.70:
            recommended_next_action = RecommendedAction.RUN_SELF_AUDIT.value
        elif weakest_path_score < 0.55 or critical_square_exposure > 0.70:
            recommended_next_action = RecommendedAction.ADD_PROTECTIVE_FRICTION.value

        effective_fallback_required = (
            fallback_required
            or hidden_disturbance_score >= 0.75
            or execution_drift_score >= 0.70
        )
        action_allowed = (
            admission.action_allowed
            and self_audit_action_allowed
            and action_worthiness_score >= 0.45
        )
        promotion_allowed = (
            admission.promotion_allowed
            and global_clearance
            and self_audit_action_allowed
            and action_worthiness_score >= 0.45
        )

        if board_input.policy_veto or board_input.chaos_veto or final_state == BoardControlState.GLOBAL_CLEARANCE_BLOCKED.value:
            bull_state = BullBoardState.DIABLO.value
        elif baseline_violation_flag and hidden_disturbance_score >= 0.75:
            bull_state = BullBoardState.ISLERO.value
        elif premise_quality_score < 0.50 or board_input.validation_score < 0.50:
            bull_state = BullBoardState.MIURA.value
        elif effective_fallback_required or hidden_disturbance_score >= 0.60:
            bull_state = BullBoardState.MURCIELAGO.value
        elif action_allowed and promotion_allowed and admission.investable_signal_score >= 0.85:
            bull_state = BullBoardState.AVENTADOR.value
        elif action_allowed and precision_tools_allowed and board_input.execution_survivability_score >= 0.70:
            bull_state = BullBoardState.GALLARDO.value
        elif (
            action_allowed
            and promotion_allowed
            and board_input.detection_score >= 0.80
            and board_input.validation_score >= 0.60
            and board_control_score >= 0.70
            and global_clearance
            and operator_precision_readiness >= 0.60
            and not board_input.policy_veto
            and not board_input.chaos_veto
            and not effective_fallback_required
        ):
            bull_state = BullBoardState.HURACAN.value
        else:
            bull_state = BullBoardState.MURCIELAGO.value

        transition_log.append(
            f"Admission tier={admission.admission_tier}, investable_score={admission.investable_signal_score:.3f}."
        )

        return BoardControlSafetyReport(
            signal_id=board_input.signal_id,
            timestamp=board_input.timestamp,
            input_summary={
                "notes": list(board_input.notes),
                "path_count": len(path_inputs),
                "critical_layer_count": sum(1 for layer in clearance_layers if layer.critical),
            },
            premise_quality_score=premise_quality_score,
            board_control_score=board_control_score,
            critical_square_exposure=critical_square_exposure,
            weakest_path_score=weakest_path_score,
            local_global_clearance_gap=local_global_clearance_gap,
            feedback_integrity_score=feedback_integrity_score,
            review_theater_score=review_theater_score,
            self_audit_score=self_audit_score,
            hidden_disturbance_score=hidden_disturbance_score,
            execution_drift_score=execution_drift_score,
            baseline_violation_flag=baseline_violation_flag,
            error_cluster_type=error_cluster_type,
            active_mode=active_mode,
            disabled_tools=disabled_tools,
            allowed_tools=allowed_tools,
            operator_precision_readiness=operator_precision_readiness,
            ritual_effectiveness_score=ritual_effectiveness_score,
            conversion_failure_score=conversion_failure_score,
            protective_friction_score=protective_friction_score,
            investable_signal_score=admission.investable_signal_score,
            final_state=final_state,
            bull_state=bull_state,
            promotion_allowed=promotion_allowed,
            action_allowed=action_allowed,
            fallback_required=effective_fallback_required,
            precision_tools_allowed=precision_tools_allowed,
            feedback_learning_valid=learning_valid and admission.feedback_learning_valid,
            reason_codes=list(dict.fromkeys(reason_codes)),
            recommended_next_action=recommended_next_action,
            formula_trace={
                "board_control_score": board_control_score,
                "critical_square_exposure": critical_square_exposure,
                "weakest_path_score": weakest_path_score,
                "local_clearance_score": local_clearance_score,
                "global_clearance_score": global_clearance_score,
                "local_global_clearance_gap": local_global_clearance_gap,
                "feedback_integrity_score": feedback_integrity_score,
                "review_theater_score": review_theater_score,
                "self_audit_score": self_audit_score,
                "premise_quality_score": premise_quality_score,
                "outcome_quality_score": outcome_quality_score,
                "signal_durability": signal_durability,
                "targeted_intent_probability": targeted_intent_probability,
                "hostility_probability": hostility_probability,
                "action_worthiness_score": action_worthiness_score,
                "error_rate_delta": error_rate_delta,
                "hidden_disturbance_score": hidden_disturbance_score,
                "execution_drift_score": execution_drift_score,
                "clustered_failure_likelihood": clustered_failure_likelihood,
                "ritual_effectiveness_score": ritual_effectiveness_score,
                "mechanical_cue_score": mechanical_cue_score,
                "operator_precision_readiness": operator_precision_readiness,
                "protective_friction_score": protective_friction_score,
                **conversion_metrics,
                **admission.formula_trace,
            },
            transition_log=transition_log,
        )


def summarize_board_control_safety_report(report: dict[str, Any]) -> str:
    return (
        "board_control_safety="
        f"state={report.get('board_control_final_state', BoardControlState.NO_BOARD_RISK_DETECTED.value)}, "
        f"score={report.get('board_control_score', 0.0)}, "
        f"weakest_path={report.get('weakest_path_score', 0.0)}, "
        f"hidden_drift={report.get('hidden_disturbance_score', 0.0)}, "
        f"action={report.get('board_control_recommended_next_action', RecommendedAction.HOLD_NO_ACTION.value)}"
    )


def build_board_control_safety_report(
    signal_rows: list[dict[str, Any]] | None,
    runtime_state: dict[str, Any] | None = None,
    write_runtime: bool = True,
    output_path: Path | None = None,
) -> dict[str, Any]:
    runtime_payload = runtime_state if isinstance(runtime_state, dict) else {}
    rows = [row for row in (signal_rows or []) if isinstance(row, dict)]
    engine = BoardControlSafetyLayer()
    per_signal_reports: list[BoardControlSafetyReport] = []

    for row in rows:
        board_input = _normalize_board_control_input(row, runtime_payload)
        operator_input = OperatorStateTelemetryInput(
            food_state_score=clamp01(_coerce_float(row.get("food_state_score"), 0.60)),
            hydration_score=clamp01(_coerce_float(row.get("hydration_score"), 0.60)),
            alcohol_penalty=clamp01(_coerce_float(row.get("alcohol_penalty"), 0.0)),
            sleep_quality_score=clamp01(_coerce_float(row.get("sleep_quality_score"), 0.60)),
            stress_score=clamp01(_coerce_float(row.get("stress_score"), _coerce_float(row.get("chaos_intensity"), 0.30))),
            warmup_quality_score=clamp01(_coerce_float(row.get("warmup_quality_score"), 0.60)),
        )
        operator_precision_readiness, _ = evaluate_operator_state_telemetry(operator_input)

        per_signal_reports.append(
            engine.evaluate(
                board_input,
                path_inputs=_build_default_paths(board_input),
                clearance_layers=_build_default_clearance_layers(board_input, operator_precision_readiness),
                feedback_input=FeedbackIntegrityInput(
                    root_cause_specificity=clamp01(_coerce_float(row.get("root_cause_specificity"), 0.55)),
                    ownership_clarity=clamp01(_coerce_float(row.get("ownership_clarity"), 0.55)),
                    verifiable_action_score=clamp01(_coerce_float(row.get("verifiable_action_score"), 0.55)),
                    deadline_clarity=clamp01(_coerce_float(row.get("deadline_clarity"), 0.55)),
                    blame_avoidance_penalty=clamp01(_coerce_float(row.get("blame_avoidance_penalty"), 0.10)),
                    vague_language_score=clamp01(_coerce_float(row.get("vague_language_score"), 0.20)),
                    no_owner_score=clamp01(_coerce_float(row.get("no_owner_score"), 0.20)),
                    no_deadline_score=clamp01(_coerce_float(row.get("no_deadline_score"), 0.20)),
                    no_verifiable_change_score=clamp01(_coerce_float(row.get("no_verifiable_change_score"), 0.20)),
                ),
                self_audit_input=SelfAuditInput(
                    premise_confidence=clamp01(_coerce_float(row.get("premise_confidence"), board_input.validation_score)),
                    boundary_integrity=clamp01(_coerce_float(row.get("boundary_integrity"), board_input.protective_friction_score)),
                    evidence_strength=clamp01(_coerce_float(row.get("evidence_strength"), board_input.validation_score)),
                    exposure_awareness=clamp01(_coerce_float(row.get("exposure_awareness"), 0.55)),
                    action_discipline=clamp01(_coerce_float(row.get("action_discipline"), board_input.execution_survivability_score)),
                    alternative_hypotheses_present=bool(row.get("alternative_hypotheses_present", True)),
                    avoidable_opening_reconstructed=bool(row.get("avoidable_opening_reconstructed", True)),
                    fallback_mode_considered=bool(row.get("fallback_mode_considered", True)),
                ),
                premise_input=PremiseTestingInput(
                    evidence_strength=clamp01(_coerce_float(row.get("evidence_strength"), board_input.validation_score)),
                    alternative_hypothesis_coverage=clamp01(_coerce_float(row.get("alternative_hypothesis_coverage"), 0.55)),
                    source_quality=clamp01(_coerce_float(row.get("source_quality"), board_input.critical_square_control)),
                    contradiction_check=clamp01(_coerce_float(row.get("contradiction_check"), 1.0 - board_input.access_surface_exposure)),
                    assumption_transparency=clamp01(_coerce_float(row.get("assumption_transparency"), 0.55)),
                    process_quality_score=clamp01(_coerce_float(row.get("process_quality_score"), board_input.durability_score)),
                    execution_quality_score=clamp01(_coerce_float(row.get("execution_quality_score"), board_input.execution_survivability_score)),
                ),
                contextual_input=ContextualInterpretationGuardInput(
                    pattern_strength=clamp01(_coerce_float(row.get("pattern_strength"), 0.55)),
                    context_relevance=clamp01(_coerce_float(row.get("context_relevance"), 0.55)),
                    signal_specificity=clamp01(_coerce_float(row.get("signal_specificity"), 0.45)),
                    consequence_score=clamp01(_coerce_float(row.get("consequence_score"), 0.45)),
                    repetition_score=clamp01(_coerce_float(row.get("repetition_score"), 0.55)),
                    cross_context_persistence=clamp01(_coerce_float(row.get("cross_context_persistence"), 0.55)),
                    source_consistency=clamp01(_coerce_float(row.get("source_consistency"), board_input.validation_score)),
                    time_persistence=clamp01(_coerce_float(row.get("time_persistence"), board_input.durability_score)),
                    timing_alignment=clamp01(_coerce_float(row.get("timing_alignment"), 0.45)),
                    target_repetition=clamp01(_coerce_float(row.get("target_repetition"), 0.35)),
                    general_habit_evidence=clamp01(_coerce_float(row.get("general_habit_evidence"), 0.25)),
                    negative_consequence_score=clamp01(_coerce_float(row.get("negative_consequence_score"), 0.30)),
                    adversarial_context_score=clamp01(_coerce_float(row.get("adversarial_context_score"), 0.30)),
                    signal_truth_score=clamp01(_coerce_float(row.get("signal_truth_score"), board_input.validation_score)),
                    strategic_relevance=clamp01(_coerce_float(row.get("strategic_relevance"), 0.55)),
                    expected_benefit=clamp01(_coerce_float(row.get("expected_benefit"), 0.55)),
                    reaction_cost=clamp01(_coerce_float(row.get("reaction_cost"), 0.20)),
                ),
                hidden_input=HiddenDisturbanceInput(
                    baseline_error_rate=clamp01(_coerce_float(row.get("baseline_error_rate"), 0.10)),
                    current_error_rate=clamp01(_coerce_float(row.get("current_error_rate"), 0.10)),
                    pressure_state_score=clamp01(_coerce_float(row.get("pressure_state_score"), _coerce_float(row.get("chaos_intensity"), 0.30))),
                    disturbance_sensitivity=clamp01(_coerce_float(row.get("disturbance_sensitivity"), 0.45)),
                    visible_reaction_score=clamp01(_coerce_float(row.get("visible_reaction_score"), 0.30)),
                ),
                baseline_input=BaselineViolationInput(
                    baseline_error_rate=clamp01(_coerce_float(row.get("baseline_error_rate"), 0.10)),
                    current_error_rate=clamp01(_coerce_float(row.get("current_error_rate"), 0.10)),
                    baseline_threshold=clamp01(_coerce_float(row.get("baseline_threshold"), 0.10)),
                ),
                error_events=[
                    ErrorEventInput(
                        error_type=str(event.get("error_type") or "unknown"),
                        tool_type=str(event.get("tool_type") or "precision"),
                        sequence_index=event.get("sequence_index"),
                        pressure_state=str(event.get("pressure_state") or "normal"),
                        context_label=str(event.get("context_label") or "default"),
                    )
                    for event in (row.get("error_events") if isinstance(row.get("error_events"), list) else [])
                    if isinstance(event, dict)
                ],
                fallback_input=FallbackSwitchingInput(
                    precision_tool_error_count=int(_coerce_float(row.get("precision_tool_error_count"), 0)),
                    fallback_activation_threshold=int(_coerce_float(row.get("fallback_activation_threshold"), 2)),
                ),
                pressure_tools=[
                    PressureToolInput(
                        tool_name=str(tool.get("tool_name") or "DEFAULT_PRECISION"),
                        tool_category=str(tool.get("tool_category") or "precision"),
                        base_skill=clamp01(_coerce_float(tool.get("base_skill"), 0.55)),
                        operator_state_score=operator_precision_readiness,
                        pressure_fit_score=clamp01(_coerce_float(tool.get("pressure_fit_score"), 0.55)),
                        recent_success_rate=clamp01(_coerce_float(tool.get("recent_success_rate"), 0.55)),
                        tool_fragility_score=clamp01(_coerce_float(tool.get("tool_fragility_score"), 0.45)),
                        pressure_state_score=clamp01(_coerce_float(tool.get("pressure_state_score"), 0.45)),
                        threshold=clamp01(_coerce_float(tool.get("threshold"), 0.50)),
                    )
                    for tool in (
                        row.get("pressure_tools")
                        if isinstance(row.get("pressure_tools"), list)
                        else [{"tool_name": "DEFAULT_PRECISION", "tool_category": "precision"}]
                    )
                    if isinstance(tool, dict)
                ],
                ritual_input=RitualEffectivenessInput(
                    ritual_completed=bool(row.get("ritual_completed", False)),
                    pre_ritual_error_rate=clamp01(_coerce_float(row.get("pre_ritual_error_rate"), 0.12)),
                    post_ritual_error_rate=clamp01(_coerce_float(row.get("post_ritual_error_rate"), 0.12)),
                    baseline_error_rate=clamp01(_coerce_float(row.get("baseline_error_rate"), 0.10)),
                    threshold=clamp01(_coerce_float(row.get("ritual_threshold"), 0.05)),
                ),
                mechanical_input=MechanicalCueInput(
                    cue_selected=row.get("cue_selected"),
                    cue_type=row.get("cue_type"),
                    cue_adherence_score=clamp01(_coerce_float(row.get("cue_adherence_score"), 0.0)),
                    post_cue_execution_quality=clamp01(_coerce_float(row.get("post_cue_execution_quality"), 0.0)),
                    ritual_insufficient=bool(row.get("ritual_insufficient", False)),
                    mental_reset_score=clamp01(_coerce_float(row.get("mental_reset_score"), 0.55)),
                    operator_state_score=operator_precision_readiness,
                ),
                operator_input=operator_input,
                conversion_input=ConversionFailureInput(
                    capability_score=clamp01(_coerce_float(row.get("capability_score"), 0.55)),
                    hinge_points_won=int(_coerce_float(row.get("hinge_points_won"), 0)),
                    hinge_points_played=int(_coerce_float(row.get("hinge_points_played"), 0)),
                    final_phase_error_rate=clamp01(_coerce_float(row.get("final_phase_error_rate"), 0.10)),
                    baseline_error_rate=clamp01(_coerce_float(row.get("baseline_error_rate"), 0.10)),
                    deuce_points_won=int(_coerce_float(row.get("deuce_points_won"), 0)),
                    deuce_points_played=int(_coerce_float(row.get("deuce_points_played"), 0)),
                    lead_protection_successes=int(_coerce_float(row.get("lead_protection_successes"), 0)),
                    lead_protection_attempts=int(_coerce_float(row.get("lead_protection_attempts"), 0)),
                    pressure_points_won=int(_coerce_float(row.get("pressure_points_won"), 0)),
                    pressure_points_played=int(_coerce_float(row.get("pressure_points_played"), 0)),
                    threshold=clamp01(_coerce_float(row.get("conversion_threshold"), 0.05)),
                ),
                protective_friction_input=ProtectiveFrictionInput(
                    friction_location=str(row.get("friction_location") or "entry_path"),
                    critical_path_flag=bool(row.get("critical_path_flag", True)),
                    risk_reduction_score=clamp01(_coerce_float(row.get("risk_reduction_score"), board_input.protective_friction_score)),
                    opportunity_drag_score=clamp01(_coerce_float(row.get("opportunity_drag_score"), 0.25)),
                    critical_square_exposure=compute_critical_square_exposure(board_input)[0],
                    protective_friction_score=board_input.protective_friction_score,
                ),
            )
        )

    primary = (
        min(
            per_signal_reports,
            key=lambda report: (
                0 if not report.action_allowed else 1,
                0 if not report.promotion_allowed else 1,
                report.investable_signal_score,
                report.board_control_score,
            ),
        )
        if per_signal_reports
        else None
    )
    counts = {
        "blocked_count": sum(1 for report in per_signal_reports if not report.promotion_allowed),
        "fallback_required_count": sum(1 for report in per_signal_reports if report.fallback_required),
        "precision_tools_disabled_count": sum(1 for report in per_signal_reports if not report.precision_tools_allowed),
        "critical_square_exposed_count": sum(1 for report in per_signal_reports if report.critical_square_exposure >= 0.70),
    }

    payload: dict[str, Any] = {
        "board_control_score": round(primary.board_control_score, 4) if primary else 0.0,
        "critical_square_exposure": round(primary.critical_square_exposure, 4) if primary else 0.0,
        "weakest_path_score": round(primary.weakest_path_score, 4) if primary else 0.0,
        "local_global_clearance_gap": round(primary.local_global_clearance_gap, 4) if primary else 0.0,
        "feedback_integrity_score": round(primary.feedback_integrity_score, 4) if primary else 0.0,
        "review_theater_score": round(primary.review_theater_score, 4) if primary else 0.0,
        "hidden_disturbance_score": round(primary.hidden_disturbance_score, 4) if primary else 0.0,
        "execution_drift_score": round(primary.execution_drift_score, 4) if primary else 0.0,
        "baseline_violation_flag": bool(primary.baseline_violation_flag) if primary else False,
        "error_cluster_type": primary.error_cluster_type if primary else BoardControlState.NO_BOARD_RISK_DETECTED.value,
        "board_control_active_mode": primary.active_mode if primary else BoardControlState.BOARD_CONTROL_ACCEPTABLE.value,
        "board_control_disabled_tools": primary.disabled_tools if primary else [],
        "board_control_allowed_tools": primary.allowed_tools if primary else [],
        "operator_precision_readiness": round(primary.operator_precision_readiness, 4) if primary else 0.0,
        "ritual_effectiveness_score": round(primary.ritual_effectiveness_score, 4) if primary else 0.0,
        "conversion_failure_score": round(primary.conversion_failure_score, 4) if primary else 0.0,
        "protective_friction_score": round(primary.protective_friction_score, 4) if primary else 0.0,
        "investable_signal_score": round(primary.investable_signal_score, 4) if primary else 0.0,
        "board_control_final_state": primary.final_state if primary else BoardControlState.NO_BOARD_RISK_DETECTED.value,
        "board_control_bull_state": primary.bull_state if primary else BullBoardState.DIABLO.value,
        "board_control_promotion_allowed": bool(primary.promotion_allowed) if primary else False,
        "board_control_action_allowed": bool(primary.action_allowed) if primary else False,
        "board_control_fallback_required": bool(primary.fallback_required) if primary else False,
        "board_control_recommended_next_action": primary.recommended_next_action if primary else RecommendedAction.HOLD_NO_ACTION.value,
        "signals_evaluated": len(per_signal_reports),
        "board_control_counts": counts,
        "board_control_safety": (
            f"state={primary.final_state}, score={primary.board_control_score:.4f}, "
            f"weakest_path={primary.weakest_path_score:.4f}, "
            f"hidden_drift={primary.hidden_disturbance_score:.4f}, "
            f"action={primary.recommended_next_action}"
            if primary
            else (
                "state=NO_BOARD_RISK_DETECTED, score=0.0000, "
                "weakest_path=0.0000, hidden_drift=0.0000, action=HOLD_NO_ACTION"
            )
        ),
        "per_signal_reports": [report.to_dict() for report in per_signal_reports],
        "report_path": repo_relative(output_path or BOARD_CONTROL_SAFETY_REPORT_PATH),
    }
    stamped = stamp_payload(payload, runtime_state=runtime_payload)
    if write_runtime:
        write_json_atomic(output_path or BOARD_CONTROL_SAFETY_REPORT_PATH, stamped)
    return stamped


__all__ = [
    "ActionAdmissionResult",
    "BaselineViolationInput",
    "BoardControlInput",
    "BoardControlSafetyLayer",
    "BoardControlSafetyReport",
    "BoardControlState",
    "BullBoardState",
    "ClearanceLayerInput",
    "ContextualInterpretationGuardInput",
    "ConversionFailureInput",
    "ErrorEventInput",
    "FallbackSwitchingInput",
    "FeedbackIntegrityInput",
    "HiddenDisturbanceInput",
    "MechanicalCueInput",
    "OperatorStateTelemetryInput",
    "PathGateInput",
    "PremiseTestingInput",
    "PressureToolInput",
    "ProtectiveFrictionInput",
    "RecommendedAction",
    "RitualEffectivenessInput",
    "SelfAuditInput",
    "audit_weakest_path",
    "build_board_control_safety_report",
    "classify_error_cluster",
    "classify_protective_friction",
    "clamp01",
    "compute_board_control_score",
    "compute_critical_square_exposure",
    "evaluate_action_admission",
    "evaluate_baseline_violation",
    "evaluate_clearance_guard",
    "evaluate_contextual_interpretation_guard",
    "evaluate_conversion_failure",
    "evaluate_feedback_integrity",
    "evaluate_fallback_switching",
    "evaluate_hidden_disturbance",
    "evaluate_mechanical_cue",
    "evaluate_operator_state_telemetry",
    "evaluate_premise_testing",
    "evaluate_pressure_tool",
    "evaluate_ritual_effectiveness",
    "evaluate_self_audit",
    "safe_divide",
    "summarize_board_control_safety_report",
    "weighted_mean",
]
