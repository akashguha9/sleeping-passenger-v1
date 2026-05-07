from scripts.board_control_safety_layer import (
    BaselineViolationInput,
    BoardControlInput,
    BoardControlSafetyLayer,
    ClearanceLayerInput,
    ContextualInterpretationGuardInput,
    ConversionFailureInput,
    ErrorEventInput,
    FallbackSwitchingInput,
    FeedbackIntegrityInput,
    HiddenDisturbanceInput,
    MechanicalCueInput,
    OperatorStateTelemetryInput,
    PathGateInput,
    PremiseTestingInput,
    PressureToolInput,
    ProtectiveFrictionInput,
    RitualEffectivenessInput,
    SelfAuditInput,
    build_board_control_safety_report,
    classify_error_cluster,
    classify_protective_friction,
    compute_board_control_score,
    compute_critical_square_exposure,
    evaluate_action_admission,
    evaluate_baseline_violation,
    evaluate_clearance_guard,
    evaluate_contextual_interpretation_guard,
    evaluate_feedback_integrity,
    evaluate_fallback_switching,
    evaluate_hidden_disturbance,
    evaluate_mechanical_cue,
    evaluate_operator_state_telemetry,
    evaluate_premise_testing,
    evaluate_pressure_tool,
    evaluate_ritual_effectiveness,
    evaluate_self_audit,
)


def make_board_input(**overrides: object) -> BoardControlInput:
    payload = {
        "signal_id": "SIG-1",
        "timestamp": "2026-05-07T00:00:00+00:00",
        "critical_square_control": 0.8,
        "response_line_openness": 0.8,
        "containment_strength": 0.8,
        "core_protection": 0.8,
        "access_surface_exposure": 0.1,
        "impact_score": 0.7,
        "access_score": 0.5,
        "reversibility_score": 0.7,
        "protective_friction_score": 0.7,
        "detection_score": 0.8,
        "validation_score": 0.8,
        "durability_score": 0.8,
        "execution_survivability_score": 0.8,
        "policy_veto": False,
        "chaos_veto": False,
        "heat_risk_score": 0.1,
        "notes": [],
    }
    payload.update(overrides)
    return BoardControlInput(**payload)


def test_board_control_high_score_passes() -> None:
    score, reasons = compute_board_control_score(
        make_board_input(
            critical_square_control=0.95,
            response_line_openness=0.92,
            containment_strength=0.90,
            core_protection=0.90,
            access_surface_exposure=0.05,
        )
    )
    assert score >= 0.35
    assert "BOARD_CONTROL_ACCEPTABLE" in reasons


def test_board_control_low_score_emits_critical_square_exposed() -> None:
    score, reasons = compute_board_control_score(
        make_board_input(
            critical_square_control=0.2,
            response_line_openness=0.2,
            containment_strength=0.2,
            core_protection=0.2,
            access_surface_exposure=0.8,
        )
    )
    assert score < 0.35
    assert "CRITICAL_SQUARE_EXPOSED" in reasons


def test_critical_square_exposure_high_blocks_promotion() -> None:
    exposure, _ = compute_critical_square_exposure(
        make_board_input(
            impact_score=1.0,
            access_score=1.0,
            reversibility_score=0.0,
            protective_friction_score=0.0,
        )
    )
    admission = evaluate_action_admission(
        detection_score=0.9,
        validation_score=0.9,
        durability_score=0.9,
        execution_survivability_score=0.9,
        board_control_score=0.9,
        global_clearance_score=1.0,
        operator_precision_readiness=0.9,
        weakest_path_score=0.9,
        hidden_disturbance_score=0.1,
        critical_square_exposure=exposure,
        premise_quality_score=0.9,
        policy_veto=False,
        chaos_veto=False,
        fallback_required=False,
        review_theater_score=0.1,
    )
    assert admission.promotion_allowed is False


def test_weakest_path_auditor_uses_minimum_path_strength_correctly() -> None:
    from scripts.board_control_safety_layer import audit_weakest_path

    weakest, _ = audit_weakest_path(
        [
            PathGateInput("a", 0.9, 0.9, 0.9, 0.9, 0.9),
            PathGateInput("b", 0.7, 0.2, 0.7, 0.7, 0.7),
        ]
    )
    assert weakest == 0.2


def test_local_clearance_true_but_global_clearance_false_blocks_promotion() -> None:
    global_clearance, local_score, global_score, _, reasons = evaluate_clearance_guard(
        [
            ClearanceLayerInput("source_validation", True, 0.9, True),
            ClearanceLayerInput("containment_check", False, 0.2, True),
            ClearanceLayerInput("execution_readiness", True, 0.8, True),
        ]
    )
    assert global_clearance is False
    assert local_score > global_score
    assert "LOCAL_CLEAR_BUT_GLOBAL_RISK_REMAINS" in reasons


def test_review_theater_detection_works() -> None:
    _, review_theater, reasons, learning_valid = evaluate_feedback_integrity(
        FeedbackIntegrityInput(0.4, 0.3, 0.3, 0.3, 0.4, 0.9, 0.9, 0.9, 0.9)
    )
    assert review_theater >= 0.70
    assert "REVIEW_THEATER_DETECTED" in reasons
    assert learning_valid is False


def test_premise_quality_below_threshold_blocks_action() -> None:
    _, _, reasons = evaluate_premise_testing(
        PremiseTestingInput(0.2, 0.2, 0.2, 0.2, 0.2, 0.7, 0.7)
    )
    assert "PREMISE_CORRUPTION_RISK" in reasons


def test_contextual_interpretation_distinguishes_durable_signal_from_hostile_signal() -> None:
    durability, _, hostility, _, reasons = evaluate_contextual_interpretation_guard(
        ContextualInterpretationGuardInput(
            0.7, 0.7, 0.2, 0.2, 0.9, 0.9, 0.9, 0.9, 0.2, 0.2, 0.3, 0.2, 0.2, 0.8, 0.7, 0.7, 0.2
        )
    )
    assert durability >= 0.70
    assert hostility < 0.40
    assert "DURABLE_NOT_HOSTILE" in reasons


def test_single_signal_does_not_become_targeted_intent() -> None:
    _, targeted, _, _, reasons = evaluate_contextual_interpretation_guard(
        ContextualInterpretationGuardInput(
            0.2, 0.5, 0.4, 0.4, 0.2, 0.2, 0.5, 0.2, 0.3, 0.3, 0.0, 0.3, 0.3, 0.6, 0.5, 0.5, 0.1
        )
    )
    assert targeted < 0.2
    assert "SINGLE_SIGNAL_ONLY" in reasons


def test_repeated_general_pattern_lowers_targeted_intent_probability() -> None:
    _, targeted, _, _, reasons = evaluate_contextual_interpretation_guard(
        ContextualInterpretationGuardInput(
            0.8, 0.7, 0.7, 0.7, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.6, 0.6, 0.8, 0.8, 0.8, 0.2
        )
    )
    assert targeted < 0.2
    assert "GENERAL_PATTERN_NOT_TARGETED" in reasons


def test_hidden_disturbance_triggers_when_visible_reaction_is_low_but_error_delta_is_high() -> None:
    _, hidden, reasons = evaluate_hidden_disturbance(
        HiddenDisturbanceInput(0.1, 0.9, 0.9, 0.9, 0.1)
    )
    assert hidden >= 0.60
    assert "HIDDEN_EXECUTION_DRIFT" in reasons


def test_baseline_violation_triggers_restricted_mode() -> None:
    _, violated, reasons = evaluate_baseline_violation(
        BaselineViolationInput(0.1, 0.4, 0.1)
    )
    assert violated is True
    assert "RESTRICTED_MODE_REQUIRED" in reasons


def test_error_cluster_classifier_detects_touch_deception_instability_after_repeated_failures() -> None:
    cluster_type, _, reasons, _ = classify_error_cluster(
        [
            ErrorEventInput("miss", "touch", 1, "high", "ctx"),
            ErrorEventInput("miss", "touch", 2, "high", "ctx"),
            ErrorEventInput("miss", "power", 3, "high", "ctx"),
        ]
    )
    assert cluster_type == "TOUCH_DECEPTION_UNSTABLE"
    assert "TOUCH_TOOL_UNSTABLE" in reasons


def test_fallback_switching_disables_precision_deception_high_volatility_tools_after_threshold_breach() -> None:
    state, required, disabled, allowed, reasons = evaluate_fallback_switching(
        FallbackSwitchingInput(precision_tool_error_count=2, fallback_activation_threshold=2)
    )
    assert state == "DURABLE_FALLBACK_REQUIRED"
    assert required is True
    assert "PRECISION" in disabled
    assert "DURABLE_MODE_ACTIVATED" in reasons


def test_pressure_state_tool_filter_blocks_fragile_tools_under_poor_operator_readiness() -> None:
    _, allowed, reasons = evaluate_pressure_tool(
        PressureToolInput("tool", "precision", 0.8, 0.4, 0.4, 0.4, 0.9, 0.8, 0.5)
    )
    assert allowed is False
    assert "FRAGILITY_COST_TOO_HIGH" in reasons


def test_ritual_effectiveness_auditor_flags_ritual_insufficient_when_output_does_not_recover() -> None:
    _, insufficient, reasons = evaluate_ritual_effectiveness(
        RitualEffectivenessInput(True, 0.2, 0.5, 0.1, 0.05)
    )
    assert insufficient is True
    assert "RITUAL_INSUFFICIENT" in reasons


def test_mechanical_cue_layer_is_required_after_ritual_insufficiency() -> None:
    _, _, reasons = evaluate_mechanical_cue(
        MechanicalCueInput(None, None, 0.2, 0.2, True, 0.5, 0.5)
    )
    assert "MECHANICAL_CUE_REQUIRED" in reasons


def test_operator_state_telemetry_applies_alcohol_penalty_and_low_food_state_penalty() -> None:
    readiness, reasons = evaluate_operator_state_telemetry(
        OperatorStateTelemetryInput(0.2, 0.8, 0.2, 0.8, 0.4, 0.8)
    )
    assert readiness < 0.60
    assert "LOW_FOOD_STATE" in reasons
    assert "ALCOHOL_PENALTY" in reasons


def test_conversion_failure_analyzer_distinguishes_capability_gap_from_conversion_failure() -> None:
    from scripts.board_control_safety_layer import evaluate_conversion_failure

    score, _, reasons = evaluate_conversion_failure(
        ConversionFailureInput(0.8, 1, 5, 0.3, 0.1, 0, 3, 0, 2, 0, 4, 0.05)
    )
    assert score > 0
    assert "CONVERSION_FAILURE_HIGH" in reasons


def test_protective_friction_classifier_distinguishes_protective_friction_from_operational_drag() -> None:
    state, _, reasons = classify_protective_friction(
        ProtectiveFrictionInput("entry", True, 0.8, 0.2, 0.8, 0.2)
    )
    assert state == "PROTECTIVE_FRICTION_REQUIRED"
    assert "FRICTION_PROTECTS_CRITICAL_PATH" in reasons


def test_final_action_admission_hard_vetoes_weak_path_global_clearance_failure_and_premise_corruption() -> None:
    admission = evaluate_action_admission(
        detection_score=0.9,
        validation_score=0.9,
        durability_score=0.9,
        execution_survivability_score=0.9,
        board_control_score=0.9,
        global_clearance_score=0.5,
        operator_precision_readiness=0.9,
        weakest_path_score=0.2,
        hidden_disturbance_score=0.1,
        critical_square_exposure=0.1,
        premise_quality_score=0.4,
        policy_veto=False,
        chaos_veto=False,
        fallback_required=False,
        review_theater_score=0.1,
    )
    assert admission.promotion_allowed is False
    assert admission.action_allowed is False


def test_json_diagnostic_output_contains_required_fields() -> None:
    report = build_board_control_safety_report(
        [{"ticker": "RTX", "truth_probability": 0.8, "signal_strength_score": 0.7}],
        runtime_state={"policy_state": "RESTRICTED", "truth_origin": "seeded"},
        write_runtime=False,
    )
    assert "board_control_score" in report
    assert "board_control_safety" in report
    assert "per_signal_reports" in report


def test_existing_diagnostics_pipeline_still_runs() -> None:
    report = build_board_control_safety_report(
        [{"ticker": "RTX", "truth_probability": 0.8, "signal_strength_score": 0.7}],
        runtime_state={"policy_state": "RESTRICTED", "truth_origin": "seeded"},
        write_runtime=False,
    )
    assert report["board_control_final_state"]


def test_layer_evaluate_end_to_end() -> None:
    layer = BoardControlSafetyLayer()
    report = layer.evaluate(
        make_board_input(),
        path_inputs=[PathGateInput("p", 0.8, 0.8, 0.8, 0.8, 0.8)],
        clearance_layers=[
            ClearanceLayerInput("source_validation", True, 0.8, True),
            ClearanceLayerInput("cross_system_risk", True, 0.8, True),
            ClearanceLayerInput("access_surface_check", True, 0.8, True),
            ClearanceLayerInput("containment_check", True, 0.8, True),
            ClearanceLayerInput("execution_readiness", True, 0.8, True),
            ClearanceLayerInput("reversibility_check", True, 0.8, True),
            ClearanceLayerInput("operator_state_check", True, 0.8, True),
        ],
        feedback_input=FeedbackIntegrityInput(0.8, 0.8, 0.8, 0.8, 0.1, 0.1, 0.1, 0.1, 0.1),
        self_audit_input=SelfAuditInput(0.8, 0.8, 0.8, 0.8, 0.8, True, True, True),
        premise_input=PremiseTestingInput(0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8),
        contextual_input=ContextualInterpretationGuardInput(0.8, 0.8, 0.4, 0.4, 0.8, 0.8, 0.8, 0.8, 0.4, 0.4, 0.2, 0.2, 0.2, 0.8, 0.8, 0.8, 0.2),
        hidden_input=HiddenDisturbanceInput(0.1, 0.1, 0.2, 0.2, 0.2),
        baseline_input=BaselineViolationInput(0.1, 0.1, 0.1),
        error_events=[],
        fallback_input=FallbackSwitchingInput(0, 2),
        pressure_tools=[PressureToolInput("tool", "precision", 0.8, 0.8, 0.8, 0.8, 0.2, 0.2, 0.5)],
        ritual_input=RitualEffectivenessInput(False, 0.1, 0.1, 0.1, 0.05),
        mechanical_input=MechanicalCueInput("cue", "SAFE_MODE", 0.8, 0.8, False, 0.8, 0.8),
        operator_input=OperatorStateTelemetryInput(0.8, 0.8, 0.0, 0.8, 0.2, 0.8),
        conversion_input=ConversionFailureInput(0.8, 4, 5, 0.1, 0.1, 2, 3, 2, 3, 3, 4, 0.05),
        protective_friction_input=ProtectiveFrictionInput("entry", True, 0.8, 0.2, 0.2, 0.8),
    )
    assert report.signal_id == "SIG-1"
    assert report.final_state
