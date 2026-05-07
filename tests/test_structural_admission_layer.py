from __future__ import annotations

import pytest

from scripts.pipeline_health_report import (
    build_pipeline_health_report,
    format_pipeline_health_summary,
)
from scripts.structural_admission_layer import (
    AdmissionClass,
    BurnProfile,
    DesignIntegrityInput,
    DomainInstrumentInput,
    EngineClass,
    EnvironmentInput,
    OperatorClarityInput,
    PrimitiveCompetenceInput,
    ProgressionInput,
    RealityAnchorInput,
    RegimeClass,
    RejectionReason,
    SignalGraphInput,
    StructuralAdmissionInput,
    TransitionClass,
    TransitionInput,
    TrapdoorInput,
    TrustInput,
    UseCaseFitInput,
    classify_materiality,
    classify_regime,
    detect_trapdoor,
    estimate_burn_profile,
    evaluate_design_integrity,
    evaluate_domain_fit,
    evaluate_operator_clarity,
    evaluate_reality_alignment,
    evaluate_signal_harmony,
    evaluate_structural_admission,
    evaluate_transition_quality,
    evaluate_trust,
    evaluate_use_case_fit,
    select_engine,
)


def _base_input() -> StructuralAdmissionInput:
    return StructuralAdmissionInput(
        design_integrity=DesignIntegrityInput(
            readability_score=0.8,
            structure_score=0.8,
            traceability_score=0.8,
            risk_visibility_score=0.8,
            execution_clarity_score=0.8,
            utility_high=True,
        ),
        domain_instrument=DomainInstrumentInput(
            instrument_domain="MARKET_STRUCTURE",
            required_variable_domain="MARKET_STRUCTURE",
        ),
        environment=EnvironmentInput(
            volatility=0.3,
            liquidity=0.8,
            spread=0.2,
            news_intensity=0.2,
            correlation_break=0.2,
            execution_friction=0.2,
            selected_engine=EngineClass.BIC_ENGINE,
        ),
        burn_profile=BurnProfile(
            ignition_speed=0.6,
            duration_score=0.8,
            stability_score=0.8,
            environment_resistance_score=0.8,
            decay_rate=0.2,
        ),
        signal_graph=SignalGraphInput(
            node_values={"PRICE": 0.8, "VOLUME": 0.8, "NEWS": 0.7},
            expected_edges=[("PRICE", "VOLUME"), ("NEWS", "PRICE")],
            observed_edges=[("PRICE", "VOLUME", "confirm"), ("NEWS", "PRICE", "confirm")],
        ),
        progression=ProgressionInput(
            observed_sequence=["EVENT", "NEWS", "SENTIMENT", "VOLUME", "PRICE", "OPTIONS"],
            required_confirmations=["PRICE", "VOLUME"],
        ),
        transition=TransitionInput(
            curvature=0.6,
            oscillation=0.3,
            resolution_strength=0.85,
            trapdoor_risk=0.1,
        ),
        trapdoor=TrapdoorInput(
            expected_path_deviation=0.2,
            impact=0.3,
            speed=0.3,
        ),
        trust=TrustInput(
            observability=0.9,
            auditability=0.9,
            explainability=0.9,
            high_stakes=True,
        ),
        operator_clarity=OperatorClarityInput(
            dashboard_readability=0.9,
            noise=0.1,
            cognitive_load=0.1,
            alert_overload=0.1,
            ambiguity=0.1,
        ),
        reality_anchor=RealityAnchorInput(
            freshness=0.9,
            external_confirmation=0.9,
            regime_consistency=0.9,
            time_since_validation_hours=1.0,
        ),
        primitive_competence=PrimitiveCompetenceInput(
            primitive_understanding=0.9,
            interface_leverage=0.9,
            signal_defined=True,
            variable_defined=True,
            instrument_validity_explained=True,
            invalidation_defined=True,
            regime_defined=True,
            wrong_proof_defined=True,
            fallback_defined=True,
        ),
        use_case_fit=UseCaseFitInput(
            task_context="FINAL_ADMISSION",
            tool_class="SPECIALIST_TOOL",
            specialization_match=0.9,
            generalist_output_used_for_execution=False,
        ),
        validation_strength=0.9,
        chaos_veto=False,
        policy_veto=False,
        source="TEST",
    )


def _has_reason(result, code: RejectionReason) -> bool:
    return any(reason["code"] == code.value for reason in result.rejection_reasons)


def test_crocs_utility_paradox_rejects_utility_without_structure() -> None:
    score, reasons = evaluate_design_integrity(
        DesignIntegrityInput(
            readability_score=0.2,
            structure_score=0.2,
            traceability_score=0.2,
            risk_visibility_score=0.2,
            execution_clarity_score=0.2,
            utility_high=True,
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.UTILITY_WITHOUT_STRUCTURE.value


def test_scale_vs_caliper_domain_mismatch_rejects() -> None:
    score, reasons = evaluate_domain_fit(
        DomainInstrumentInput(
            instrument_domain="PRICE_ACTION",
            required_variable_domain="FUNDAMENTALS",
        )
    )
    assert score.score == 0.0
    assert reasons[0].code == RejectionReason.DOMAIN_MISMATCH.value


def test_triund_lighter_failure_uses_matchbox_engine_in_chaos() -> None:
    score, regime, engine, reasons = evaluate_structural_environment_case()
    assert regime == RegimeClass.CHAOS
    assert engine == EngineClass.MATCHBOX_ENGINE
    assert score.passed is False
    assert reasons[0].code == RejectionReason.ENVIRONMENT_MISMATCH.value


def evaluate_structural_environment_case():
    from scripts.structural_admission_layer import evaluate_environment_fit

    return evaluate_environment_fit(
        EnvironmentInput(
            volatility=0.95,
            liquidity=0.2,
            spread=0.8,
            news_intensity=0.9,
            correlation_break=0.9,
            execution_friction=0.95,
            selected_engine=EngineClass.BIC_ENGINE,
        )
    )


def test_wooden_match_is_less_durable_than_wax_match() -> None:
    wood_profile = BurnProfile(
        ignition_speed=0.9,
        duration_score=0.25,
        stability_score=0.35,
        environment_resistance_score=0.2,
        decay_rate=0.8,
    )
    wax_profile = BurnProfile(
        ignition_speed=0.55,
        duration_score=0.85,
        stability_score=0.85,
        environment_resistance_score=0.8,
        decay_rate=0.1,
    )
    _, wood_score = estimate_burn_profile(wood_profile)
    _, wax_score = estimate_burn_profile(wax_profile)
    wood_class, _ = classify_materiality(wood_profile)
    wax_class, _ = classify_materiality(wax_profile)
    assert wood_class.value in {"WOOD_SIGNAL", "FOAM_SIGNAL"}
    assert wax_class.value == "WAX_SIGNAL"
    assert wax_score > wood_score


def test_boxing_scale_rejects_low_trust_observability() -> None:
    score, reasons = evaluate_trust(
        TrustInput(
            observability=0.2,
            auditability=0.3,
            explainability=0.2,
            high_stakes=True,
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.LOW_TRUST_OBSERVABILITY.value


def test_yellow_light_rejects_low_operator_clarity() -> None:
    score, reasons = evaluate_operator_clarity(
        OperatorClarityInput(
            dashboard_readability=0.4,
            noise=0.8,
            cognitive_load=0.8,
            alert_overload=0.7,
            ambiguity=0.8,
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.LOW_OPERATOR_CLARITY.value


def test_battery_watch_drift_rejects_stale_reality_alignment() -> None:
    score, reasons = evaluate_reality_alignment(
        RealityAnchorInput(
            freshness=0.2,
            external_confirmation=0.2,
            regime_consistency=0.3,
            time_since_validation_hours=72.0,
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.DRIFT_FROM_REALITY.value


def test_ableton_without_notes_rejects_missing_primitive_understanding() -> None:
    from scripts.structural_admission_layer import evaluate_primitive_competence

    score, reasons = evaluate_primitive_competence(
        PrimitiveCompetenceInput(
            primitive_understanding=0.9,
            interface_leverage=0.9,
            signal_defined=True,
            variable_defined=False,
            instrument_validity_explained=False,
            invalidation_defined=False,
            regime_defined=False,
            wrong_proof_defined=False,
            fallback_defined=False,
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.NO_PRIMITIVE_UNDERSTANDING.value


def test_swiss_knife_misuse_rejects_generalist_for_execution() -> None:
    score, reasons = evaluate_use_case_fit(
        UseCaseFitInput(
            task_context="EXECUTION",
            tool_class="GENERALIST_TOOL",
            specialization_match=0.9,
            generalist_output_used_for_execution=True,
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.MISUSED_GENERALIST.value


def test_signal_graph_dissonance_rejects_conflicting_edges() -> None:
    score, _, reasons = evaluate_signal_harmony(
        SignalGraphInput(
            node_values={"PRICE": 0.8, "VOLUME": 0.2, "LIQUIDITY": 0.1},
            expected_edges=[("PRICE", "VOLUME"), ("LIQUIDITY", "PRICE")],
            observed_edges=[("PRICE", "VOLUME", "conflict"), ("LIQUIDITY", "PRICE", "conflict")],
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.SIGNAL_DISSONANCE.value


def test_gamaka_trapdoor_blocks_execution_candidate() -> None:
    trapdoor_risk, trapdoor_reasons = detect_trapdoor(
        TrapdoorInput(expected_path_deviation=0.95, impact=0.9, speed=0.85)
    )
    transition_score, transition_class, transition_reasons = evaluate_transition_quality(
        TransitionInput(curvature=0.8, oscillation=0.7, resolution_strength=0.2, trapdoor_risk=trapdoor_risk)
    )
    assert transition_class == TransitionClass.TRAPDOOR
    assert trapdoor_reasons[0].code == RejectionReason.TRAPDOOR_EVENT.value
    assert transition_score.hard_reject is True
    assert transition_reasons[0].code == RejectionReason.TRAPDOOR_EVENT.value


def test_bottleneck_admission_uses_min_not_average() -> None:
    payload = _base_input()
    payload.use_case_fit.specialization_match = 0.3
    result = evaluate_structural_admission(payload)
    assert result.admission_score == 0.3


def test_diagnostic_score_does_not_override_low_bottleneck() -> None:
    payload = _base_input()
    payload.use_case_fit.specialization_match = 0.35
    result = evaluate_structural_admission(payload)
    assert result.diagnostic_score > result.admission_score
    assert result.admission_class != AdmissionClass.ADMIT_EXECUTION_CANDIDATE.value


def test_policy_hierarchy_keeps_chaos_veto_supreme() -> None:
    payload = _base_input()
    payload.policy_veto = True
    result = evaluate_structural_admission(payload)
    assert result.chaos_veto is True
    assert result.admission_class == AdmissionClass.CHAOS_VETO.value


def test_progression_validator_rejects_broken_order() -> None:
    from scripts.structural_admission_layer import validate_progression

    score, reasons = validate_progression(
        ProgressionInput(
            observed_sequence=["PRICE", "EVENT", "VOLUME"],
            required_confirmations=["PRICE", "VOLUME"],
        )
    )
    assert score.passed is False
    assert reasons[0].code == RejectionReason.INVALID_PROGRESSION.value


def test_structural_admission_integration_surfaces_diagnostics_state() -> None:
    report = build_pipeline_health_report(write_runtime=False)
    summary = format_pipeline_health_summary(report)
    state = report["structural_admission_state"]
    assert state["admission_class"] == AdmissionClass.CHAOS_VETO.value
    assert "component_scores" in state
    assert report["structural_admission_chaos_veto"] is True
    assert "structural_admission_class=CHAOS_VETO" in summary
