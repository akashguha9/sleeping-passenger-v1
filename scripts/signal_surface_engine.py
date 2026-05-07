from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        classify_operating_mode,
        repo_relative,
        stamp_payload,
        write_json_atomic,
        SIGNAL_SURFACE_REPORT_PATH,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        classify_operating_mode,
        repo_relative,
        stamp_payload,
        write_json_atomic,
        SIGNAL_SURFACE_REPORT_PATH,
    )


EPSILON = 1e-6


class DamageClass(str, Enum):
    INTACT = "INTACT"
    MINOR_DENT = "MINOR_DENT"
    SURFACE_DAMAGE = "SURFACE_DAMAGE"
    STRUCTURAL_DISTORTION = "STRUCTURAL_DISTORTION"
    CONTAMINATED = "CONTAMINATED"
    CONTRADICTED = "CONTRADICTED"
    STRUCTURAL_FAILURE = "STRUCTURAL_FAILURE"
    UNKNOWN = "UNKNOWN"


class RepairMode(str, Enum):
    RESTORE = "RESTORE"
    REFINE = "REFINE"
    REBUILD = "REBUILD"
    QUARANTINE = "QUARANTINE"


class LayerStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CureGateStatus(str, Enum):
    STABLE = "STABLE"
    CURING = "CURING"
    UNSTABLE = "UNSTABLE"
    EXPIRED = "EXPIRED"
    SHOCK_RESET = "SHOCK_RESET"


class FinishHonestyFlag(str, Enum):
    HONEST = "HONEST"
    OVER_POLISHED = "OVER_POLISHED"
    UNDER_PRESENTED = "UNDER_PRESENTED"
    MASKING_STRUCTURAL_WEAKNESS = "MASKING_STRUCTURAL_WEAKNESS"
    PRESENTATION_NOT_ALLOWED = "PRESENTATION_NOT_ALLOWED"


class SurfaceDecision(str, Enum):
    REJECT = "REJECT"
    WAIT = "WAIT"
    REPAIR = "REPAIR"
    VALIDATE = "VALIDATE"
    PROMOTE = "PROMOTE"
    EXECUTE_READY = "EXECUTE_READY"
    QUARANTINE = "QUARANTINE"


class BullSurfaceState(str, Enum):
    MIURA_RAW_DENT = "MIURA_RAW_DENT"
    MURCIELAGO_DURABILITY_REPAIR = "MURCIELAGO_DURABILITY_REPAIR"
    AVENTADOR_VALIDATED_SURFACE = "AVENTADOR_VALIDATED_SURFACE"
    GALLARDO_EXECUTION_FINISH = "GALLARDO_EXECUTION_FINISH"
    ISLERO_SHOCK_RECLASSIFICATION = "ISLERO_SHOCK_RECLASSIFICATION"
    DIABLO_CHAOS_SURFACE_VETO = "DIABLO_CHAOS_SURFACE_VETO"
    HURACAN_FAST_TRACK_SURFACE = "HURACAN_FAST_TRACK_SURFACE"
    UNKNOWN_SURFACE_STATE = "UNKNOWN_SURFACE_STATE"


@dataclass(slots=True)
class SurfaceEngineConfig:
    theta_restore: float = 0.78
    theta_refine: float = 0.45
    action_threshold: float = 0.72
    validation_threshold: float = 0.65
    stress_threshold: float = 0.60
    max_perception_gap: float = 0.18
    min_stabilization_minutes: float = 180.0
    allowed_process_alpha: float = 0.05
    layer_weights: dict[str, float] = field(
        default_factory=lambda: {
            "substrate_integrity": 1.0,
            "structural_correction": 1.1,
            "residual_smoothness": 0.9,
            "preparation": 0.9,
            "adhesion": 0.9,
            "narrative_fit": 1.0,
            "validation_protection": 1.1,
            "boundary_blending": 0.9,
            "cure_stability": 1.0,
            "presentation_clarity": 0.7,
            "stress_survival": 1.1,
        }
    )
    visible_distortion_weights: dict[str, float] = field(
        default_factory=lambda: {
            "structural_distortion": 0.45,
            "reflection_distortion": 0.35,
            "finish_distortion": 0.20,
        }
    )
    boundary_visibility_weights: dict[str, float] = field(
        default_factory=lambda: {
            "data_mismatch": 0.35,
            "logic_mismatch": 0.30,
            "tone_mismatch": 0.20,
            "interface_mismatch": 0.15,
        }
    )


@dataclass(slots=True)
class SignalSurfaceInput:
    signal_id: str
    timestamp: datetime
    source_count: int
    source_reliability_score: float
    raw_signal_strength: float
    raw_noise_score: float
    contradiction_score: float
    volatility_score: float
    liquidity_risk_score: float = 0.0
    latency_risk_score: float = 0.0
    narrative_clarity_score: float = 0.0
    data_completeness_score: float = 0.0
    schema_readiness_score: float = 0.0
    metadata_completeness_score: float = 0.0
    context_compatibility_score: float = 0.0
    execution_readiness_score: float = 0.0
    policy_veto: bool = False
    chaos_veto: bool = False
    heat_risk_score: float = 0.0
    time_since_major_change_minutes: float = 0.0
    stress_test_before_score: float | None = None
    stress_test_after_score: float | None = None
    momentum_score: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SignalSurfaceReport:
    signal_id: str
    damage_class: DamageClass
    repair_mode: RepairMode
    layer_scores: dict[str, float]
    layer_statuses: dict[str, LayerStatus]
    substrate_integrity_score: float
    structural_correction_score: float
    residual_smoothness_score: float
    preparation_score: float
    adhesion_score: float
    narrative_fit_score: float
    validation_protection_score: float
    boundary_blending_score: float
    cure_stability_score: float
    presentation_clarity_score: float
    stress_survival_score: float
    strict_multiplicative_score: float
    weighted_geometric_score: float
    surface_system_score: float
    output_quality_ceiling: float
    final_capped_score: float
    visible_distortion_score: float
    perceived_signal_quality: float
    finish_honesty_flag: FinishHonestyFlag
    cure_gate_status: CureGateStatus
    surface_decision: SurfaceDecision
    bull_surface_state: BullSurfaceState
    action_permission: bool
    hard_veto_reasons: list[str]
    warnings: list[str]
    recommended_next_steps: list[str]
    formula_trace: dict[str, float]
    transition_log: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["damage_class"] = self.damage_class.value
        payload["repair_mode"] = self.repair_mode.value
        payload["layer_statuses"] = {
            key: value.value for key, value in self.layer_statuses.items()
        }
        payload["finish_honesty_flag"] = self.finish_honesty_flag.value
        payload["cure_gate_status"] = self.cure_gate_status.value
        payload["surface_decision"] = self.surface_decision.value
        payload["bull_surface_state"] = self.bull_surface_state.value
        return payload


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def safe_weighted_sum(values: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(max(0.0, float(weight)) for weight in weights.values())
    if total_weight <= EPSILON:
        return 0.0
    numerator = 0.0
    for key, weight in weights.items():
        numerator += clamp01(values.get(key, 0.0)) * max(0.0, float(weight))
    return clamp01(numerator / total_weight)


def weighted_geometric_score(
    scores: dict[str, float], weights: dict[str, float], epsilon: float = EPSILON
) -> float:
    total_weight = sum(max(0.0, float(weight)) for weight in weights.values())
    if total_weight <= epsilon:
        return 0.0
    weighted_log_sum = 0.0
    for key, weight in weights.items():
        score = clamp01(scores.get(key, 0.0))
        weighted_log_sum += max(0.0, float(weight)) * __import__("math").log(
            max(score, epsilon)
        )
    return clamp01(__import__("math").exp(weighted_log_sum / total_weight))


def _layer_status(score: float) -> LayerStatus:
    if score >= 0.70:
        return LayerStatus.PASS
    if score >= 0.45:
        return LayerStatus.WARN
    return LayerStatus.FAIL


def compute_substrate_integrity(signal_input: SignalSurfaceInput) -> float:
    return clamp01(
        0.35 * clamp01(signal_input.source_reliability_score)
        + 0.25 * clamp01(signal_input.data_completeness_score)
        + 0.20 * (1.0 - clamp01(signal_input.raw_noise_score))
        + 0.20 * (1.0 - clamp01(signal_input.contradiction_score))
    )


def classify_damage(
    signal_input: SignalSurfaceInput, config: SurfaceEngineConfig
) -> DamageClass:
    substrate = compute_substrate_integrity(signal_input)
    if signal_input.policy_veto or signal_input.chaos_veto:
        return DamageClass.CONTAMINATED
    if signal_input.contradiction_score >= 0.80:
        return DamageClass.CONTRADICTED
    if substrate <= 0.20 or signal_input.source_count <= 0:
        return DamageClass.STRUCTURAL_FAILURE
    if (
        signal_input.raw_noise_score >= 0.75
        or signal_input.data_completeness_score <= 0.25
        or signal_input.schema_readiness_score <= 0.20
    ):
        return DamageClass.CONTAMINATED
    if substrate <= 0.35 or signal_input.raw_noise_score >= 0.60:
        return DamageClass.STRUCTURAL_DISTORTION
    if signal_input.contradiction_score >= 0.55 or signal_input.volatility_score >= 0.60:
        return DamageClass.SURFACE_DAMAGE
    if substrate >= config.theta_restore and signal_input.raw_noise_score <= 0.20:
        return DamageClass.INTACT
    if substrate >= config.theta_refine:
        return DamageClass.MINOR_DENT
    return DamageClass.UNKNOWN


def choose_repair_mode(
    damage_class: DamageClass,
    surface_integrity_score: float,
    signal_input: SignalSurfaceInput,
    config: SurfaceEngineConfig,
) -> RepairMode:
    if signal_input.policy_veto or signal_input.chaos_veto:
        return RepairMode.QUARANTINE
    if surface_integrity_score >= config.theta_restore:
        return RepairMode.RESTORE
    if surface_integrity_score >= config.theta_refine:
        return RepairMode.REFINE
    return RepairMode.REBUILD


def compute_structural_correction(
    signal_input: SignalSurfaceInput, damage_class: DamageClass
) -> float:
    base = clamp01(
        0.40 * clamp01(signal_input.raw_signal_strength)
        + 0.25 * clamp01(signal_input.source_reliability_score)
        + 0.20 * (1.0 - clamp01(signal_input.raw_noise_score))
        + 0.15 * (1.0 - clamp01(signal_input.contradiction_score))
    )
    multipliers = {
        DamageClass.INTACT: 1.00,
        DamageClass.MINOR_DENT: 0.92,
        DamageClass.SURFACE_DAMAGE: 0.75,
        DamageClass.STRUCTURAL_DISTORTION: 0.55,
        DamageClass.CONTAMINATED: 0.25,
        DamageClass.CONTRADICTED: 0.20,
        DamageClass.STRUCTURAL_FAILURE: 0.10,
        DamageClass.UNKNOWN: 0.15,
    }
    return clamp01(base * multipliers[damage_class])


def compute_residual_smoothness(
    signal_input: SignalSurfaceInput, structural_correction_score: float
) -> float:
    raw_signal_distortion = clamp01(
        0.45 * clamp01(signal_input.raw_noise_score)
        + 0.35 * clamp01(signal_input.contradiction_score)
        + 0.20 * clamp01(signal_input.volatility_score)
    )
    residual_signal_error = clamp01(
        raw_signal_distortion * (1.0 - clamp01(structural_correction_score))
    )
    return clamp01(1.0 - residual_signal_error)


def compute_preparation_score(signal_input: SignalSurfaceInput) -> float:
    return clamp01(
        0.35 * clamp01(signal_input.data_completeness_score)
        + 0.25 * clamp01(signal_input.metadata_completeness_score)
        + 0.20 * clamp01(signal_input.context_compatibility_score)
        + 0.20 * (1.0 - clamp01(signal_input.latency_risk_score))
    )


def compute_adhesion_score(signal_input: SignalSurfaceInput) -> float:
    """AdhesionCompatibilityScore =
    0.40 × schema_readiness_score
    + 0.30 × context_compatibility_score
    + 0.20 × metadata_completeness_score
    + 0.10 × data_completeness_score
    """
    return clamp01(
        0.40 * clamp01(signal_input.schema_readiness_score)
        + 0.30 * clamp01(signal_input.context_compatibility_score)
        + 0.20 * clamp01(signal_input.metadata_completeness_score)
        + 0.10 * clamp01(signal_input.data_completeness_score)
    )


def compute_narrative_fit_score(signal_input: SignalSurfaceInput) -> float:
    """NarrativeFitScore =
    0.45 × narrative_clarity_score
    + 0.25 × context_compatibility_score
    + 0.20 × raw_signal_strength
    + 0.10 × source_reliability_score
    then penalize by contradiction.
    """
    score = clamp01(
        0.45 * clamp01(signal_input.narrative_clarity_score)
        + 0.25 * clamp01(signal_input.context_compatibility_score)
        + 0.20 * clamp01(signal_input.raw_signal_strength)
        + 0.10 * clamp01(signal_input.source_reliability_score)
    )
    return clamp01(score * (1.0 - 0.50 * clamp01(signal_input.contradiction_score)))


def compute_validation_protection_score(signal_input: SignalSurfaceInput) -> float:
    """ValidationProtectionScore =
    0.30 × source_reliability_score
    + 0.25 × (1 − contradiction_score)
    + 0.20 × (1 − volatility_score)
    + 0.15 × data_completeness_score
    + 0.10 × (1 − heat_risk_score)
    """
    if signal_input.policy_veto or signal_input.chaos_veto:
        return 0.0
    return clamp01(
        0.30 * clamp01(signal_input.source_reliability_score)
        + 0.25 * (1.0 - clamp01(signal_input.contradiction_score))
        + 0.20 * (1.0 - clamp01(signal_input.volatility_score))
        + 0.15 * clamp01(signal_input.data_completeness_score)
        + 0.10 * (1.0 - clamp01(signal_input.heat_risk_score))
    )


def compute_visible_distortion_score(signal_input: SignalSurfaceInput) -> float:
    """VisibleSignalDistortion =
    0.45 × StructuralDistortion
    + 0.35 × ReflectionDistortion
    + 0.20 × FinishDistortion
    """
    structural_distortion = clamp01(
        0.50 * clamp01(signal_input.raw_noise_score)
        + 0.50 * clamp01(signal_input.contradiction_score)
    )
    reflection_distortion = clamp01(
        abs(clamp01(signal_input.narrative_clarity_score) - clamp01(signal_input.raw_signal_strength))
    )
    finish_distortion = clamp01(
        0.50 * (1.0 - clamp01(signal_input.metadata_completeness_score))
        + 0.50 * (1.0 - clamp01(signal_input.context_compatibility_score))
    )
    return clamp01(
        0.45 * structural_distortion
        + 0.35 * reflection_distortion
        + 0.20 * finish_distortion
    )


def compute_boundary_blending_score(
    layer_scores: dict[str, float],
) -> tuple[float, dict[str, float]]:
    data_mismatch = clamp01(1.0 - layer_scores.get("preparation", 0.0))
    logic_mismatch = clamp01(1.0 - layer_scores.get("validation_protection", 0.0))
    tone_mismatch = clamp01(abs(layer_scores.get("narrative_fit", 0.0) - layer_scores.get("substrate_integrity", 0.0)))
    interface_mismatch = clamp01(1.0 - layer_scores.get("adhesion", 0.0))
    boundary_visibility = clamp01(
        0.35 * data_mismatch
        + 0.30 * logic_mismatch
        + 0.20 * tone_mismatch
        + 0.15 * interface_mismatch
    )
    return clamp01(1.0 - boundary_visibility), {
        "boundary_visibility": boundary_visibility,
        "data_mismatch": data_mismatch,
        "logic_mismatch": logic_mismatch,
        "tone_mismatch": tone_mismatch,
        "interface_mismatch": interface_mismatch,
    }


def compute_cure_gate(
    signal_input: SignalSurfaceInput, config: SurfaceEngineConfig
) -> tuple[CureGateStatus, float]:
    if signal_input.policy_veto or signal_input.chaos_veto:
        return CureGateStatus.SHOCK_RESET, 0.0
    if signal_input.contradiction_score >= 0.80:
        return CureGateStatus.SHOCK_RESET, 0.0
    if signal_input.volatility_score >= 0.85:
        return CureGateStatus.UNSTABLE, 0.20
    if signal_input.time_since_major_change_minutes < config.min_stabilization_minutes:
        ratio = clamp01(
            signal_input.time_since_major_change_minutes
            / max(config.min_stabilization_minutes, EPSILON)
        )
        return CureGateStatus.CURING, ratio
    if signal_input.time_since_major_change_minutes > config.min_stabilization_minutes * 24:
        return CureGateStatus.EXPIRED, 0.55
    return CureGateStatus.STABLE, 1.0


def compute_presentation_clarity_score(
    signal_input: SignalSurfaceInput,
    validation_protection_score: float,
    core_integrity_score: float,
) -> float:
    score = clamp01(
        0.50 * clamp01(signal_input.narrative_clarity_score)
        + 0.20 * clamp01(signal_input.metadata_completeness_score)
        + 0.20 * clamp01(signal_input.context_compatibility_score)
        + 0.10 * clamp01(signal_input.schema_readiness_score)
    )
    if validation_protection_score < 0.50:
        score = min(score, 0.60)
    if core_integrity_score < 0.45:
        score = min(score, 0.50)
    return clamp01(score)


def compute_stress_survival_score(signal_input: SignalSurfaceInput) -> float:
    before = signal_input.stress_test_before_score
    after = signal_input.stress_test_after_score
    if before is not None and after is not None:
        ratio = float(after) / max(float(before), EPSILON)
        if ratio >= 1.0:
            return clamp01(min(1.0, 0.90 + 0.10 * min(ratio - 1.0, 1.0)))
        return clamp01(ratio)
    return clamp01(
        0.30 * (1.0 - clamp01(signal_input.volatility_score))
        + 0.25 * (1.0 - clamp01(signal_input.contradiction_score))
        + 0.20 * clamp01(signal_input.source_reliability_score)
        + 0.15 * clamp01(signal_input.data_completeness_score)
        + 0.10 * (1.0 - clamp01(signal_input.heat_risk_score))
    )


def compute_finish_honesty_flag(
    perceived_quality: float,
    underlying_integrity: float,
    presentation_score: float,
    validation_score: float,
    config: SurfaceEngineConfig,
) -> FinishHonestyFlag:
    if validation_score < 0.40 and presentation_score >= 0.50:
        return FinishHonestyFlag.PRESENTATION_NOT_ALLOWED
    if underlying_integrity < 0.45 and presentation_score >= 0.55:
        return FinishHonestyFlag.MASKING_STRUCTURAL_WEAKNESS
    if perceived_quality - underlying_integrity > config.max_perception_gap:
        return FinishHonestyFlag.OVER_POLISHED
    if underlying_integrity >= 0.70 and presentation_score < 0.45:
        return FinishHonestyFlag.UNDER_PRESENTED
    return FinishHonestyFlag.HONEST


def compute_action_permission(
    signal_input: SignalSurfaceInput,
    report: SignalSurfaceReport,
    config: SurfaceEngineConfig,
) -> bool:
    if signal_input.policy_veto or signal_input.chaos_veto:
        return False
    if report.cure_gate_status != CureGateStatus.STABLE:
        return False
    if report.damage_class in {
        DamageClass.CONTRADICTED,
        DamageClass.CONTAMINATED,
        DamageClass.STRUCTURAL_FAILURE,
        DamageClass.UNKNOWN,
    }:
        return False
    if report.final_capped_score < config.action_threshold:
        return False
    if report.validation_protection_score < config.validation_threshold:
        return False
    if report.stress_survival_score < config.stress_threshold:
        return False
    if report.finish_honesty_flag in {
        FinishHonestyFlag.MASKING_STRUCTURAL_WEAKNESS,
        FinishHonestyFlag.PRESENTATION_NOT_ALLOWED,
    }:
        return False
    return True


def map_to_surface_decision(
    report: SignalSurfaceReport,
    signal_input: SignalSurfaceInput,
    config: SurfaceEngineConfig,
) -> SurfaceDecision:
    if signal_input.policy_veto or signal_input.chaos_veto or report.cure_gate_status == CureGateStatus.SHOCK_RESET:
        return SurfaceDecision.QUARANTINE
    if report.damage_class in {
        DamageClass.CONTRADICTED,
        DamageClass.CONTAMINATED,
        DamageClass.STRUCTURAL_FAILURE,
        DamageClass.UNKNOWN,
    }:
        return SurfaceDecision.REJECT
    if (
        report.cure_gate_status in {CureGateStatus.CURING, CureGateStatus.UNSTABLE, CureGateStatus.EXPIRED}
        or report.final_capped_score < config.validation_threshold
    ):
        return SurfaceDecision.WAIT
    if report.action_permission and signal_input.execution_readiness_score >= config.action_threshold:
        return SurfaceDecision.EXECUTE_READY
    if report.action_permission:
        return SurfaceDecision.PROMOTE
    if report.repair_mode in {RepairMode.REBUILD, RepairMode.REFINE}:
        return SurfaceDecision.REPAIR
    return SurfaceDecision.VALIDATE


def map_to_bull_surface_state(
    report: SignalSurfaceReport,
    signal_input: SignalSurfaceInput,
    config: SurfaceEngineConfig,
) -> BullSurfaceState:
    if signal_input.policy_veto or signal_input.chaos_veto:
        return BullSurfaceState.DIABLO_CHAOS_SURFACE_VETO
    if report.cure_gate_status == CureGateStatus.SHOCK_RESET or signal_input.contradiction_score >= 0.80:
        return BullSurfaceState.ISLERO_SHOCK_RECLASSIFICATION
    if report.action_permission and signal_input.execution_readiness_score >= config.action_threshold:
        return BullSurfaceState.GALLARDO_EXECUTION_FINISH
    if (
        report.final_capped_score >= config.action_threshold
        and report.validation_protection_score >= config.validation_threshold
        and signal_input.execution_readiness_score < config.action_threshold
    ):
        return BullSurfaceState.AVENTADOR_VALIDATED_SURFACE
    if (
        signal_input.momentum_score >= 0.80
        and signal_input.raw_signal_strength >= 0.75
        and report.validation_protection_score >= config.validation_threshold
        and report.stress_survival_score >= config.stress_threshold
        and report.cure_gate_status == CureGateStatus.STABLE
        and not signal_input.policy_veto
        and not signal_input.chaos_veto
    ):
        return BullSurfaceState.HURACAN_FAST_TRACK_SURFACE
    if signal_input.raw_signal_strength >= 0.70 and report.validation_protection_score < config.validation_threshold:
        return BullSurfaceState.MIURA_RAW_DENT
    if report.repair_mode in {RepairMode.RESTORE, RepairMode.REFINE, RepairMode.REBUILD} and (
        signal_input.stress_test_before_score is not None or signal_input.stress_test_after_score is not None
    ):
        return BullSurfaceState.MURCIELAGO_DURABILITY_REPAIR
    return BullSurfaceState.UNKNOWN_SURFACE_STATE


def generate_recommended_next_steps(report: SignalSurfaceReport) -> list[str]:
    steps: list[str] = []
    if report.surface_decision == SurfaceDecision.QUARANTINE:
        steps.append("Honor policy and chaos veto before any further surface work.")
    if report.cure_gate_status == CureGateStatus.CURING:
        steps.append("Allow more stabilization time before presentation or promotion.")
    if report.cure_gate_status == CureGateStatus.UNSTABLE:
        steps.append("Reduce volatility exposure and re-run cure checks.")
    if report.validation_protection_score < 0.65:
        steps.append("Increase validation protection before allowing surface presentation.")
    if report.stress_survival_score < 0.60:
        steps.append("Run or improve stress survival before promotion.")
    if report.finish_honesty_flag in {
        FinishHonestyFlag.OVER_POLISHED,
        FinishHonestyFlag.MASKING_STRUCTURAL_WEAKNESS,
        FinishHonestyFlag.PRESENTATION_NOT_ALLOWED,
    }:
        steps.append("Reduce presentation emphasis until structural validity improves.")
    if not steps:
        steps.append("Maintain current validated surface discipline and monitor for shocks.")
    return steps


def summarize_surface_report(report: SignalSurfaceReport) -> str:
    blockers = ", ".join(report.hard_veto_reasons) if report.hard_veto_reasons else "none"
    return (
        f"surface_decision={report.surface_decision.value}; "
        f"damage={report.damage_class.value}; "
        f"bull_state={report.bull_surface_state.value}; "
        f"score={report.final_capped_score:.3f}; "
        f"cure={report.cure_gate_status.value}; "
        f"finish={report.finish_honesty_flag.value}; "
        f"blockers={blockers}"
    )


def _normalize_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _normalize_surface_input(
    payload: dict[str, Any], runtime_state: dict[str, Any] | None = None
) -> SignalSurfaceInput:
    runtime_payload = runtime_state if isinstance(runtime_state, dict) else {}
    policy_state = str(
        payload.get("policy_state")
        or runtime_payload.get("policy_state")
        or runtime_payload.get("execution_policy", {}).get("policy_state")
        or "RESTRICTED"
    ).upper()
    chaos_flag = bool(
        payload.get("chaos_veto")
        or payload.get("chaos_flag")
        or payload.get("joker_event_detected")
        or runtime_payload.get("structural_admission", {}).get("structural_admission_class") == "CHAOS_VETO"
    )
    return SignalSurfaceInput(
        signal_id=str(
            payload.get("signal_id")
            or payload.get("ticker")
            or payload.get("symbol")
            or "UNKNOWN_SIGNAL"
        ),
        timestamp=_normalize_timestamp(payload.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        source_count=int(payload.get("source_count", payload.get("confirmation_count", 1)) or 1),
        source_reliability_score=clamp01(
            float(payload.get("source_reliability_score", payload.get("truth_probability", 0.5)) or 0.5)
        ),
        raw_signal_strength=clamp01(
            float(payload.get("raw_signal_strength", payload.get("signal_strength_score", 0.5)) or 0.5)
        ),
        raw_noise_score=clamp01(
            float(payload.get("raw_noise_score", payload.get("hallucination_risk", 0.4)) or 0.4)
        ),
        contradiction_score=clamp01(
            float(payload.get("contradiction_score", payload.get("bluff_risk", 0.1)) or 0.1)
        ),
        volatility_score=clamp01(
            float(payload.get("volatility_score", payload.get("chaos_intensity", 0.4)) or 0.4)
        ),
        liquidity_risk_score=clamp01(float(payload.get("liquidity_risk_score", 0.2) or 0.2)),
        latency_risk_score=clamp01(float(payload.get("latency_risk_score", 0.2) or 0.2)),
        narrative_clarity_score=clamp01(
            float(payload.get("narrative_clarity_score", payload.get("truth_probability", 0.5)) or 0.5)
        ),
        data_completeness_score=clamp01(float(payload.get("data_completeness_score", 0.55) or 0.55)),
        schema_readiness_score=clamp01(float(payload.get("schema_readiness_score", 0.55) or 0.55)),
        metadata_completeness_score=clamp01(
            float(payload.get("metadata_completeness_score", 0.55) or 0.55)
        ),
        context_compatibility_score=clamp01(
            float(payload.get("context_compatibility_score", 0.50) or 0.50)
        ),
        execution_readiness_score=clamp01(
            float(payload.get("execution_readiness_score", payload.get("execution_score", 0.0)) or 0.0)
        ),
        policy_veto=bool(policy_state in {"RESTRICTED", "DO_NOT_DEPLOY", "BLOCKED"} or payload.get("policy_veto")),
        chaos_veto=chaos_flag,
        heat_risk_score=clamp01(float(payload.get("heat_risk_score", 0.2) or 0.2)),
        time_since_major_change_minutes=float(payload.get("time_since_major_change_minutes", 240.0) or 240.0),
        stress_test_before_score=payload.get("stress_test_before_score"),
        stress_test_after_score=payload.get("stress_test_after_score"),
        momentum_score=clamp01(float(payload.get("momentum_score", 0.0) or 0.0)),
        notes=list(payload.get("notes", [])) if isinstance(payload.get("notes"), list) else [],
    )


class SignalSurfaceEngine:
    def __init__(self, config: SurfaceEngineConfig | None = None):
        self.config = config or SurfaceEngineConfig()

    def evaluate(self, signal_input: SignalSurfaceInput) -> SignalSurfaceReport:
        warnings: list[str] = []
        transition_log: list[str] = []
        hard_veto_reasons: list[str] = []
        config = self.config

        substrate_integrity = compute_substrate_integrity(signal_input)
        transition_log.append(f"Substrate integrity computed at {substrate_integrity:.3f}.")
        damage_class = classify_damage(signal_input, config)
        transition_log.append(f"Damage classified as {damage_class.value}.")
        if signal_input.source_count <= 1:
            warnings.append("Limited source count reduces confidence in surface stability.")
        if signal_input.policy_veto:
            hard_veto_reasons.append("POLICY_VETO")
        if signal_input.chaos_veto:
            hard_veto_reasons.append("CHAOS_VETO")
        if signal_input.contradiction_score >= 0.80:
            hard_veto_reasons.append("CONTRADICTION_SHOCK")

        repair_mode = choose_repair_mode(
            damage_class, substrate_integrity, signal_input, config
        )
        transition_log.append(f"Repair mode selected as {repair_mode.value}.")

        structural_correction = compute_structural_correction(signal_input, damage_class)
        residual_smoothness = compute_residual_smoothness(signal_input, structural_correction)
        preparation = compute_preparation_score(signal_input)
        adhesion = compute_adhesion_score(signal_input)
        narrative_fit = compute_narrative_fit_score(signal_input)
        validation_protection = compute_validation_protection_score(signal_input)

        core_scores = {
            "substrate_integrity": substrate_integrity,
            "structural_correction": structural_correction,
            "residual_smoothness": residual_smoothness,
            "preparation": preparation,
            "adhesion": adhesion,
        }
        core_integrity = weighted_geometric_score(
            core_scores,
            {
                "substrate_integrity": 1.0,
                "structural_correction": 1.1,
                "residual_smoothness": 0.9,
                "preparation": 0.9,
                "adhesion": 0.9,
            },
        )
        boundary_blending, boundary_trace = compute_boundary_blending_score(
            {
                "preparation": preparation,
                "validation_protection": validation_protection,
                "narrative_fit": narrative_fit,
                "substrate_integrity": substrate_integrity,
                "adhesion": adhesion,
            }
        )
        cure_gate_status, cure_stability = compute_cure_gate(signal_input, config)
        transition_log.append(
            f"Cure gate resolved to {cure_gate_status.value} with score {cure_stability:.3f}."
        )
        presentation_clarity = compute_presentation_clarity_score(
            signal_input, validation_protection, core_integrity
        )
        stress_survival = compute_stress_survival_score(signal_input)
        finish_scores = {
            "narrative_fit": narrative_fit,
            "validation_protection": validation_protection,
            "boundary_blending": boundary_blending,
            "cure_stability": cure_stability,
            "presentation_clarity": presentation_clarity,
            "stress_survival": stress_survival,
        }
        finish_durability = weighted_geometric_score(
            finish_scores,
            {
                "narrative_fit": 1.0,
                "validation_protection": 1.1,
                "boundary_blending": 0.9,
                "cure_stability": 1.0,
                "presentation_clarity": 0.7,
                "stress_survival": 1.1,
            },
        )
        visible_distortion = compute_visible_distortion_score(signal_input)
        raw_signal_distortion = clamp01(
            0.45 * clamp01(signal_input.raw_noise_score)
            + 0.35 * clamp01(signal_input.contradiction_score)
            + 0.20 * clamp01(signal_input.volatility_score)
        )
        residual_signal_error = clamp01(raw_signal_distortion * (1.0 - structural_correction))

        layer_scores = {
            "substrate_integrity": substrate_integrity,
            "structural_correction": structural_correction,
            "residual_smoothness": residual_smoothness,
            "preparation": preparation,
            "adhesion": adhesion,
            "narrative_fit": narrative_fit,
            "validation_protection": validation_protection,
            "boundary_blending": boundary_blending,
            "cure_stability": cure_stability,
            "presentation_clarity": presentation_clarity,
            "stress_survival": stress_survival,
        }
        layer_statuses = {name: _layer_status(score) for name, score in layer_scores.items()}
        strict_multiplicative = 1.0
        for score in layer_scores.values():
            strict_multiplicative *= clamp01(score)
        weighted_geometric_raw = weighted_geometric_score(layer_scores, config.layer_weights)
        process_quality_score = safe_weighted_sum(
            {
                "structural_correction": structural_correction,
                "residual_smoothness": residual_smoothness,
                "preparation": preparation,
                "adhesion": adhesion,
                "validation_protection": validation_protection,
                "stress_survival": stress_survival,
            },
            {
                "structural_correction": 1.0,
                "residual_smoothness": 0.9,
                "preparation": 0.8,
                "adhesion": 0.9,
                "validation_protection": 1.1,
                "stress_survival": 1.1,
            },
        )
        surface_system_score = clamp01(
            substrate_integrity
            * preparation
            * adhesion
            * boundary_blending
            * finish_durability
        )
        output_quality_ceiling = clamp01(substrate_integrity * process_quality_score)
        final_capped_score = min(
            weighted_geometric_raw, output_quality_ceiling + config.allowed_process_alpha
        )
        perceived_signal_quality = clamp01(
            0.35 * narrative_fit
            + 0.40 * core_integrity
            + 0.25 * validation_protection
        )
        finish_honesty_flag = compute_finish_honesty_flag(
            perceived_signal_quality,
            core_integrity,
            presentation_clarity,
            validation_protection,
            config,
        )

        provisional_report = SignalSurfaceReport(
            signal_id=signal_input.signal_id,
            damage_class=damage_class,
            repair_mode=repair_mode,
            layer_scores=layer_scores,
            layer_statuses=layer_statuses,
            substrate_integrity_score=substrate_integrity,
            structural_correction_score=structural_correction,
            residual_smoothness_score=residual_smoothness,
            preparation_score=preparation,
            adhesion_score=adhesion,
            narrative_fit_score=narrative_fit,
            validation_protection_score=validation_protection,
            boundary_blending_score=boundary_blending,
            cure_stability_score=cure_stability,
            presentation_clarity_score=presentation_clarity,
            stress_survival_score=stress_survival,
            strict_multiplicative_score=clamp01(strict_multiplicative),
            weighted_geometric_score=weighted_geometric_raw,
            surface_system_score=surface_system_score,
            output_quality_ceiling=output_quality_ceiling,
            final_capped_score=clamp01(final_capped_score),
            visible_distortion_score=visible_distortion,
            perceived_signal_quality=perceived_signal_quality,
            finish_honesty_flag=finish_honesty_flag,
            cure_gate_status=cure_gate_status,
            surface_decision=SurfaceDecision.WAIT,
            bull_surface_state=BullSurfaceState.UNKNOWN_SURFACE_STATE,
            action_permission=False,
            hard_veto_reasons=hard_veto_reasons,
            warnings=warnings,
            recommended_next_steps=[],
            formula_trace={
                "raw_signal_distortion": raw_signal_distortion,
                "residual_signal_error": residual_signal_error,
                "boundary_visibility": boundary_trace["boundary_visibility"],
                "data_mismatch": boundary_trace["data_mismatch"],
                "logic_mismatch": boundary_trace["logic_mismatch"],
                "tone_mismatch": boundary_trace["tone_mismatch"],
                "interface_mismatch": boundary_trace["interface_mismatch"],
                "process_quality_score": process_quality_score,
                "output_quality_ceiling": output_quality_ceiling,
                "weighted_geometric_raw": weighted_geometric_raw,
                "final_capped_score": clamp01(final_capped_score),
                "perceived_quality_gap": clamp01(perceived_signal_quality - core_integrity),
                "action_threshold": config.action_threshold,
                "validation_threshold": config.validation_threshold,
                "stress_threshold": config.stress_threshold,
            },
            transition_log=transition_log,
        )
        action_permission = compute_action_permission(signal_input, provisional_report, config)
        provisional_report.action_permission = action_permission
        provisional_report.surface_decision = map_to_surface_decision(
            provisional_report, signal_input, config
        )
        provisional_report.bull_surface_state = map_to_bull_surface_state(
            provisional_report, signal_input, config
        )
        provisional_report.recommended_next_steps = generate_recommended_next_steps(
            provisional_report
        )
        if provisional_report.surface_decision in {
            SurfaceDecision.REJECT,
            SurfaceDecision.QUARANTINE,
        }:
            provisional_report.transition_log.append(
                "Surface-system flow terminated before presentation or fast-track consideration."
            )
        elif provisional_report.surface_decision == SurfaceDecision.EXECUTE_READY:
            provisional_report.transition_log.append(
                "Surface stack passed policy, cure, validation, stress, and execution-finish gates."
            )
        else:
            provisional_report.transition_log.append(
                "Surface stack preserved hidden-layer discipline before any visible presentation upgrade."
            )
        return provisional_report


def _count_by_decision(reports: list[SignalSurfaceReport], decision: SurfaceDecision) -> int:
    return sum(1 for report in reports if report.surface_decision == decision)


def build_signal_surface_report(
    signal_rows: list[dict[str, Any]] | None,
    runtime_state: dict[str, Any] | None = None,
    write_runtime: bool = True,
    output_path: Path | None = None,
) -> dict[str, Any]:
    rows = [row for row in (signal_rows or []) if isinstance(row, dict)]
    runtime_payload = runtime_state if isinstance(runtime_state, dict) else {}
    engine = SignalSurfaceEngine()
    reports = [engine.evaluate(_normalize_surface_input(row, runtime_payload)) for row in rows]
    primary = max(reports, key=lambda report: report.final_capped_score) if reports else None
    payload: dict[str, Any] = {
        "policy_state": str(
            runtime_payload.get("policy_state")
            or runtime_payload.get("execution_policy", {}).get("policy_state")
            or "RESTRICTED"
        ),
        "signal_surface_state": primary.bull_surface_state.value if primary else BullSurfaceState.UNKNOWN_SURFACE_STATE.value,
        "signal_surface_decision": primary.surface_decision.value if primary else SurfaceDecision.WAIT.value,
        "signal_surface_score": round(primary.final_capped_score, 4) if primary else 0.0,
        "signal_surface_damage_class": primary.damage_class.value if primary else DamageClass.UNKNOWN.value,
        "signal_surface_repair_mode": primary.repair_mode.value if primary else RepairMode.QUARANTINE.value,
        "signal_surface_bull_state": primary.bull_surface_state.value if primary else BullSurfaceState.UNKNOWN_SURFACE_STATE.value,
        "signal_surface_action_permission": bool(primary.action_permission) if primary else False,
        "signal_surface_finish_honesty": primary.finish_honesty_flag.value if primary else FinishHonestyFlag.PRESENTATION_NOT_ALLOWED.value,
        "signal_surface_cure_gate": primary.cure_gate_status.value if primary else CureGateStatus.SHOCK_RESET.value,
        "signals_evaluated": len(reports),
        "surface_counts": {
            "quarantine_count": _count_by_decision(reports, SurfaceDecision.QUARANTINE),
            "reject_count": _count_by_decision(reports, SurfaceDecision.REJECT),
            "wait_count": _count_by_decision(reports, SurfaceDecision.WAIT),
            "repair_count": _count_by_decision(reports, SurfaceDecision.REPAIR),
            "validate_count": _count_by_decision(reports, SurfaceDecision.VALIDATE),
            "promote_count": _count_by_decision(reports, SurfaceDecision.PROMOTE),
            "execute_ready_count": _count_by_decision(reports, SurfaceDecision.EXECUTE_READY),
            "diablo_count": sum(1 for report in reports if report.bull_surface_state == BullSurfaceState.DIABLO_CHAOS_SURFACE_VETO),
            "islero_count": sum(1 for report in reports if report.bull_surface_state == BullSurfaceState.ISLERO_SHOCK_RECLASSIFICATION),
            "huracan_count": sum(1 for report in reports if report.bull_surface_state == BullSurfaceState.HURACAN_FAST_TRACK_SURFACE),
        },
        "per_signal_reports": [report.to_dict() for report in reports],
        "summary": summarize_surface_report(primary) if primary else "surface_decision=WAIT; no compatible signals available",
        "report_path": repo_relative(output_path or SIGNAL_SURFACE_REPORT_PATH),
    }
    payload["operating_mode"] = classify_operating_mode(runtime_payload)
    payload["truth_origin"] = str(runtime_payload.get("truth_origin") or "seeded")
    stamped = stamp_payload(payload, runtime_state=runtime_payload)
    if write_runtime:
        write_json_atomic(output_path or SIGNAL_SURFACE_REPORT_PATH, stamped)
    return stamped
