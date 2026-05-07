from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        STRUCTURAL_DESIGN_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_source_mode,
        repo_relative,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        STRUCTURAL_DESIGN_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_source_mode,
        repo_relative,
        write_json_atomic,
    )
    from signal_conversion_monitor import build_signal_conversion_report  # type: ignore[no-redef]


PRESSURE_FIELD = "PRESSURE_FIELD"
FLOW_FIELD = "FLOW_FIELD"
HYBRID_FIELD = "HYBRID_FIELD"
FRAGMENTED_FIELD = "FRAGMENTED_FIELD"
LOW_STRUCTURE = "LOW_STRUCTURE"
UNKNOWN_STRUCTURE = "UNKNOWN_STRUCTURE"
POLICY_SUPPRESSED = "POLICY_SUPPRESSED"

PRESSURE_WEIGHTS = {
    "density": 0.20,
    "verticality": 0.15,
    "proximity": 0.15,
    "acoustic_containment": 0.15,
    "structural_exposure": 0.15,
    "focus_compression": 0.20,
}

FLOW_WEIGHTS = {
    "continuity": 0.20,
    "curvature": 0.15,
    "coverage": 0.15,
    "environmental_fit": 0.15,
    "channeling_efficiency": 0.20,
    "adaptive_use": 0.15,
}

CURRENT_IDENTITY_WEIGHTS = {
    "original_intent_fit": 0.15,
    "expansion_impact": 0.20,
    "renovation_impact": 0.25,
    "current_usage_fit": 0.25,
    "constraint_adaptation": 0.15,
}

EMOTIONAL_GEOMETRY_WEIGHTS = {
    "geometry_intensity": 0.18,
    "density_effect": 0.18,
    "visibility_effect": 0.14,
    "acoustic_effect": 0.18,
    "movement_effect": 0.14,
    "historical_memory_effect": 0.18,
}

DEFAULT_SOURCE = "DEFAULT_STRUCTURAL_ANALYSIS"
DEFAULT_WARNING = "No live structural input source connected; using safe defaults."
ADVISORY_WARNING = (
    "Structural design layer is advisory only; it cannot override policy, chaos, or execution guards."
)


@dataclass(slots=True)
class StructuralDesignInputs:
    density: float = 0.0
    verticality: float = 0.0
    proximity: float = 0.0
    acoustic_containment: float = 0.0
    structural_exposure: float = 0.0
    focus_compression: float = 0.0
    continuity: float = 0.0
    curvature: float = 0.0
    coverage: float = 0.0
    environmental_fit: float = 0.0
    channeling_efficiency: float = 0.0
    adaptive_use: float = 0.0
    original_intent_fit: float = 0.0
    expansion_impact: float = 0.0
    renovation_impact: float = 0.0
    current_usage_fit: float = 0.0
    constraint_adaptation: float = 0.0
    input_force_clarity: float = 0.0
    transfer_node_reliability: float = 0.0
    grounding_quality: float = 0.0
    failure_containment: float = 0.0
    geometry_intensity: float = 0.0
    density_effect: float = 0.0
    visibility_effect: float = 0.0
    acoustic_effect: float = 0.0
    movement_effect: float = 0.0
    historical_memory_effect: float = 0.0
    physical_form_score: float = 0.0
    occupancy_proxy: float = 0.0
    acoustic_proxy: float = 0.0
    memory_proxy: float = 0.0
    detected_signal: float = 0.0
    validation_score: float = 0.0
    durability_score: float = 0.0
    execution_survivability: float = 0.0
    system_name: str | None = None
    source: str = DEFAULT_SOURCE
    notes: str | None = None
    feature_layer: str | None = None
    structural_expression_type: str | None = None


@dataclass(slots=True)
class StructuralDesignScores:
    pressure_score: float
    flow_score: float
    current_identity_score: float
    load_path_coherence: float
    emotional_geometry_score: float
    atmosphere_score: float
    architecture_score: float
    structural_coherence: float
    investable_structural_signal: float
    structure_state: str
    dominant_logic: str
    explanation: str
    warnings: list[str] = field(default_factory=list)
    source: str = DEFAULT_SOURCE
    objective_clarity: float = 0.0
    emergent_experience_quality: float = 0.0


def clamp01(x: Any) -> float:
    try:
        value = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def weighted_sum(features: dict[str, float], weights: dict[str, float]) -> float:
    total = 0.0
    for name, weight in weights.items():
        total += weight * clamp01(features.get(name, 0.0))
    return clamp01(total)


def compute_pressure_score(inputs: StructuralDesignInputs) -> float:
    return weighted_sum(
        {
            "density": inputs.density,
            "verticality": inputs.verticality,
            "proximity": inputs.proximity,
            "acoustic_containment": inputs.acoustic_containment,
            "structural_exposure": inputs.structural_exposure,
            "focus_compression": inputs.focus_compression,
        },
        PRESSURE_WEIGHTS,
    )


def compute_flow_score(inputs: StructuralDesignInputs) -> float:
    return weighted_sum(
        {
            "continuity": inputs.continuity,
            "curvature": inputs.curvature,
            "coverage": inputs.coverage,
            "environmental_fit": inputs.environmental_fit,
            "channeling_efficiency": inputs.channeling_efficiency,
            "adaptive_use": inputs.adaptive_use,
        },
        FLOW_WEIGHTS,
    )


def compute_current_identity_score(inputs: StructuralDesignInputs) -> float:
    return weighted_sum(
        {
            "original_intent_fit": inputs.original_intent_fit,
            "expansion_impact": inputs.expansion_impact,
            "renovation_impact": inputs.renovation_impact,
            "current_usage_fit": inputs.current_usage_fit,
            "constraint_adaptation": inputs.constraint_adaptation,
        },
        CURRENT_IDENTITY_WEIGHTS,
    )


def compute_load_path_coherence(inputs: StructuralDesignInputs) -> float:
    return clamp01(
        clamp01(inputs.input_force_clarity)
        * clamp01(inputs.transfer_node_reliability)
        * clamp01(inputs.grounding_quality)
        * clamp01(inputs.failure_containment)
    )


def compute_emotional_geometry_score(inputs: StructuralDesignInputs) -> float:
    return weighted_sum(
        {
            "geometry_intensity": inputs.geometry_intensity,
            "density_effect": inputs.density_effect,
            "visibility_effect": inputs.visibility_effect,
            "acoustic_effect": inputs.acoustic_effect,
            "movement_effect": inputs.movement_effect,
            "historical_memory_effect": inputs.historical_memory_effect,
        },
        EMOTIONAL_GEOMETRY_WEIGHTS,
    )


def compute_atmosphere_score(inputs: StructuralDesignInputs) -> float:
    return clamp01(
        clamp01(inputs.physical_form_score)
        * clamp01(inputs.occupancy_proxy)
        * clamp01(inputs.acoustic_proxy)
        * clamp01(inputs.memory_proxy)
    )


def _compute_objective_clarity(inputs: StructuralDesignInputs) -> float:
    return weighted_sum(
        {
            "original_intent_fit": inputs.original_intent_fit,
            "current_usage_fit": inputs.current_usage_fit,
            "input_force_clarity": inputs.input_force_clarity,
            "constraint_adaptation": inputs.constraint_adaptation,
        },
        {
            "original_intent_fit": 0.30,
            "current_usage_fit": 0.30,
            "input_force_clarity": 0.25,
            "constraint_adaptation": 0.15,
        },
    )


def _compute_structural_coherence(
    pressure_score: float,
    flow_score: float,
    current_identity_score: float,
    load_path_coherence: float,
) -> float:
    dominant_field = max(pressure_score, flow_score)
    logic_alignment = 1.0 - abs(pressure_score - flow_score)
    return clamp01(
        0.35 * dominant_field
        + 0.25 * current_identity_score
        + 0.25 * load_path_coherence
        + 0.15 * logic_alignment
    )


def _compute_emergent_experience_quality(
    emotional_geometry_score: float,
    atmosphere_score: float,
) -> float:
    return clamp01((emotional_geometry_score * 0.55) + (atmosphere_score * 0.45))


def classify_structure_state(
    scores: StructuralDesignScores | dict[str, Any],
    policy_veto: bool = False,
) -> str:
    if policy_veto:
        return POLICY_SUPPRESSED
    if isinstance(scores, StructuralDesignScores):
        pressure_score = scores.pressure_score
        flow_score = scores.flow_score
    else:
        pressure_score = clamp01(scores.get("pressure_score", 0.0))
        flow_score = clamp01(scores.get("flow_score", 0.0))
    if pressure_score >= 0.70 and pressure_score - flow_score >= 0.15:
        return PRESSURE_FIELD
    if flow_score >= 0.70 and flow_score - pressure_score >= 0.15:
        return FLOW_FIELD
    if pressure_score >= 0.60 and flow_score >= 0.60:
        return HYBRID_FIELD
    if pressure_score < 0.35 and flow_score < 0.35:
        return LOW_STRUCTURE
    if abs(pressure_score - flow_score) < 0.10 and max(pressure_score, flow_score) < 0.60:
        return FRAGMENTED_FIELD
    return UNKNOWN_STRUCTURE


def _dominant_logic(structure_state: str, pressure_score: float, flow_score: float) -> str:
    if structure_state == POLICY_SUPPRESSED:
        return "POLICY_VETO"
    if structure_state == PRESSURE_FIELD:
        return "PRESSURE_DOMINANT"
    if structure_state == FLOW_FIELD:
        return "FLOW_DOMINANT"
    if structure_state == HYBRID_FIELD:
        return "HYBRID_PRESSURE_FLOW"
    if structure_state == FRAGMENTED_FIELD:
        return "FRAGMENTED_LOGIC"
    if structure_state == LOW_STRUCTURE:
        return "WEAK_ARCHITECTURE"
    return "PRESSURE_DOMINANT" if pressure_score >= flow_score else "FLOW_DOMINANT"


def _explanation(structure_state: str) -> str:
    if structure_state == POLICY_SUPPRESSED:
        return (
            "POLICY_SUPPRESSED: policy veto overrides structural attractiveness. "
            "Structural design remains advisory only."
        )
    if structure_state == PRESSURE_FIELD:
        return (
            "PRESSURE_FIELD: compression variables dominate flow variables. System behaves "
            "like San Siro: density, focus, and exposed structure amplify decision pressure."
        )
    if structure_state == FLOW_FIELD:
        return (
            "FLOW_FIELD: continuity variables dominate pressure variables. System behaves "
            "like Velodrome: curvature, coverage, and channeling create adaptive flow."
        )
    if structure_state == HYBRID_FIELD:
        return (
            "HYBRID_FIELD: pressure and flow variables both clear threshold. System balances "
            "San Siro compression with Velodrome continuity."
        )
    if structure_state == FRAGMENTED_FIELD:
        return (
            "FRAGMENTED_FIELD: neither pressure nor flow logic cleanly dominates. Form shows "
            "partial structure without coherent governing behavior."
        )
    if structure_state == LOW_STRUCTURE:
        return (
            "LOW_STRUCTURE: both pressure and flow variables remain weak. Architecture should "
            "not be over-trusted until coherence improves."
        )
    return (
        "UNKNOWN_STRUCTURE: structural signals are mixed and below confident classification. "
        "Treat the layer as explanatory only."
    )


def analyze_structural_design(
    inputs: StructuralDesignInputs,
    policy_veto: bool = False,
) -> StructuralDesignScores:
    pressure_score = compute_pressure_score(inputs)
    flow_score = compute_flow_score(inputs)
    current_identity_score = compute_current_identity_score(inputs)
    load_path_coherence = compute_load_path_coherence(inputs)
    emotional_geometry_score = compute_emotional_geometry_score(inputs)
    atmosphere_score = compute_atmosphere_score(inputs)
    objective_clarity = _compute_objective_clarity(inputs)
    structural_coherence = _compute_structural_coherence(
        pressure_score,
        flow_score,
        current_identity_score,
        load_path_coherence,
    )
    emergent_experience_quality = _compute_emergent_experience_quality(
        emotional_geometry_score,
        atmosphere_score,
    )
    architecture_score = clamp01(
        objective_clarity * structural_coherence * emergent_experience_quality
    )
    investable_structural_signal = clamp01(
        clamp01(inputs.detected_signal)
        * structural_coherence
        * load_path_coherence
        * atmosphere_score
        * clamp01(inputs.validation_score)
        * clamp01(inputs.durability_score)
        * clamp01(inputs.execution_survivability)
        * (0.0 if policy_veto else 1.0)
    )
    provisional = {
        "pressure_score": pressure_score,
        "flow_score": flow_score,
    }
    structure_state = classify_structure_state(provisional, policy_veto=policy_veto)
    warnings: list[str] = [ADVISORY_WARNING]
    if inputs.source == DEFAULT_SOURCE:
        warnings.insert(0, DEFAULT_WARNING)
    dominant_logic = _dominant_logic(structure_state, pressure_score, flow_score)
    return StructuralDesignScores(
        pressure_score=pressure_score,
        flow_score=flow_score,
        current_identity_score=current_identity_score,
        load_path_coherence=load_path_coherence,
        emotional_geometry_score=emotional_geometry_score,
        atmosphere_score=atmosphere_score,
        architecture_score=architecture_score,
        structural_coherence=structural_coherence,
        investable_structural_signal=investable_structural_signal,
        structure_state=structure_state,
        dominant_logic=dominant_logic,
        explanation=_explanation(structure_state),
        warnings=warnings,
        source=inputs.source,
        objective_clarity=objective_clarity,
        emergent_experience_quality=emergent_experience_quality,
    )


def build_structural_design_report(
    *,
    runtime_state: dict[str, Any],
    reflection_context: dict[str, Any],
    attention_proxy_report: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    asset_durability_report: dict[str, Any],
    execution_integrity_report: dict[str, Any],
    policy_veto: bool,
    output_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    validation_row = reflection_context.get("validation_row", {})
    active_blockers = runtime_state.get("active_blockers", [])
    if not isinstance(active_blockers, list):
        active_blockers = []
    density_proxy = clamp01(
        0.45 * (1.0 if active_blockers else 0.0)
        + 0.35 * float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0)
        + 0.20 * (1.0 if signal_refinery_report.get("launch_control", {}).get("decision_grade_signal_count", 0) else 0.0)
    )
    flow_proxy = clamp01(
        0.40 * float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0)
        + 0.30 * float(validation_row.get("source_quality_score", 0.0) or 0.0)
        + 0.30 * float(validation_row.get("first_order_score", 0.0) or 0.0)
    )
    inputs = StructuralDesignInputs(
        density=density_proxy,
        verticality=clamp01(float(validation_row.get("price_lead_score", 0.0) or 0.0)),
        proximity=clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0)),
        acoustic_containment=clamp01(float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0)),
        structural_exposure=clamp01(1.0 - float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
        focus_compression=clamp01(1.0 if active_blockers else float(validation_row.get("validation_score", 0.0) or 0.0)),
        continuity=flow_proxy,
        curvature=clamp01(float(validation_row.get("novelty_score", 0.0) or 0.0)),
        coverage=clamp01(float(validation_row.get("source_quality_score", 0.0) or 0.0)),
        environmental_fit=clamp01(float(validation_row.get("repricing_headroom_score", 0.0) or 0.0)),
        channeling_efficiency=clamp01(float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0)),
        adaptive_use=clamp01(float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
        original_intent_fit=clamp01(float(validation_row.get("validation_score", 0.0) or 0.0)),
        expansion_impact=clamp01(float(validation_row.get("novelty_score", 0.0) or 0.0)),
        renovation_impact=clamp01(float(validation_row.get("repricing_headroom_score", 0.0) or 0.0)),
        current_usage_fit=clamp01(float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0)),
        constraint_adaptation=clamp01(float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
        input_force_clarity=clamp01(float(reflection_context.get("evidence_strength", 0.0) or 0.0)),
        transfer_node_reliability=clamp01(float(validation_row.get("source_quality_score", 0.0) or 0.0)),
        grounding_quality=clamp01(float(asset_durability_report.get("hundred_wash_score", 0.0) or 0.0)),
        failure_containment=clamp01(float(execution_integrity_report.get("execution_integrity_score", 0.0) or 0.0)),
        geometry_intensity=clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0)),
        density_effect=density_proxy,
        visibility_effect=clamp01(float(validation_row.get("source_quality_score", 0.0) or 0.0)),
        acoustic_effect=clamp01(float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0)),
        movement_effect=flow_proxy,
        historical_memory_effect=clamp01(
            min(
                1.0,
                float(signal_refinery_report.get("repeatability_tracker", {}).get("rolling_expectancy_pct", 0.0) or 0.0) / 100.0,
            )
        ),
        physical_form_score=clamp01(float(validation_row.get("validation_score", 0.0) or 0.0)),
        occupancy_proxy=clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0)),
        acoustic_proxy=clamp01(float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0)),
        memory_proxy=clamp01(
            min(
                1.0,
                float(signal_refinery_report.get("repeatability_tracker", {}).get("rolling_expectancy_pct", 0.0) or 0.0) / 100.0,
            )
        ),
        detected_signal=clamp01(float(reflection_context.get("evidence_strength", 0.0) or 0.0)),
        validation_score=clamp01(float(validation_row.get("validation_score", 0.0) or 0.0)),
        durability_score=clamp01(float(asset_durability_report.get("hundred_wash_score", 0.0) or 0.0)),
        execution_survivability=clamp01(float(execution_integrity_report.get("execution_integrity_score", 0.0) or 0.0)),
        system_name=str(reflection_context.get("primary_ticker") or "pipeline_health"),
        source=DEFAULT_SOURCE,
        notes="Proxy-derived structural model from diagnostics runtime state.",
        feature_layer="diagnostics",
        structural_expression_type="SAN_SIRO_VELODROME_PROXY",
    )
    scores = analyze_structural_design(inputs, policy_veto=policy_veto)
    report = asdict(scores)
    report["inputs"] = asdict(inputs)
    report["policy_veto"] = bool(policy_veto)
    report["source_mode"] = get_source_mode()
    report["report_path"] = repo_relative(output_path or STRUCTURAL_DESIGN_REPORT_PATH)
    if write_runtime:
        write_json_atomic(output_path or STRUCTURAL_DESIGN_REPORT_PATH, report, stamp=True)
    return report


def format_structural_design_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Structural Design Engine",
            f"structure_state={report.get('structure_state', UNKNOWN_STRUCTURE)}",
            f"pressure_score={report.get('pressure_score', 0.0)}",
            f"flow_score={report.get('flow_score', 0.0)}",
            f"load_path_coherence={report.get('load_path_coherence', 0.0)}",
            f"atmosphere_score={report.get('atmosphere_score', 0.0)}",
            f"dominant_logic={report.get('dominant_logic', 'UNKNOWN')}",
            f"source={report.get('source', DEFAULT_SOURCE)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the structural design analysis layer."
    )
    parser.add_argument("--summary", action="store_true", help="Emit a compact summary.")
    parser.add_argument("--write-runtime", action="store_true", help="Persist runtime artifact.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    report = build_structural_design_report(
        runtime_state=runtime_state,
        reflection_context={},
        attention_proxy_report={},
        signal_refinery_report={},
        asset_durability_report={},
        execution_integrity_report={},
        policy_veto=not bool(runtime_state.get("execution_policy", {}).get("allow_new_risk", False)),
        write_runtime=args.write_runtime,
    )
    if args.summary:
        print(format_structural_design_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
