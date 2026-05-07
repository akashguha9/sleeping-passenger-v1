from __future__ import annotations

import pytest

from scripts.pipeline_health_report import (
    build_pipeline_health_report,
    format_pipeline_health_summary,
)
from scripts.structural_design_engine import (
    FLOW_FIELD,
    FRAGMENTED_FIELD,
    HYBRID_FIELD,
    LOW_STRUCTURE,
    POLICY_SUPPRESSED,
    PRESSURE_FIELD,
    StructuralDesignInputs,
    analyze_structural_design,
    compute_atmosphere_score,
)


def _pressure_inputs() -> StructuralDesignInputs:
    return StructuralDesignInputs(
        density=0.95,
        verticality=0.85,
        proximity=0.84,
        acoustic_containment=0.86,
        structural_exposure=0.82,
        focus_compression=0.96,
        continuity=0.30,
        curvature=0.22,
        coverage=0.28,
        environmental_fit=0.25,
        channeling_efficiency=0.35,
        adaptive_use=0.24,
        original_intent_fit=0.80,
        expansion_impact=0.70,
        renovation_impact=0.76,
        current_usage_fit=0.84,
        constraint_adaptation=0.68,
        input_force_clarity=0.84,
        transfer_node_reliability=0.88,
        grounding_quality=0.82,
        failure_containment=0.78,
        geometry_intensity=0.80,
        density_effect=0.90,
        visibility_effect=0.72,
        acoustic_effect=0.86,
        movement_effect=0.58,
        historical_memory_effect=0.74,
        physical_form_score=0.80,
        occupancy_proxy=0.84,
        acoustic_proxy=0.82,
        memory_proxy=0.76,
        detected_signal=0.88,
        validation_score=0.84,
        durability_score=0.82,
        execution_survivability=0.80,
        source="TEST",
    )


def _flow_inputs() -> StructuralDesignInputs:
    return StructuralDesignInputs(
        density=0.20,
        verticality=0.25,
        proximity=0.28,
        acoustic_containment=0.22,
        structural_exposure=0.18,
        focus_compression=0.24,
        continuity=0.92,
        curvature=0.86,
        coverage=0.84,
        environmental_fit=0.82,
        channeling_efficiency=0.96,
        adaptive_use=0.80,
        original_intent_fit=0.82,
        expansion_impact=0.74,
        renovation_impact=0.78,
        current_usage_fit=0.85,
        constraint_adaptation=0.72,
        input_force_clarity=0.86,
        transfer_node_reliability=0.84,
        grounding_quality=0.83,
        failure_containment=0.80,
        geometry_intensity=0.70,
        density_effect=0.45,
        visibility_effect=0.76,
        acoustic_effect=0.68,
        movement_effect=0.88,
        historical_memory_effect=0.72,
        physical_form_score=0.78,
        occupancy_proxy=0.82,
        acoustic_proxy=0.76,
        memory_proxy=0.74,
        detected_signal=0.86,
        validation_score=0.82,
        durability_score=0.80,
        execution_survivability=0.81,
        source="TEST",
    )


def test_high_san_siro_like_inputs_classify_as_pressure_field() -> None:
    result = analyze_structural_design(_pressure_inputs())
    assert result.structure_state == PRESSURE_FIELD
    assert result.pressure_score > result.flow_score
    assert "San Siro" in result.explanation


def test_high_velodrome_like_inputs_classify_as_flow_field() -> None:
    result = analyze_structural_design(_flow_inputs())
    assert result.structure_state == FLOW_FIELD
    assert result.flow_score > result.pressure_score
    assert "Velodrome" in result.explanation


def test_high_pressure_and_flow_classify_as_hybrid_field() -> None:
    inputs = _pressure_inputs()
    inputs.continuity = 0.86
    inputs.curvature = 0.78
    inputs.coverage = 0.80
    inputs.environmental_fit = 0.75
    inputs.channeling_efficiency = 0.84
    inputs.adaptive_use = 0.78
    result = analyze_structural_design(inputs)
    assert result.structure_state == HYBRID_FIELD


def test_low_values_classify_as_low_structure() -> None:
    result = analyze_structural_design(StructuralDesignInputs(source="TEST"))
    assert result.structure_state == LOW_STRUCTURE


def test_similar_weak_pressure_and_flow_classify_as_fragmented_field() -> None:
    result = analyze_structural_design(
        StructuralDesignInputs(
            density=0.45,
            verticality=0.45,
            proximity=0.45,
            acoustic_containment=0.45,
            structural_exposure=0.45,
            focus_compression=0.45,
            continuity=0.48,
            curvature=0.48,
            coverage=0.48,
            environmental_fit=0.48,
            channeling_efficiency=0.48,
            adaptive_use=0.48,
            source="TEST",
        )
    )
    assert result.structure_state == FRAGMENTED_FIELD


def test_policy_veto_forces_policy_suppressed() -> None:
    result = analyze_structural_design(_pressure_inputs(), policy_veto=True)
    assert result.structure_state == POLICY_SUPPRESSED
    assert result.investable_structural_signal == 0.0


def test_scores_are_clamped_between_zero_and_one() -> None:
    inputs = StructuralDesignInputs(
        density=5.0,
        verticality=5.0,
        proximity=5.0,
        acoustic_containment=5.0,
        structural_exposure=5.0,
        focus_compression=5.0,
        continuity=5.0,
        curvature=5.0,
        coverage=5.0,
        environmental_fit=5.0,
        channeling_efficiency=5.0,
        adaptive_use=5.0,
        original_intent_fit=5.0,
        expansion_impact=5.0,
        renovation_impact=5.0,
        current_usage_fit=5.0,
        constraint_adaptation=5.0,
        input_force_clarity=5.0,
        transfer_node_reliability=5.0,
        grounding_quality=5.0,
        failure_containment=5.0,
        geometry_intensity=5.0,
        density_effect=5.0,
        visibility_effect=5.0,
        acoustic_effect=5.0,
        movement_effect=5.0,
        historical_memory_effect=5.0,
        physical_form_score=5.0,
        occupancy_proxy=5.0,
        acoustic_proxy=5.0,
        memory_proxy=5.0,
        detected_signal=5.0,
        validation_score=5.0,
        durability_score=5.0,
        execution_survivability=5.0,
        source="TEST",
    )
    result = analyze_structural_design(inputs)
    assert 0.0 <= result.pressure_score <= 1.0
    assert 0.0 <= result.flow_score <= 1.0
    assert 0.0 <= result.architecture_score <= 1.0
    assert 0.0 <= result.investable_structural_signal <= 1.0


def test_missing_default_inputs_do_not_crash() -> None:
    result = analyze_structural_design(StructuralDesignInputs())
    assert result.structure_state == LOW_STRUCTURE
    assert DEFAULT_WARNING_IN_RESULT(result.warnings)


def DEFAULT_WARNING_IN_RESULT(warnings: list[str]) -> bool:
    return any("safe defaults" in warning.lower() for warning in warnings)


def test_atmosphere_score_multiplies_proxies_and_stays_clamped() -> None:
    inputs = StructuralDesignInputs(
        physical_form_score=0.8,
        occupancy_proxy=0.5,
        acoustic_proxy=0.75,
        memory_proxy=0.6,
        source="TEST",
    )
    score = compute_atmosphere_score(inputs)
    assert score == pytest.approx(0.18)


def test_architecture_score_is_deterministic() -> None:
    inputs = _pressure_inputs()
    first = analyze_structural_design(inputs)
    second = analyze_structural_design(inputs)
    assert first.architecture_score == second.architecture_score
    assert first.structural_coherence == second.structural_coherence


def test_explanation_contains_correct_dominant_logic() -> None:
    result = analyze_structural_design(_flow_inputs())
    assert result.dominant_logic == "FLOW_DOMINANT"
    assert "continuity variables dominate pressure variables" in result.explanation


def test_diagnostics_pipeline_still_runs_and_surfaces_structural_design_state() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    summary = format_pipeline_health_summary(report)
    state = report["structural_design_state"]
    assert state["structure_state"] == POLICY_SUPPRESSED
    assert "pressure_score" in state
    assert "flow_score" in state
    assert "structural_design_state=POLICY_SUPPRESSED" in summary
