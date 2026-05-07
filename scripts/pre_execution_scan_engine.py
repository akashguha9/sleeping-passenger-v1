from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        PRE_EXECUTION_SCAN_REPORT_PATH,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        PRE_EXECUTION_SCAN_REPORT_PATH,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )


EPSILON = 1e-6


class ScanReadiness(str, Enum):
    BLIND = "BLIND"
    PARTIAL = "PARTIAL"
    MAPPED = "MAPPED"
    HIGH_AWARENESS = "HIGH_AWARENESS"
    OVER_SCANNING = "OVER_SCANNING"


class PressureState(str, Enum):
    NO_PRESSURE = "NO_PRESSURE"
    MANAGEABLE = "MANAGEABLE"
    COMPRESSED = "COMPRESSED"
    TRAP_FORMING = "TRAP_FORMING"
    OVERLOADED = "OVERLOADED"
    CHAOS = "CHAOS"


class TurnDecision(str, Enum):
    TURN_ALLOWED = "TURN_ALLOWED"
    RECYCLE = "RECYCLE"
    HOLD = "HOLD"
    EXIT_FIRST = "EXIT_FIRST"
    NO_TURN = "NO_TURN"
    QUARANTINE = "QUARANTINE"


class SurpriseBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BoardControlState(str, Enum):
    CONTROLLED = "CONTROLLED"
    BALANCED = "BALANCED"
    EXPOSED = "EXPOSED"
    COLLAPSING = "COLLAPSING"
    UNKNOWN = "UNKNOWN"


class PreExecutionDecision(str, Enum):
    REJECT = "REJECT"
    WAIT = "WAIT"
    RESCAN = "RESCAN"
    RECYCLE = "RECYCLE"
    VALIDATE_MORE = "VALIDATE_MORE"
    PROMOTE_TO_EXECUTION = "PROMOTE_TO_EXECUTION"
    EXECUTE_READY = "EXECUTE_READY"
    QUARANTINE = "QUARANTINE"


class PreExecutionArchetype(str, Enum):
    MIURA_BLIND_RAW_SIGNAL = "MIURA_BLIND_RAW_SIGNAL"
    MURCIELAGO_MAPPED_UNDER_PRESSURE = "MURCIELAGO_MAPPED_UNDER_PRESSURE"
    AVENTADOR_PREPARED_ACTIONABLE = "AVENTADOR_PREPARED_ACTIONABLE"
    GALLARDO_CLEAN_EXECUTION_READY = "GALLARDO_CLEAN_EXECUTION_READY"
    ISLERO_SHOCK_REMAP = "ISLERO_SHOCK_REMAP"
    DIABLO_CHAOS_NO_TURN = "DIABLO_CHAOS_NO_TURN"
    HURACAN_FAST_TRACK_WITH_SCAN_FLOOR = "HURACAN_FAST_TRACK_WITH_SCAN_FLOOR"
    UNKNOWN_PRE_EXECUTION_STATE = "UNKNOWN_PRE_EXECUTION_STATE"


@dataclass(slots=True)
class PreExecutionScanConfig:
    min_scan_quality_for_action: float = 0.65
    min_board_control_for_action: float = 0.60
    min_optionality_for_action: float = 0.55
    max_surprise_risk_for_action: float = 0.40
    max_pressure_for_turn: float = 0.65
    max_trap_risk_for_turn: float = 0.55
    max_collision_risk_for_turn: float = 0.55
    min_validation_for_fast_track: float = 0.60
    min_durability_for_fast_track: float = 0.55
    min_scan_floor_for_fast_track: float = 0.58
    max_heat_risk_for_action: float = 0.70
    max_contradiction_for_action: float = 0.45
    max_scan_recency_seconds: float = 45.0
    min_time_to_execution_seconds: float = 0.0
    information_decay_floor: float = 0.15
    pre_scan_quality_weights: dict[str, float] = field(
        default_factory=lambda: {
            "scan_frequency": 0.25,
            "scan_accuracy": 0.30,
            "context_freshness": 0.25,
            "scan_recency": 0.20,
        }
    )
    mini_map_weights: dict[str, float] = field(
        default_factory=lambda: {
            "actor_coverage": 0.25,
            "spatial_coverage": 0.25,
            "exit_lane_quality": 0.25,
            "collision_safety": 0.25,
        }
    )
    pressure_awareness_weights: dict[str, float] = field(
        default_factory=lambda: {
            "inverse_pressure": 0.25,
            "inverse_closing_speed": 0.20,
            "inverse_angle_risk": 0.20,
            "direction_confidence": 0.20,
            "inverse_trap_risk": 0.15,
        }
    )
    board_control_weights: dict[str, float] = field(
        default_factory=lambda: {
            "zone_control_ratio": 0.45,
            "inverse_exposure_ratio": 0.25,
            "containment_strength": 0.30,
        }
    )
    optionality_weights: dict[str, float] = field(
        default_factory=lambda: {
            "safe_action_ratio": 0.35,
            "best_action_quality": 0.25,
            "fallback_quality": 0.20,
            "recycle_quality": 0.20,
        }
    )
    final_score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "pre_scan_quality": 0.18,
            "mini_map_quality": 0.16,
            "pressure_awareness": 0.14,
            "inverse_surprise_risk": 0.14,
            "board_control": 0.14,
            "optionality": 0.10,
            "turn_safety": 0.06,
            "hidden_preconditions": 0.05,
            "execution_timing": 0.03,
        }
    )


@dataclass(slots=True)
class PreExecutionScanInput:
    signal_id: str
    timestamp: datetime | str
    raw_signal_strength: float
    signal_confidence: float
    validation_score: float
    durability_score: float
    execution_readiness_score: float
    scan_count: int
    scan_frequency_per_minute: float
    scan_recency_seconds: float
    scan_accuracy_score: float
    context_freshness_score: float
    information_decay_rate: float
    known_actor_count: int
    estimated_total_actor_count: int
    teammate_alignment_score: float
    opponent_pressure_score: float
    exit_lane_count: int
    safe_exit_lane_count: int
    collision_risk_score: float
    spatial_coverage_score: float
    pressure_magnitude: float
    pressure_closing_speed: float
    pressure_angle_risk: float
    pressure_direction_confidence: float
    trap_risk_score: float
    critical_zones_total: int
    critical_zones_controlled: int
    critical_zones_exposed: int
    containment_strength_score: float
    safe_action_count: int
    total_action_count: int
    best_action_quality_score: float
    fallback_quality_score: float
    recycle_quality_score: float
    policy_veto: bool
    chaos_veto: bool
    shock_event: bool
    heat_risk_score: float
    volatility_score: float
    contradiction_score: float
    time_to_execution_seconds: float
    execution_half_life_seconds: float
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PreExecutionScanReport:
    signal_id: str
    scan_readiness: ScanReadiness
    pressure_state: PressureState
    turn_decision: TurnDecision
    surprise_band: SurpriseBand
    board_control_state: BoardControlState
    pre_execution_decision: PreExecutionDecision
    pre_execution_archetype: PreExecutionArchetype
    pre_scan_quality_score: float
    mini_map_quality_score: float
    pressure_awareness_score: float
    surprise_risk_score: float
    board_control_score: float
    optionality_score: float
    turn_safety_score: float
    hidden_preconditions_score: float
    execution_timing_score: float
    pre_execution_quality_score: float
    final_pre_execution_score: float
    scan_gate_pass: bool
    pressure_gate_pass: bool
    board_control_gate_pass: bool
    optionality_gate_pass: bool
    timing_gate_pass: bool
    hard_veto_pass: bool
    action_permission: bool
    hard_veto_reasons: list[str]
    warnings: list[str]
    recommended_next_steps: list[str]
    formula_trace: dict[str, float]
    transition_log: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scan_readiness"] = self.scan_readiness.value
        payload["pressure_state"] = self.pressure_state.value
        payload["turn_decision"] = self.turn_decision.value
        payload["surprise_band"] = self.surprise_band.value
        payload["board_control_state"] = self.board_control_state.value
        payload["pre_execution_decision"] = self.pre_execution_decision.value
        payload["pre_execution_archetype"] = self.pre_execution_archetype.value
        return payload


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(float(denominator)) <= EPSILON:
        return float(default)
    return float(numerator) / float(denominator)


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in weights.values())
    if total <= EPSILON:
        return {key: 0.0 for key in weights}
    return {key: max(0.0, float(value)) / total for key, value in weights.items()}


def weighted_sum(values: dict[str, float], weights: dict[str, float]) -> float:
    normalized = normalize_weights(weights)
    return clamp01(
        sum(clamp01(values.get(key, 0.0)) * weight for key, weight in normalized.items())
    )


def weighted_geometric_score(
    values: dict[str, float], weights: dict[str, float], epsilon: float = EPSILON
) -> float:
    normalized = normalize_weights(weights)
    if not normalized:
        return 0.0
    import math

    weighted_logs = 0.0
    for key, weight in normalized.items():
        weighted_logs += weight * math.log(max(clamp01(values.get(key, 0.0)), epsilon))
    return clamp01(math.exp(weighted_logs))


def compute_scan_frequency_effect(scan_frequency_per_minute: float, k: float = 3.0) -> float:
    value = max(0.0, float(scan_frequency_per_minute))
    return clamp01(value / (value + max(k, EPSILON)))


def compute_scan_recency_score(
    scan_recency_seconds: float, max_scan_recency_seconds: float
) -> float:
    if max_scan_recency_seconds <= EPSILON:
        return 0.0
    return 1.0 - clamp01(float(scan_recency_seconds) / float(max_scan_recency_seconds))


def _to_timestamp_string(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def compute_pre_scan_quality(
    scan_input: PreExecutionScanInput, config: PreExecutionScanConfig
) -> tuple[float, dict[str, float]]:
    scan_frequency_effect = compute_scan_frequency_effect(
        scan_input.scan_frequency_per_minute
    )
    scan_recency_score = compute_scan_recency_score(
        scan_input.scan_recency_seconds, config.max_scan_recency_seconds
    )
    update_speed_score = clamp01(scan_frequency_effect * scan_recency_score)
    values = {
        "scan_frequency": scan_frequency_effect,
        "scan_accuracy": clamp01(scan_input.scan_accuracy_score),
        "context_freshness": clamp01(scan_input.context_freshness_score),
        "scan_recency": scan_recency_score,
    }
    score = weighted_sum(values, config.pre_scan_quality_weights)
    return score, {
        "scan_frequency_effect": scan_frequency_effect,
        "scan_recency_score": scan_recency_score,
        "update_speed_score": update_speed_score,
        "pre_scan_quality_score": score,
    }


def compute_mini_map_quality(
    scan_input: PreExecutionScanInput, config: PreExecutionScanConfig
) -> tuple[float, dict[str, float]]:
    actor_coverage = clamp01(
        safe_div(scan_input.known_actor_count, scan_input.estimated_total_actor_count, 0.0)
    )
    exit_lane_quality = clamp01(
        safe_div(scan_input.safe_exit_lane_count, scan_input.exit_lane_count, 0.0)
    )
    collision_safety = 1.0 - clamp01(scan_input.collision_risk_score)
    weighted_score = weighted_sum(
        {
            "actor_coverage": actor_coverage,
            "spatial_coverage": clamp01(scan_input.spatial_coverage_score),
            "exit_lane_quality": exit_lane_quality,
            "collision_safety": collision_safety,
        },
        config.mini_map_weights,
    )
    geometric_score = weighted_geometric_score(
        {
            "actor_coverage": actor_coverage,
            "spatial_coverage": clamp01(scan_input.spatial_coverage_score),
            "exit_lane_quality": exit_lane_quality,
            "collision_safety": collision_safety,
        },
        {
            "actor_coverage": 0.25,
            "spatial_coverage": 0.25,
            "exit_lane_quality": 0.25,
            "collision_safety": 0.25,
        },
    )
    return weighted_score, {
        "actor_coverage": actor_coverage,
        "known_actor_coverage": actor_coverage,
        "exit_lane_quality": exit_lane_quality,
        "collision_safety": collision_safety,
        "mini_map_weighted_score": weighted_score,
        "mini_map_geometric_score": geometric_score,
    }


def compute_pressure_awareness(
    scan_input: PreExecutionScanInput, config: PreExecutionScanConfig
) -> tuple[float, dict[str, float]]:
    inverse_pressure = 1.0 - clamp01(scan_input.pressure_magnitude)
    inverse_closing_speed = 1.0 - clamp01(scan_input.pressure_closing_speed)
    inverse_angle_risk = 1.0 - clamp01(scan_input.pressure_angle_risk)
    direction_confidence = clamp01(scan_input.pressure_direction_confidence)
    inverse_trap_risk = 1.0 - clamp01(scan_input.trap_risk_score)
    score = weighted_sum(
        {
            "inverse_pressure": inverse_pressure,
            "inverse_closing_speed": inverse_closing_speed,
            "inverse_angle_risk": inverse_angle_risk,
            "direction_confidence": direction_confidence,
            "inverse_trap_risk": inverse_trap_risk,
        },
        config.pressure_awareness_weights,
    )
    return score, {
        "inverse_pressure": inverse_pressure,
        "inverse_closing_speed": inverse_closing_speed,
        "inverse_angle_risk": inverse_angle_risk,
        "direction_confidence": direction_confidence,
        "inverse_trap_risk": inverse_trap_risk,
        "pressure_awareness_score": score,
    }


def compute_surprise_risk(
    scan_input: PreExecutionScanInput, config: PreExecutionScanConfig
) -> tuple[float, dict[str, float]]:
    scan_frequency_effect = compute_scan_frequency_effect(
        scan_input.scan_frequency_per_minute
    )
    known_actor_coverage = clamp01(
        safe_div(scan_input.known_actor_count, scan_input.estimated_total_actor_count, 0.0)
    )
    information_staleness = clamp01(
        safe_div(scan_input.scan_recency_seconds, config.max_scan_recency_seconds, 0.0)
    )
    raw_surprise_risk = clamp01(
        0.35 * (1.0 - known_actor_coverage)
        + 0.25 * information_staleness
        + 0.20 * (1.0 - clamp01(scan_input.scan_accuracy_score))
        + 0.20 * (1.0 - clamp01(scan_input.context_freshness_score))
    )
    adjusted_surprise_risk = clamp01(
        raw_surprise_risk * (1.0 - 0.35 * scan_frequency_effect)
    )
    mapped_variable_ratio = clamp01(
        0.50 * known_actor_coverage
        + 0.25 * clamp01(scan_input.spatial_coverage_score)
        + 0.25 * clamp01(scan_input.pressure_direction_confidence)
    )
    unknown_variable_ratio = 1.0 - mapped_variable_ratio
    return adjusted_surprise_risk, {
        "scan_frequency_effect": scan_frequency_effect,
        "known_actor_coverage": known_actor_coverage,
        "unknown_variable_ratio": unknown_variable_ratio,
        "information_staleness": information_staleness,
        "raw_surprise_risk": raw_surprise_risk,
        "adjusted_surprise_risk": adjusted_surprise_risk,
        "mapped_variable_ratio": mapped_variable_ratio,
    }


def compute_board_control(
    scan_input: PreExecutionScanInput, config: PreExecutionScanConfig
) -> tuple[float, BoardControlState, dict[str, float]]:
    if scan_input.critical_zones_total <= 0:
        return 0.0, BoardControlState.UNKNOWN, {
            "critical_square_coverage": 0.0,
            "exposure_ratio": 1.0,
            "board_control_score": 0.0,
        }
    critical_square_coverage = clamp01(
        safe_div(
            scan_input.critical_zones_controlled,
            scan_input.critical_zones_total,
            0.0,
        )
    )
    exposure_ratio = clamp01(
        safe_div(
            scan_input.critical_zones_exposed,
            scan_input.critical_zones_total,
            0.0,
        )
    )
    score = weighted_sum(
        {
            "zone_control_ratio": critical_square_coverage,
            "inverse_exposure_ratio": 1.0 - exposure_ratio,
            "containment_strength": clamp01(scan_input.containment_strength_score),
        },
        config.board_control_weights,
    )
    if score >= 0.75 and exposure_ratio <= 0.20:
        state = BoardControlState.CONTROLLED
    elif score >= 0.55:
        state = BoardControlState.BALANCED
    elif score >= 0.35:
        state = BoardControlState.EXPOSED
    else:
        state = BoardControlState.COLLAPSING
    return score, state, {
        "critical_square_coverage": critical_square_coverage,
        "exposure_ratio": exposure_ratio,
        "board_control_score": score,
    }


def compute_optionality(
    scan_input: PreExecutionScanInput, config: PreExecutionScanConfig
) -> tuple[float, dict[str, float]]:
    safe_action_ratio = clamp01(
        safe_div(scan_input.safe_action_count, scan_input.total_action_count, 0.0)
    )
    score = weighted_sum(
        {
            "safe_action_ratio": safe_action_ratio,
            "best_action_quality": clamp01(scan_input.best_action_quality_score),
            "fallback_quality": clamp01(scan_input.fallback_quality_score),
            "recycle_quality": clamp01(scan_input.recycle_quality_score),
        },
        config.optionality_weights,
    )
    return score, {
        "safe_action_ratio": safe_action_ratio,
        "optionality_score": score,
    }


def compute_turn_safety(
    scan_input: PreExecutionScanInput,
    config: PreExecutionScanConfig,
    intermediate_scores: dict[str, float],
) -> tuple[float, TurnDecision, dict[str, float]]:
    turn_safety_score = weighted_sum(
        {
            "mini_map_quality": intermediate_scores.get("mini_map_quality_score", 0.0),
            "board_control": intermediate_scores.get("board_control_score", 0.0),
            "optionality": intermediate_scores.get("optionality_score", 0.0),
            "pressure_awareness": intermediate_scores.get("pressure_awareness_score", 0.0),
            "validation": clamp01(scan_input.validation_score),
        },
        {
            "mini_map_quality": 0.30,
            "board_control": 0.25,
            "optionality": 0.20,
            "pressure_awareness": 0.15,
            "validation": 0.10,
        },
    )
    capped = turn_safety_score
    if (
        scan_input.pressure_magnitude > config.max_pressure_for_turn
        or scan_input.trap_risk_score > config.max_trap_risk_for_turn
        or scan_input.collision_risk_score > config.max_collision_risk_for_turn
    ):
        capped = min(capped, 0.49)
    if scan_input.policy_veto or scan_input.chaos_veto or scan_input.shock_event:
        decision = TurnDecision.QUARANTINE
    elif (
        capped >= 0.65
        and scan_input.pressure_magnitude <= config.max_pressure_for_turn
        and scan_input.trap_risk_score <= config.max_trap_risk_for_turn
        and scan_input.collision_risk_score <= config.max_collision_risk_for_turn
    ):
        decision = TurnDecision.TURN_ALLOWED
    elif (
        scan_input.collision_risk_score > config.max_collision_risk_for_turn
        or scan_input.trap_risk_score > config.max_trap_risk_for_turn
    ) and scan_input.safe_exit_lane_count > 0:
        decision = TurnDecision.EXIT_FIRST
    elif scan_input.pressure_magnitude > config.max_pressure_for_turn and scan_input.recycle_quality_score >= 0.55:
        decision = TurnDecision.RECYCLE
    elif intermediate_scores.get("optionality_score", 0.0) < config.min_optionality_for_action and scan_input.pressure_magnitude < 0.65:
        decision = TurnDecision.HOLD
    else:
        decision = TurnDecision.NO_TURN
    return capped, decision, {"turn_safety_score": capped}


def compute_hidden_preconditions_score(
    scores: dict[str, float], config: PreExecutionScanConfig
) -> tuple[float, dict[str, float]]:
    hidden_preconditions_score = weighted_geometric_score(
        {
            "pre_scan_quality_score": scores.get("pre_scan_quality_score", 0.0),
            "mini_map_quality_score": scores.get("mini_map_quality_score", 0.0),
            "board_control_score": scores.get("board_control_score", 0.0),
            "optionality_score": scores.get("optionality_score", 0.0),
            "pressure_awareness_score": scores.get("pressure_awareness_score", 0.0),
        },
        {
            "pre_scan_quality_score": 0.20,
            "mini_map_quality_score": 0.20,
            "board_control_score": 0.20,
            "optionality_score": 0.20,
            "pressure_awareness_score": 0.20,
        },
    )
    execution_ceiling = clamp01(
        hidden_preconditions_score * clamp01(scores.get("execution_readiness_score", 0.0))
    )
    return hidden_preconditions_score, {
        "hidden_preconditions_score": hidden_preconditions_score,
        "execution_ceiling": execution_ceiling,
    }


def compute_execution_timing_score(
    scan_input: PreExecutionScanInput, config: PreExecutionScanConfig
) -> tuple[float, dict[str, float]]:
    warnings: dict[str, float] = {}
    if scan_input.execution_half_life_seconds <= 0:
        return 0.50, {"opportunity_half_life_risk": 0.50, "execution_timing_score": 0.50}
    opportunity_half_life_risk = safe_div(
        scan_input.time_to_execution_seconds,
        scan_input.execution_half_life_seconds,
        default=1.0,
    )
    execution_timing_score = 1.0 - clamp01(
        opportunity_half_life_risk
        * max(clamp01(scan_input.information_decay_rate), config.information_decay_floor)
    )
    if scan_input.time_to_execution_seconds <= 0:
        execution_timing_score = max(execution_timing_score, 0.50)
    warnings["opportunity_half_life_risk"] = clamp01(opportunity_half_life_risk)
    warnings["execution_timing_score"] = clamp01(execution_timing_score)
    return clamp01(execution_timing_score), warnings


def compute_failure_risk(
    scan_input: PreExecutionScanInput,
    scores: dict[str, float],
    config: PreExecutionScanConfig,
) -> tuple[float, dict[str, float]]:
    _ = config
    scan_frequency_effect = scores.get("scan_frequency_effect", 0.0)
    awareness_speed = clamp01(
        scan_frequency_effect
        * clamp01(scan_input.scan_accuracy_score)
        * clamp01(scan_input.context_freshness_score)
    )
    pressure_speed = clamp01(
        0.50 * clamp01(scan_input.pressure_closing_speed)
        + 0.30 * clamp01(scan_input.pressure_magnitude)
        + 0.20 * clamp01(scan_input.trap_risk_score)
    )
    failure_risk = clamp01(pressure_speed - awareness_speed + 0.50)
    return failure_risk, {
        "pressure_speed": pressure_speed,
        "awareness_speed": awareness_speed,
        "failure_risk": failure_risk,
    }


def classify_scan_readiness(
    pre_scan_quality: float,
    surprise_risk: float,
    telemetry_freshness: float,
    scan_count: int,
    execution_timing_score: float,
    hard_veto: bool,
) -> ScanReadiness:
    if (
        scan_count >= 8
        and pre_scan_quality >= 0.70
        and execution_timing_score < 0.40
        and not hard_veto
    ):
        return ScanReadiness.OVER_SCANNING
    if pre_scan_quality < 0.30 or surprise_risk > 0.80:
        return ScanReadiness.BLIND
    if pre_scan_quality < 0.55 or telemetry_freshness < 0.45:
        return ScanReadiness.PARTIAL
    if pre_scan_quality >= 0.75 and surprise_risk <= 0.30:
        return ScanReadiness.HIGH_AWARENESS
    return ScanReadiness.MAPPED


def classify_pressure_state(
    scan_input: PreExecutionScanInput, pressure_awareness: float, failure_risk: float
) -> PressureState:
    _ = pressure_awareness
    if scan_input.chaos_veto or scan_input.shock_event or scan_input.contradiction_score >= 0.80:
        return PressureState.CHAOS
    if scan_input.trap_risk_score >= 0.60:
        return PressureState.TRAP_FORMING
    if scan_input.pressure_magnitude >= 0.80 or failure_risk >= 0.80:
        return PressureState.OVERLOADED
    if scan_input.pressure_magnitude < 0.20 and scan_input.trap_risk_score < 0.20:
        return PressureState.NO_PRESSURE
    if scan_input.pressure_magnitude < 0.45 and failure_risk < 0.50:
        return PressureState.MANAGEABLE
    return PressureState.COMPRESSED


def classify_surprise_band(surprise_risk: float) -> SurpriseBand:
    if surprise_risk <= 0.25:
        return SurpriseBand.LOW
    if surprise_risk <= 0.45:
        return SurpriseBand.MODERATE
    if surprise_risk <= 0.70:
        return SurpriseBand.HIGH
    return SurpriseBand.CRITICAL


def compute_gates(
    scan_input: PreExecutionScanInput,
    scores: dict[str, float],
    config: PreExecutionScanConfig,
) -> dict[str, bool]:
    hard_veto_pass = not (
        scan_input.policy_veto or scan_input.chaos_veto or scan_input.shock_event
    )
    scan_gate_pass = scores.get("pre_scan_quality_score", 0.0) >= config.min_scan_quality_for_action
    pressure_gate_pass = (
        scores.get("surprise_risk_score", 1.0) <= config.max_surprise_risk_for_action
        and scan_input.pressure_magnitude <= config.max_pressure_for_turn
        and scan_input.trap_risk_score <= config.max_trap_risk_for_turn
    )
    board_control_gate_pass = scores.get("board_control_score", 0.0) >= config.min_board_control_for_action
    optionality_gate_pass = scores.get("optionality_score", 0.0) >= config.min_optionality_for_action
    timing_gate_pass = scores.get("execution_timing_score", 0.0) >= 0.45
    validation_gate_pass = clamp01(scan_input.validation_score) >= config.min_validation_for_fast_track
    durability_gate_pass = clamp01(scan_input.durability_score) >= config.min_durability_for_fast_track
    return {
        "scan_gate_pass": scan_gate_pass,
        "pressure_gate_pass": pressure_gate_pass,
        "board_control_gate_pass": board_control_gate_pass,
        "optionality_gate_pass": optionality_gate_pass,
        "timing_gate_pass": timing_gate_pass,
        "validation_gate_pass": validation_gate_pass,
        "durability_gate_pass": durability_gate_pass,
        "hard_veto_pass": hard_veto_pass,
    }


def map_pre_execution_decision(
    scan_input: PreExecutionScanInput,
    scores: dict[str, float],
    gates: dict[str, bool],
    enums: dict[str, Any],
) -> PreExecutionDecision:
    _ = enums
    if (
        not gates["hard_veto_pass"]
        or scan_input.chaos_veto
        or scan_input.shock_event
        or scan_input.policy_veto
    ):
        return PreExecutionDecision.QUARANTINE
    if scores["telemetry_freshness_score"] < 0.45 or scores["pre_scan_quality_score"] < 0.45:
        return PreExecutionDecision.RESCAN
    if scores["final_pre_execution_score"] < 0.30:
        return PreExecutionDecision.REJECT
    if scores["execution_timing_score"] < 0.45 and scores["pre_scan_quality_score"] >= 0.45:
        return PreExecutionDecision.WAIT
    if scores["turn_decision"] == TurnDecision.RECYCLE.value:
        return PreExecutionDecision.RECYCLE
    if not gates["validation_gate_pass"] or not gates["durability_gate_pass"]:
        return PreExecutionDecision.VALIDATE_MORE
    if all(
        gates[key]
        for key in (
            "scan_gate_pass",
            "pressure_gate_pass",
            "board_control_gate_pass",
            "optionality_gate_pass",
            "timing_gate_pass",
            "validation_gate_pass",
            "durability_gate_pass",
        )
    ):
        if clamp01(scan_input.execution_readiness_score) >= 0.78:
            return PreExecutionDecision.EXECUTE_READY
        return PreExecutionDecision.PROMOTE_TO_EXECUTION
    return PreExecutionDecision.WAIT


def map_pre_execution_archetype(
    scan_input: PreExecutionScanInput,
    scores: dict[str, float],
    gates: dict[str, bool],
    config: PreExecutionScanConfig,
) -> PreExecutionArchetype:
    if scan_input.shock_event or scan_input.contradiction_score >= 0.80:
        return PreExecutionArchetype.ISLERO_SHOCK_REMAP
    if scan_input.chaos_veto or scores["pressure_state"] == PressureState.CHAOS.value:
        return PreExecutionArchetype.DIABLO_CHAOS_NO_TURN
    fast_track_candidate = (
        scan_input.raw_signal_strength >= 0.80
        and scan_input.time_to_execution_seconds >= config.min_time_to_execution_seconds
        and scan_input.execution_half_life_seconds > 0
        and safe_div(
            scan_input.time_to_execution_seconds,
            scan_input.execution_half_life_seconds,
            default=1.0,
        )
        <= 0.75
        and clamp01(scan_input.validation_score) >= config.min_validation_for_fast_track
        and clamp01(scan_input.durability_score) >= config.min_durability_for_fast_track
        and scores["pre_scan_quality_score"] >= config.min_scan_floor_for_fast_track
        and scores["surprise_risk_score"] <= config.max_surprise_risk_for_action
        and scores["board_control_score"] >= config.min_board_control_for_action
        and not scan_input.policy_veto
        and not scan_input.chaos_veto
        and not scan_input.shock_event
    )
    if fast_track_candidate:
        return PreExecutionArchetype.HURACAN_FAST_TRACK_WITH_SCAN_FLOOR
    if scan_input.raw_signal_strength >= 0.75 and (
        scores["pre_scan_quality_score"] < 0.55 or scores["surprise_risk_score"] > 0.50
    ):
        return PreExecutionArchetype.MIURA_BLIND_RAW_SIGNAL
    if (
        all(
            gates[key]
            for key in (
                "scan_gate_pass",
                "pressure_gate_pass",
                "board_control_gate_pass",
                "optionality_gate_pass",
                "timing_gate_pass",
                "validation_gate_pass",
                "durability_gate_pass",
                "hard_veto_pass",
            )
        )
        and clamp01(scan_input.execution_readiness_score) >= 0.78
    ):
        return PreExecutionArchetype.GALLARDO_CLEAN_EXECUTION_READY
    stress_or_pressure_survival_proxy = 1.0 - max(
        clamp01(scan_input.pressure_magnitude),
        clamp01(scan_input.trap_risk_score),
        clamp01(scan_input.heat_risk_score),
    )
    murcielago_fit = clamp01(
        clamp01(scan_input.durability_score)
        * scores["pressure_awareness_score"]
        * stress_or_pressure_survival_proxy
    )
    if (
        max(clamp01(scan_input.pressure_magnitude), clamp01(scan_input.trap_risk_score)) >= 0.35
        and scores["pressure_state"] in {PressureState.MANAGEABLE.value, PressureState.COMPRESSED.value, PressureState.TRAP_FORMING.value}
        and scores["pre_scan_quality_score"] >= 0.58
        and scores["board_control_score"] >= 0.55
        and murcielago_fit >= 0.18
        and clamp01(scan_input.execution_readiness_score) < 0.70
    ):
        return PreExecutionArchetype.MURCIELAGO_MAPPED_UNDER_PRESSURE
    if (
        scores["pre_scan_quality_score"] >= 0.70
        and scores["board_control_score"] >= config.min_board_control_for_action
        and clamp01(scan_input.validation_score) >= 0.70
        and clamp01(scan_input.durability_score) >= 0.70
        and clamp01(scan_input.execution_readiness_score) < 0.78
    ):
        return PreExecutionArchetype.AVENTADOR_PREPARED_ACTIONABLE
    return PreExecutionArchetype.UNKNOWN_PRE_EXECUTION_STATE


def generate_recommended_next_steps(report: PreExecutionScanReport) -> list[str]:
    steps: list[str] = []
    if report.pre_execution_decision == PreExecutionDecision.QUARANTINE:
        steps.append("Respect policy/chaos/shock veto and do not promote action.")
    if report.scan_readiness in {ScanReadiness.BLIND, ScanReadiness.PARTIAL}:
        steps.append("Rescan before acting and refresh the environment map.")
    if report.turn_decision == TurnDecision.RECYCLE:
        steps.append("Recycle instead of turning into pressure.")
    if report.turn_decision == TurnDecision.EXIT_FIRST:
        steps.append("Use the exit lane first before attempting progression.")
    if not report.optionality_gate_pass:
        steps.append("Improve optionality before allowing execution.")
    if not report.board_control_gate_pass:
        steps.append("Control critical zones before promotion.")
    if not report.action_permission:
        steps.append("Hold action until scan, board, validation, and timing gates all pass.")
    if report.pre_execution_archetype == PreExecutionArchetype.HURACAN_FAST_TRACK_WITH_SCAN_FLOOR:
        steps.append("Fast-track is permitted only while the scan floor and validation floors remain intact.")
    return steps or ["No additional action required beyond normal monitoring."]


def summarize_pre_execution_report(report: PreExecutionScanReport) -> str:
    blockers = ", ".join(report.hard_veto_reasons[:2]) if report.hard_veto_reasons else "none"
    return (
        f"Pre-Execution Scan Report: {report.signal_id}\n"
        f"Scan Readiness: {report.scan_readiness.value}\n"
        f"Pressure State: {report.pressure_state.value}\n"
        f"Board Control: {report.board_control_state.value}\n"
        f"Turn Decision: {report.turn_decision.value}\n"
        f"Archetype: {report.pre_execution_archetype.value}\n"
        f"Final Score: {report.final_pre_execution_score:.3f}\n"
        f"Action Permission: {report.action_permission}\n"
        f"Main blockers: {blockers}"
    )


class PreExecutionScanEngine:
    """Rodri-style pre-execution scan layer.

    The real decision begins before the ball arrives. Detection without pre-scan
    is blind possession. Blind possession under pressure is exposure, not execution.
    """

    def __init__(self, config: PreExecutionScanConfig | None = None):
        self.config = config or PreExecutionScanConfig()

    def evaluate(self, scan_input: PreExecutionScanInput) -> PreExecutionScanReport:
        warnings: list[str] = []
        transition_log = [
            "Pre-scan quality computed from scan frequency, accuracy, freshness, and recency."
        ]

        pre_scan_quality_score, pre_scan_trace = compute_pre_scan_quality(
            scan_input, self.config
        )
        mini_map_quality_score, mini_map_trace = compute_mini_map_quality(
            scan_input, self.config
        )
        if mini_map_trace["mini_map_geometric_score"] < 0.25:
            warnings.append("Strict mini-map coherence is weak despite weighted map quality.")
            transition_log.append("Mini-map quality penalized by low actor coverage.")
        pressure_awareness_score, pressure_trace = compute_pressure_awareness(
            scan_input, self.config
        )
        surprise_risk_score, surprise_trace = compute_surprise_risk(
            scan_input, self.config
        )
        transition_log.append("Surprise risk reduced by repeated scans.")
        board_control_score, board_control_state, board_trace = compute_board_control(
            scan_input, self.config
        )
        optionality_score, optionality_trace = compute_optionality(
            scan_input, self.config
        )
        telemetry_freshness_score = clamp01(
            0.40 * pre_scan_trace["scan_recency_score"]
            + 0.30 * clamp01(scan_input.context_freshness_score)
            + 0.30 * (1.0 - max(clamp01(scan_input.information_decay_rate), self.config.information_decay_floor))
        )
        turn_safety_score, turn_decision, turn_trace = compute_turn_safety(
            scan_input,
            self.config,
            {
                "mini_map_quality_score": mini_map_quality_score,
                "board_control_score": board_control_score,
                "optionality_score": optionality_score,
                "pressure_awareness_score": pressure_awareness_score,
            },
        )
        if turn_decision == TurnDecision.NO_TURN:
            transition_log.append("Turn denied because trap risk exceeded threshold.")
        hidden_preconditions_score, hidden_trace = compute_hidden_preconditions_score(
            {
                "pre_scan_quality_score": pre_scan_quality_score,
                "mini_map_quality_score": mini_map_quality_score,
                "board_control_score": board_control_score,
                "optionality_score": optionality_score,
                "pressure_awareness_score": pressure_awareness_score,
                "execution_readiness_score": clamp01(scan_input.execution_readiness_score),
            },
            self.config,
        )
        execution_timing_score, timing_trace = compute_execution_timing_score(
            scan_input, self.config
        )
        if scan_input.execution_half_life_seconds <= 0:
            warnings.append("Execution half-life missing or non-positive; timing score set to neutral.")
        failure_risk, failure_trace = compute_failure_risk(
            scan_input,
            {"scan_frequency_effect": pre_scan_trace["scan_frequency_effect"]},
            self.config,
        )
        pressure_state = classify_pressure_state(
            scan_input, pressure_awareness_score, failure_risk
        )
        surprise_band = classify_surprise_band(surprise_risk_score)
        scan_readiness = classify_scan_readiness(
            pre_scan_quality_score,
            surprise_risk_score,
            telemetry_freshness_score,
            scan_input.scan_count,
            execution_timing_score,
            scan_input.policy_veto or scan_input.chaos_veto or scan_input.shock_event,
        )
        if scan_readiness == ScanReadiness.OVER_SCANNING:
            warnings.append("Scan quality is strong, but the action window is decaying.")

        pre_execution_quality_score = weighted_geometric_score(
            {
                "pre_scan_quality_score": pre_scan_quality_score,
                "pressure_awareness_score": pressure_awareness_score,
                "mini_map_quality_score": mini_map_quality_score,
                "execution_readiness_score": clamp01(scan_input.execution_readiness_score),
            },
            {
                "pre_scan_quality_score": 0.25,
                "pressure_awareness_score": 0.25,
                "mini_map_quality_score": 0.25,
                "execution_readiness_score": 0.25,
            },
        )
        final_weighted_raw = weighted_geometric_score(
            {
                "pre_scan_quality": pre_scan_quality_score,
                "mini_map_quality": mini_map_quality_score,
                "pressure_awareness": pressure_awareness_score,
                "inverse_surprise_risk": 1.0 - surprise_risk_score,
                "board_control": board_control_score,
                "optionality": optionality_score,
                "turn_safety": turn_safety_score,
                "hidden_preconditions": hidden_preconditions_score,
                "execution_timing": execution_timing_score,
            },
            self.config.final_score_weights,
        )
        final_pre_execution_score = min(
            final_weighted_raw,
            hidden_trace["execution_ceiling"] + 0.05,
        )
        unsafe_action_risk = clamp01(
            clamp01(scan_input.raw_signal_strength)
            * (1.0 - hidden_preconditions_score)
            * (1.0 - clamp01(scan_input.validation_score))
        )
        if unsafe_action_risk >= 0.25:
            warnings.append("Raw detection is outrunning context validation.")

        gates = compute_gates(
            scan_input,
            {
                "pre_scan_quality_score": pre_scan_quality_score,
                "surprise_risk_score": surprise_risk_score,
                "board_control_score": board_control_score,
                "optionality_score": optionality_score,
                "execution_timing_score": execution_timing_score,
            },
            self.config,
        )

        pre_execution_archetype = map_pre_execution_archetype(
            scan_input,
            {
                "pre_scan_quality_score": pre_scan_quality_score,
                "surprise_risk_score": surprise_risk_score,
                "board_control_score": board_control_score,
                "pressure_state": pressure_state.value,
                "pressure_awareness_score": pressure_awareness_score,
            },
            gates,
            self.config,
        )
        pre_execution_decision = map_pre_execution_decision(
            scan_input,
            {
                "telemetry_freshness_score": telemetry_freshness_score,
                "pre_scan_quality_score": pre_scan_quality_score,
                "final_pre_execution_score": final_pre_execution_score,
                "execution_timing_score": execution_timing_score,
                "turn_decision": turn_decision.value,
            },
            gates,
            {},
        )

        hard_veto_reasons: list[str] = []
        if scan_input.policy_veto:
            hard_veto_reasons.append("POLICY_VETO_ACTIVE")
        if scan_input.chaos_veto:
            hard_veto_reasons.append("CHAOS_VETO_ACTIVE")
        if scan_input.shock_event:
            hard_veto_reasons.append("SHOCK_EVENT_ACTIVE")
        if scan_input.contradiction_score > self.config.max_contradiction_for_action:
            hard_veto_reasons.append("CONTRADICTION_TOO_HIGH")
        if scan_input.heat_risk_score > self.config.max_heat_risk_for_action:
            hard_veto_reasons.append("HEAT_RISK_TOO_HIGH")

        if pre_execution_archetype == PreExecutionArchetype.DIABLO_CHAOS_NO_TURN:
            transition_log.append("Mapped to DIABLO because chaos veto was active.")
        if pre_execution_archetype == PreExecutionArchetype.ISLERO_SHOCK_REMAP:
            transition_log.append("Mapped to ISLERO because shock event forced remap.")
        if pre_execution_archetype == PreExecutionArchetype.MIURA_BLIND_RAW_SIGNAL:
            transition_log.append("Mapped to MIURA because raw detection outran environmental awareness.")
        if pre_execution_archetype == PreExecutionArchetype.MURCIELAGO_MAPPED_UNDER_PRESSURE:
            transition_log.append("Mapped to MURCIELAGO because pressure was high but scan and durability were acceptable.")
        if pre_execution_archetype == PreExecutionArchetype.GALLARDO_CLEAN_EXECUTION_READY:
            transition_log.append("Mapped to GALLARDO because all execution gates passed.")
        if telemetry_freshness_score < 0.45:
            transition_log.append("Decision set to RESCAN because telemetry freshness was below threshold.")

        murcielago_fit = clamp01(
            clamp01(scan_input.durability_score)
            * pressure_awareness_score
            * (
                1.0
                - max(
                    clamp01(scan_input.pressure_magnitude),
                    clamp01(scan_input.trap_risk_score),
                    clamp01(scan_input.heat_risk_score),
                )
            )
        )
        gallardo_fit = clamp01(
            clamp01(scan_input.execution_readiness_score)
            * optionality_score
            * turn_safety_score
            * clamp01(scan_input.validation_score)
        )

        action_permission = all(
            (
                gates["hard_veto_pass"],
                gates["scan_gate_pass"],
                gates["pressure_gate_pass"],
                gates["board_control_gate_pass"],
                gates["optionality_gate_pass"],
                gates["timing_gate_pass"],
                gates["validation_gate_pass"],
                gates["durability_gate_pass"],
            )
        ) and pre_execution_archetype not in {
            PreExecutionArchetype.DIABLO_CHAOS_NO_TURN,
            PreExecutionArchetype.ISLERO_SHOCK_REMAP,
        }
        if surprise_risk_score > self.config.max_surprise_risk_for_action:
            action_permission = False
        if pre_scan_quality_score < self.config.min_scan_quality_for_action:
            action_permission = False
        if board_control_score < self.config.min_board_control_for_action:
            action_permission = False
        if optionality_score < self.config.min_optionality_for_action:
            action_permission = False
        if clamp01(scan_input.validation_score) < self.config.min_validation_for_fast_track:
            action_permission = False
        if clamp01(scan_input.durability_score) < self.config.min_durability_for_fast_track:
            action_permission = False
        if scan_input.heat_risk_score > self.config.max_heat_risk_for_action:
            action_permission = False
        if scan_input.contradiction_score > self.config.max_contradiction_for_action:
            action_permission = False

        recommended_next_steps = generate_recommended_next_steps(
            PreExecutionScanReport(
                signal_id=scan_input.signal_id,
                scan_readiness=scan_readiness,
                pressure_state=pressure_state,
                turn_decision=turn_decision,
                surprise_band=surprise_band,
                board_control_state=board_control_state,
                pre_execution_decision=pre_execution_decision,
                pre_execution_archetype=pre_execution_archetype,
                pre_scan_quality_score=pre_scan_quality_score,
                mini_map_quality_score=mini_map_quality_score,
                pressure_awareness_score=pressure_awareness_score,
                surprise_risk_score=surprise_risk_score,
                board_control_score=board_control_score,
                optionality_score=optionality_score,
                turn_safety_score=turn_safety_score,
                hidden_preconditions_score=hidden_preconditions_score,
                execution_timing_score=execution_timing_score,
                pre_execution_quality_score=pre_execution_quality_score,
                final_pre_execution_score=final_pre_execution_score,
                scan_gate_pass=gates["scan_gate_pass"],
                pressure_gate_pass=gates["pressure_gate_pass"],
                board_control_gate_pass=gates["board_control_gate_pass"],
                optionality_gate_pass=gates["optionality_gate_pass"],
                timing_gate_pass=gates["timing_gate_pass"],
                hard_veto_pass=gates["hard_veto_pass"],
                action_permission=action_permission,
                hard_veto_reasons=hard_veto_reasons,
                warnings=warnings,
                recommended_next_steps=[],
                formula_trace={},
                transition_log=transition_log,
            )
        )

        return PreExecutionScanReport(
            signal_id=scan_input.signal_id,
            scan_readiness=scan_readiness,
            pressure_state=pressure_state,
            turn_decision=turn_decision,
            surprise_band=surprise_band,
            board_control_state=board_control_state,
            pre_execution_decision=pre_execution_decision,
            pre_execution_archetype=pre_execution_archetype,
            pre_scan_quality_score=pre_scan_quality_score,
            mini_map_quality_score=mini_map_quality_score,
            pressure_awareness_score=pressure_awareness_score,
            surprise_risk_score=surprise_risk_score,
            board_control_score=board_control_score,
            optionality_score=optionality_score,
            turn_safety_score=turn_safety_score,
            hidden_preconditions_score=hidden_preconditions_score,
            execution_timing_score=execution_timing_score,
            pre_execution_quality_score=pre_execution_quality_score,
            final_pre_execution_score=final_pre_execution_score,
            scan_gate_pass=gates["scan_gate_pass"],
            pressure_gate_pass=gates["pressure_gate_pass"],
            board_control_gate_pass=gates["board_control_gate_pass"],
            optionality_gate_pass=gates["optionality_gate_pass"],
            timing_gate_pass=gates["timing_gate_pass"],
            hard_veto_pass=gates["hard_veto_pass"],
            action_permission=action_permission,
            hard_veto_reasons=hard_veto_reasons,
            warnings=warnings,
            recommended_next_steps=recommended_next_steps,
            formula_trace={
                **pre_scan_trace,
                **mini_map_trace,
                **surprise_trace,
                **pressure_trace,
                **board_trace,
                **optionality_trace,
                **turn_trace,
                **hidden_trace,
                **timing_trace,
                **failure_trace,
                "telemetry_freshness_score": telemetry_freshness_score,
                "weighted_geometric_final_raw": final_weighted_raw,
                "final_pre_execution_score": final_pre_execution_score,
                "unsafe_action_risk": unsafe_action_risk,
                "murcielago_fit": murcielago_fit,
                "gallardo_fit": gallardo_fit,
            },
            transition_log=transition_log,
        )


def _coerce_float(value: Any, default: float) -> float:
    if value is None or isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_scan_input(
    row: dict[str, Any], runtime_state: dict[str, Any] | None = None
) -> PreExecutionScanInput:
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
    truth_probability = clamp01(_coerce_float(row.get("truth_probability"), 0.5))
    raw_signal_strength = clamp01(
        _coerce_float(
            row.get("signal_strength_score"),
            _coerce_float(row.get("signal_strength"), 0.5),
        )
    )
    validation_score = clamp01(
        _coerce_float(row.get("validation_score"), truth_probability)
    )
    durability_score = clamp01(
        _coerce_float(
            row.get("durability_score"),
            _coerce_float(runtime_payload.get("durability_score"), 0.45),
        )
    )
    execution_readiness = clamp01(
        _coerce_float(
            row.get("execution_readiness_score"),
            _coerce_float(row.get("execution_survivability_score"), 0.35),
        )
    )
    chaos_veto = bool(
        row.get("chaos_veto")
        or row.get("chaos_flag")
        or runtime_payload.get("structural_admission", {}).get("structural_admission_class") == "CHAOS_VETO"
    )
    return PreExecutionScanInput(
        signal_id=str(row.get("signal_id") or row.get("ticker") or row.get("symbol") or "UNKNOWN"),
        timestamp=row.get("timestamp") or runtime_payload.get("decision_timestamp") or "UNKNOWN",
        raw_signal_strength=raw_signal_strength,
        signal_confidence=clamp01(_coerce_float(row.get("signal_confidence"), truth_probability)),
        validation_score=validation_score,
        durability_score=durability_score,
        execution_readiness_score=execution_readiness,
        scan_count=int(_coerce_float(row.get("scan_count"), 2)),
        scan_frequency_per_minute=clamp01(_coerce_float(row.get("scan_frequency_per_minute"), 4.0)) * 10.0,
        scan_recency_seconds=max(0.0, _coerce_float(row.get("scan_recency_seconds"), 20.0)),
        scan_accuracy_score=clamp01(_coerce_float(row.get("scan_accuracy_score"), validation_score)),
        context_freshness_score=clamp01(_coerce_float(row.get("context_freshness_score"), 1.0 - _coerce_float(row.get("chaos_intensity"), 0.30))),
        information_decay_rate=clamp01(_coerce_float(row.get("information_decay_rate"), 0.25)),
        known_actor_count=int(_coerce_float(row.get("known_actor_count"), 6)),
        estimated_total_actor_count=int(_coerce_float(row.get("estimated_total_actor_count"), 10)),
        teammate_alignment_score=clamp01(_coerce_float(row.get("teammate_alignment_score"), 0.60)),
        opponent_pressure_score=clamp01(_coerce_float(row.get("opponent_pressure_score"), _coerce_float(row.get("chaos_intensity"), 0.30))),
        exit_lane_count=int(_coerce_float(row.get("exit_lane_count"), 3)),
        safe_exit_lane_count=int(_coerce_float(row.get("safe_exit_lane_count"), 2)),
        collision_risk_score=clamp01(_coerce_float(row.get("collision_risk_score"), 0.25)),
        spatial_coverage_score=clamp01(_coerce_float(row.get("spatial_coverage_score"), 0.60)),
        pressure_magnitude=clamp01(_coerce_float(row.get("pressure_magnitude"), _coerce_float(row.get("chaos_intensity"), 0.30))),
        pressure_closing_speed=clamp01(_coerce_float(row.get("pressure_closing_speed"), 0.35)),
        pressure_angle_risk=clamp01(_coerce_float(row.get("pressure_angle_risk"), 0.30)),
        pressure_direction_confidence=clamp01(_coerce_float(row.get("pressure_direction_confidence"), 0.60)),
        trap_risk_score=clamp01(_coerce_float(row.get("trap_risk_score"), _coerce_float(row.get("bluff_risk"), 0.20))),
        critical_zones_total=int(_coerce_float(row.get("critical_zones_total"), 4)),
        critical_zones_controlled=int(_coerce_float(row.get("critical_zones_controlled"), 2)),
        critical_zones_exposed=int(_coerce_float(row.get("critical_zones_exposed"), 1)),
        containment_strength_score=clamp01(_coerce_float(row.get("containment_strength_score"), 0.55)),
        safe_action_count=int(_coerce_float(row.get("safe_action_count"), 2)),
        total_action_count=int(_coerce_float(row.get("total_action_count"), 4)),
        best_action_quality_score=clamp01(_coerce_float(row.get("best_action_quality_score"), 0.55)),
        fallback_quality_score=clamp01(_coerce_float(row.get("fallback_quality_score"), 0.55)),
        recycle_quality_score=clamp01(_coerce_float(row.get("recycle_quality_score"), 0.55)),
        policy_veto=policy_state in {"RESTRICTED", "DO_NOT_DEPLOY", "BLOCKED"},
        chaos_veto=chaos_veto,
        shock_event=bool(row.get("shock_event") or row.get("joker_event_detected", False)),
        heat_risk_score=clamp01(_coerce_float(row.get("heat_risk_score"), 0.20)),
        volatility_score=clamp01(_coerce_float(row.get("volatility_score"), 0.30)),
        contradiction_score=clamp01(_coerce_float(row.get("contradiction_score"), _coerce_float(row.get("hallucination_risk"), 0.10))),
        time_to_execution_seconds=max(0.0, _coerce_float(row.get("time_to_execution_seconds"), 20.0)),
        execution_half_life_seconds=max(0.0, _coerce_float(row.get("execution_half_life_seconds"), 45.0)),
        notes=list(row.get("notes", [])) if isinstance(row.get("notes"), list) else [],
    )


def build_pre_execution_scan_report(
    runtime_state_or_signals: dict | list | None = None,
    runtime_state: dict[str, Any] | None = None,
    write_runtime: bool = True,
    output_path: Path | None = None,
) -> dict[str, Any]:
    runtime_payload: dict[str, Any]
    if isinstance(runtime_state_or_signals, dict):
        runtime_payload = runtime_state_or_signals
        signal_rows = runtime_payload.get("per_signal_attribution", [])
        if not isinstance(signal_rows, list):
            signal_rows = []
    else:
        runtime_payload = runtime_state if isinstance(runtime_state, dict) else {}
        signal_rows = runtime_state_or_signals if isinstance(runtime_state_or_signals, list) else []
    rows = [row for row in signal_rows if isinstance(row, dict)]
    engine = PreExecutionScanEngine()
    per_signal_reports = [engine.evaluate(_normalize_scan_input(row, runtime_payload)) for row in rows]
    primary = (
        min(
            per_signal_reports,
            key=lambda report: (
                0 if not report.action_permission else 1,
                0 if not report.hard_veto_pass else 1,
                report.final_pre_execution_score,
            ),
        )
        if per_signal_reports
        else None
    )
    payload: dict[str, Any] = {
        "pre_execution_scan_state": primary.pre_execution_archetype.value if primary else PreExecutionArchetype.UNKNOWN_PRE_EXECUTION_STATE.value,
        "pre_execution_scan_readiness": primary.scan_readiness.value if primary else ScanReadiness.BLIND.value,
        "pre_execution_pressure_state": primary.pressure_state.value if primary else PressureState.CHAOS.value,
        "pre_execution_turn_decision": primary.turn_decision.value if primary else TurnDecision.QUARANTINE.value,
        "pre_execution_surprise_band": primary.surprise_band.value if primary else SurpriseBand.CRITICAL.value,
        "pre_execution_board_control_state": primary.board_control_state.value if primary else BoardControlState.UNKNOWN.value,
        "pre_execution_decision": primary.pre_execution_decision.value if primary else PreExecutionDecision.QUARANTINE.value,
        "pre_execution_archetype": primary.pre_execution_archetype.value if primary else PreExecutionArchetype.UNKNOWN_PRE_EXECUTION_STATE.value,
        "pre_execution_score": round(primary.final_pre_execution_score, 4) if primary else 0.0,
        "pre_execution_action_permission": bool(primary.action_permission) if primary else False,
        "signals_evaluated": len(per_signal_reports),
        "pre_execution_scan_summary": summarize_pre_execution_report(primary) if primary else "No signals available.",
        "per_signal_reports": [report.to_dict() for report in per_signal_reports],
        "report_path": repo_relative(output_path or PRE_EXECUTION_SCAN_REPORT_PATH),
    }
    stamped = stamp_payload(payload, runtime_state=runtime_payload)
    if write_runtime:
        write_json_atomic(output_path or PRE_EXECUTION_SCAN_REPORT_PATH, stamped)
    return stamped


__all__ = [
    "BoardControlState",
    "PreExecutionArchetype",
    "PreExecutionDecision",
    "PreExecutionScanConfig",
    "PreExecutionScanEngine",
    "PreExecutionScanInput",
    "PreExecutionScanReport",
    "PressureState",
    "ScanReadiness",
    "SurpriseBand",
    "TurnDecision",
    "build_pre_execution_scan_report",
    "clamp01",
    "compute_board_control",
    "compute_execution_timing_score",
    "compute_failure_risk",
    "compute_gates",
    "compute_hidden_preconditions_score",
    "compute_mini_map_quality",
    "compute_optionality",
    "compute_pre_scan_quality",
    "compute_pressure_awareness",
    "compute_scan_frequency_effect",
    "compute_scan_recency_score",
    "compute_surprise_risk",
    "compute_turn_safety",
    "map_pre_execution_archetype",
    "map_pre_execution_decision",
    "normalize_weights",
    "safe_div",
    "summarize_pre_execution_report",
    "weighted_geometric_score",
    "weighted_sum",
]
