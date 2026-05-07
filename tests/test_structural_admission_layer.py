from __future__ import annotations

import pytest

from scripts.pipeline_health_report import (
    build_pipeline_health_report,
    format_pipeline_health_summary,
)
from scripts.structural_admission_layer import (
    AdmissionClass,
    BehavioralSkinInput,
    BurnProfile,
    BuyerClass,
    BuyerTypeInput,
    DesignIntegrityInput,
    DomainInstrumentInput,
    EngineClass,
    EnvironmentInput,
    ExecutionSurvivabilityInput,
    ForceFlowInput,
    MaintenanceCostInput,
    OperatorClarityInput,
    PeakMomentInput,
    PrimitiveCompetenceInput,
    ProgressionInput,
    RecoveryQualityInput,
    RealityAnchorInput,
    RegimeClass,
    RejectionReason,
    SourceValidationInput,
    SignalGraphInput,
    StructuralAdmissionInput,
    TransitionClass,
    TransitionInput,
    TrapdoorInput,
    TrustInput,
    UseCaseFitInput,
    ActorResponseInput,
    BullState,
    classify_materiality,
    classify_buyer_type,
    classify_regime,
    compute_bull_state,
    detect_trapdoor,
    estimate_burn_profile,
    evaluate_actor_response,
    evaluate_behavioral_skin,
    evaluate_buyer_alignment,
    evaluate_design_integrity,
    evaluate_domain_fit,
    evaluate_execution_survivability,
    evaluate_force_flow,
    evaluate_maintenance_survival,
    evaluate_operator_clarity,
    evaluate_peak_moment,
    evaluate_recovery_quality,
    evaluate_reality_alignment,
    evaluate_signal_harmony,
    evaluate_source_validation,
    evaluate_structural_admission,
    evaluate_transition_quality,
    evaluate_trust,
    evaluate_use_case_fit,
    load_structural_admission_thresholds,
    route_evaluation_model,
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
        buyer_type=BuyerTypeInput(
            asset_class="stock",
            objective="QUALITY_EXECUTION",
            risk_tolerance=0.4,
            time_horizon_days=180.0,
            identity_fit=0.7,
            narrative_strength=0.5,
            income_relevance=0.5,
            optionality=0.4,
            hedge_need=0.2,
            event_catalyst_strength=0.5,
            quality_bias=0.8,
            passive_fit=0.7,
        ),
        execution_survivability=ExecutionSurvivabilityInput(
            volatility=0.2,
            spread=0.2,
            slippage=0.2,
            latency=0.2,
            data_gaps=0.1,
            false_positive_rate=0.1,
            news_reversal_risk=0.2,
            liquidity_gap_risk=0.2,
            operator_confusion=0.1,
            external_confirmation_failure=0.1,
        ),
        source_validation=SourceValidationInput(
            source_credibility=0.9,
            external_confirmation=0.85,
            consistency=0.9,
            wrapper_uncertainty=0.1,
        ),
        peak_moment=PeakMomentInput(
            novelty=0.4,
            emotional_intensity=0.4,
            recall_frequency=0.4,
            total_quality=0.8,
        ),
        behavioral_skin=BehavioralSkinInput(
            appearance=0.4,
            behavior=0.7,
            feature_access=0.7,
            system_tuning=0.7,
        ),
        recovery_quality=RecoveryQualityInput(
            surface_recovery=0.5,
            structural_integrity=0.8,
        ),
        force_flow=ForceFlowInput(
            signal_force=0.8,
            transmission_path=0.8,
            buyer_sensitivity=0.7,
            damping=0.1,
        ),
        actor_response=ActorResponseInput(
            buyer_probabilities={
                BuyerClass.INSTITUTIONAL_QUALITY.value: 0.7,
                BuyerClass.RETAIL_MOMENTUM.value: 0.4,
            },
            capital_weights={
                BuyerClass.INSTITUTIONAL_QUALITY.value: 0.9,
                BuyerClass.RETAIL_MOMENTUM.value: 0.4,
            },
            reaction_speed=0.7,
            conviction=0.75,
        ),
        validation_strength=0.9,
        fast_track_momentum=0.7,
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
    assert "buyer_type" in state
    assert "layer_scores" in state
    assert "mvp_admission_layer" in report
    assert "operator_summary" in report
    assert report["structural_admission_chaos_veto"] is True
    assert "structural_admission_class=CHAOS_VETO" in summary


def test_low_material_durability_produces_rejection_reason() -> None:
    payload = _base_input()
    payload.burn_profile = BurnProfile(
        ignition_speed=0.95,
        duration_score=0.2,
        stability_score=0.2,
        environment_resistance_score=0.2,
        decay_rate=0.9,
    )
    result = evaluate_structural_admission(payload)
    assert _has_reason(result, RejectionReason.LOW_DURABILITY_SIGNAL)


def test_peak_moment_does_not_override_total_quality() -> None:
    details, reasons = evaluate_peak_moment(
        PeakMomentInput(
            novelty=0.95,
            emotional_intensity=0.95,
            recall_frequency=0.95,
            total_quality=0.2,
        )
    )
    assert details["peak_moment_score"] > 0.6
    assert reasons[0].code == RejectionReason.PEAK_MOMENT_WITHOUT_TOTAL_QUALITY.value


def test_credible_source_without_confirmation_remains_uncertain() -> None:
    details, reasons = evaluate_source_validation(
        SourceValidationInput(
            source_credibility=0.95,
            external_confirmation=0.2,
            consistency=0.7,
            wrapper_uncertainty=0.1,
        ),
        thresholds=load_structural_admission_thresholds(),
    )
    assert details["validated_product_or_event"] is False
    assert reasons[0].code == RejectionReason.SOURCE_CREDIBILITY_WITHOUT_VALIDATION.value


def test_cosmetic_skin_is_not_treated_as_behavioral() -> None:
    details, reasons = evaluate_behavioral_skin(
        BehavioralSkinInput(
            appearance=0.9,
            behavior=0.1,
            feature_access=0.1,
            system_tuning=0.1,
        )
    )
    assert details["skin_class"] == "COSMETIC_SKIN"
    assert reasons[0].code == RejectionReason.COSMETIC_SKIN_ONLY.value


def test_surface_only_recovery_is_not_structural() -> None:
    details, reasons = evaluate_recovery_quality(
        RecoveryQualityInput(
            surface_recovery=0.9,
            structural_integrity=0.2,
        )
    )
    assert details["recovery_class"] == "SURFACE_ONLY"
    assert reasons[0].code == RejectionReason.SURFACE_ONLY_IMPROVEMENT.value


def test_buyer_type_routes_evaluation_model() -> None:
    buyer = classify_buyer_type(
        BuyerTypeInput(
            asset_class="crypto",
            objective="MOMENTUM",
            risk_tolerance=0.9,
            time_horizon_days=10.0,
            identity_fit=0.8,
            narrative_strength=0.9,
            quality_bias=0.2,
        )
    )
    assert buyer["buyer_type"] in {
        BuyerClass.RETAIL_MOMENTUM.value,
        BuyerClass.NARRATIVE_SPECULATOR.value,
        BuyerClass.EVENT_DRIVEN.value,
    }
    assert route_evaluation_model("crypto", buyer["buyer_type"]) == "CRYPTO_MOMENTUM_LIQUIDITY_NARRATIVE_MODEL"


def test_actor_response_unclear_blocks_promotion() -> None:
    details, reasons = evaluate_actor_response(
        ActorResponseInput(
            buyer_probabilities={BuyerClass.RETAIL_MOMENTUM.value: 0.1},
            capital_weights={BuyerClass.RETAIL_MOMENTUM.value: 0.1},
            reaction_speed=0.1,
            conviction=0.1,
        )
    )
    assert details["clarity_score"] < 0.5
    assert reasons[0].code == RejectionReason.ACTOR_RESPONSE_UNCLEAR.value


def test_force_flow_break_is_flagged() -> None:
    details, reasons = evaluate_force_flow(
        ForceFlowInput(
            signal_force=0.4,
            transmission_path=0.1,
            buyer_sensitivity=0.2,
            damping=0.7,
        )
    )
    assert details["price_pressure"] < 0.25
    assert reasons[0].code == RejectionReason.FORCE_FLOW_BREAK.value


def test_low_maintenance_survival_is_rejected() -> None:
    details, reasons = evaluate_maintenance_survival(
        payload=MaintenanceCostInput(
            performance_after_stress=0.2,
            performance_before_stress=1.0,
            desire=0.7,
            maintenance_cost=0.8,
            failure_friction=0.8,
        ),
        thresholds=load_structural_admission_thresholds(),
    )
    assert details["survival_score"] == pytest.approx(0.2)
    assert reasons[0].code == RejectionReason.LOW_MAINTENANCE_SURVIVAL.value


def test_low_buyer_alignment_blocks_execution_candidate() -> None:
    payload = _base_input()
    payload.buyer_type = BuyerTypeInput(
        asset_class="stock",
        objective="UNCLEAR",
        risk_tolerance=0.1,
        time_horizon_days=5.0,
        identity_fit=0.1,
        narrative_strength=0.1,
        income_relevance=0.1,
        optionality=0.1,
        hedge_need=0.1,
        event_catalyst_strength=0.1,
        quality_bias=0.1,
        passive_fit=0.1,
    )
    result = evaluate_structural_admission(payload)
    assert _has_reason(result, RejectionReason.LOW_BUYER_ALIGNMENT)
    assert result.admission_class != AdmissionClass.ADMIT_EXECUTION_CANDIDATE.value


def test_low_execution_survivability_blocks_execution_candidate() -> None:
    payload = _base_input()
    payload.execution_survivability = ExecutionSurvivabilityInput(
        volatility=0.9,
        spread=0.9,
        slippage=0.9,
        latency=0.9,
        data_gaps=0.9,
        false_positive_rate=0.8,
        news_reversal_risk=0.9,
        liquidity_gap_risk=0.9,
        operator_confusion=0.8,
        external_confirmation_failure=0.8,
    )
    result = evaluate_structural_admission(payload)
    assert _has_reason(result, RejectionReason.LOW_EXECUTION_SURVIVABILITY)
    assert result.admission_class != AdmissionClass.ADMIT_EXECUTION_CANDIDATE.value


def test_diablo_chaos_veto_overrides_normal_logic() -> None:
    bull_state, reason = compute_bull_state(
        chaos_veto=True,
        policy_veto=False,
        trapdoor_risk=0.1,
        validation_strength=0.95,
        material_durability=0.95,
        buyer_alignment=0.95,
        execution_survivability=0.95,
        primitive_understanding=0.95,
        fast_track_momentum=0.95,
        thresholds=load_structural_admission_thresholds(),
    )
    assert bull_state == BullState.DIABLO.value
    assert "outranks" in reason.lower()


def test_huracan_fast_track_requires_validation_and_risk_caps() -> None:
    bull_state, _ = compute_bull_state(
        chaos_veto=False,
        policy_veto=False,
        trapdoor_risk=0.1,
        validation_strength=0.8,
        material_durability=0.8,
        buyer_alignment=0.8,
        execution_survivability=0.8,
        primitive_understanding=0.9,
        fast_track_momentum=0.9,
        thresholds=load_structural_admission_thresholds(),
    )
    assert bull_state == BullState.HURACAN.value


def test_bull_state_mapping_is_deterministic() -> None:
    payload = _base_input()
    left = evaluate_structural_admission(payload)
    right = evaluate_structural_admission(payload)
    assert left.bull_state == right.bull_state
    assert left.next_required_action == right.next_required_action


def test_buyer_alignment_component_is_exposed() -> None:
    score, result, reasons = evaluate_buyer_alignment(
        BuyerTypeInput(
            asset_class="etf",
            objective="ALLOCATION",
            risk_tolerance=0.2,
            time_horizon_days=720.0,
            identity_fit=0.7,
            narrative_strength=0.2,
            quality_bias=0.8,
            passive_fit=0.9,
        ),
        use_case_score=0.8,
    )
    assert score.score >= 0.5
    assert result["evaluation_model"] == "ETF_ALLOCATION_RISK_MACRO_MODEL"
    assert reasons == []
