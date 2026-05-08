import json

from scripts.contextual_interpretation_engine import (
    BullInterpretationState,
    CommunicationCodeType,
    HiddenMechanism,
    InterpretationAction,
    LatentCapabilityState,
    MeaningType,
    RawInterpretationInput,
    SignalChannel,
    interpret_signal,
)
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline


def build_raw_input(**overrides) -> RawInterpretationInput:
    payload = {
        "signal_id": "sig-001",
        "source": "unit_test",
        "observed_event": "observed behavioural edge under pressure",
        "channel": SignalChannel.PERFORMANCE_CHANNEL,
        "code_type": CommunicationCodeType.PERFORMANCE_SIGNAL,
        "signal_clarity": 0.76,
        "context_completeness": 0.72,
        "observed_performance": 0.78,
        "expected_baseline": 0.42,
        "exposure_time": 0.18,
        "task_difficulty": 0.74,
        "environment_complexity": 0.70,
        "constraint_burden": 0.22,
        "receiver_channel_match": 0.74,
        "receiver_shared_context": 0.70,
        "receiver_decoder_skill": 0.72,
        "label_salience": 0.10,
        "observer_assumption_strength": 0.10,
        "repeatability": 0.34,
        "stress_survival": 0.40,
        "context_transferability": 0.30,
        "alternative_explanation_strength": 0.28,
        "randomness_risk": 0.24,
        "sample_size_risk": 0.40,
        "chaos_level": 0.10,
        "shock_level": 0.10,
    }
    payload.update(overrides)
    return RawInterpretationInput(**payload)


def test_learning_velocity_high_for_low_exposure_and_high_performance() -> None:
    result = interpret_signal(
        build_raw_input(
            observed_performance=0.88,
            expected_baseline=0.30,
            exposure_time=0.05,
            task_difficulty=0.82,
            environment_complexity=0.80,
            repeatability=0.22,
            stress_survival=0.26,
            context_transferability=0.20,
            sample_size_risk=0.68,
        )
    )
    assert result.learning_velocity_score > 0.70
    assert result.meaning_type in {
        MeaningType.LEARNING_VELOCITY,
        MeaningType.HIDDEN_CAPABILITY,
        MeaningType.STRUCTURAL_EDGE,
    }
    assert result.recommended_action in {
        InterpretationAction.PRIORITY_WATCHLIST,
        InterpretationAction.VALIDATE_DURABILITY,
    }
    assert result.bull_state in {
        BullInterpretationState.HURACAN,
        BullInterpretationState.MURCIELAGO,
    }
    assert result.recommended_action != InterpretationAction.PROMOTE_TO_ACTIONABLE


def test_durability_blocks_promotion() -> None:
    result = interpret_signal(
        build_raw_input(
            observed_performance=0.92,
            expected_baseline=0.40,
            repeatability=0.10,
            stress_survival=0.12,
            context_transferability=0.08,
            sample_size_risk=0.82,
            alternative_explanation_strength=0.66,
        )
    )
    assert result.promotion_score < 0.75
    assert result.recommended_action != InterpretationAction.PROMOTE_TO_ACTIONABLE
    joined_audit = " ".join(result.audit_trail).lower()
    assert "durability" in joined_audit or "repeatability" in joined_audit


def test_non_verbal_humour() -> None:
    result = interpret_signal(
        build_raw_input(
            channel=SignalChannel.NON_VERBAL,
            code_type=CommunicationCodeType.PERSONAL_SIGNAL,
            observed_event="non-verbal humour succeeds under language constraint",
            constraint_burden=0.60,
            observed_performance=0.86,
            exposure_time=0.18,
            task_difficulty=0.76,
            environment_complexity=0.68,
            receiver_channel_match=0.88,
            receiver_shared_context=0.82,
            receiver_decoder_skill=0.80,
            repeatability=0.32,
            stress_survival=0.44,
            context_transferability=0.30,
        )
    )
    assert result.constraint_normalized_score > 0.60
    assert result.latent_capability_score > 0.45
    assert result.meaning_type in {
        MeaningType.HIDDEN_CAPABILITY,
        MeaningType.CONSTRAINT_NAVIGATION,
    }


def test_receiver_failure() -> None:
    result = interpret_signal(
        build_raw_input(
            channel=SignalChannel.LOCAL_CODE,
            code_type=CommunicationCodeType.PERSONAL_SIGNAL,
            observed_event="local code signal misread by outsider",
            signal_clarity=0.90,
            receiver_channel_match=0.18,
            receiver_shared_context=0.10,
            receiver_decoder_skill=0.14,
            context_completeness=0.58,
        )
    )
    assert result.receiver_sensitivity_score < 0.30
    assert result.meaning_type in {
        MeaningType.RECEIVER_FAILURE,
        MeaningType.CONTEXT_MISMATCH,
    }
    assert result.recommended_action != InterpretationAction.PROMOTE_TO_ACTIONABLE


def test_label_bias_guard() -> None:
    result = interpret_signal(
        build_raw_input(
            label_salience=0.80,
            observer_assumption_strength=0.70,
            observed_event="label-heavy observer underweights behavioural evidence",
        )
    )
    assert result.label_bias_risk >= 0.40
    assert any(score.name == "LabelBiasGuard" for score in result.diagnostics)
    assert "label" in " ".join(result.audit_trail).lower()


def test_chaos_overrides_learning_velocity() -> None:
    result = interpret_signal(
        build_raw_input(
            observed_performance=0.90,
            expected_baseline=0.25,
            exposure_time=0.05,
            chaos_level=0.80,
        )
    )
    assert result.recommended_action == InterpretationAction.CHAOS_HOLD
    assert result.bull_state == BullInterpretationState.DIABLO
    assert result.recommended_action != InterpretationAction.PROMOTE_TO_ACTIONABLE


def test_shock_maps_to_islero() -> None:
    result = interpret_signal(build_raw_input(shock_level=0.80, chaos_level=0.10))
    assert result.bull_state == BullInterpretationState.ISLERO
    assert result.recommended_action in {
        InterpretationAction.VALIDATE_DURABILITY,
        InterpretationAction.HOLD_FOR_REPEATABILITY,
    }


def test_json_serialization() -> None:
    result = interpret_signal(build_raw_input())
    payload = result.to_dict()
    encoded = json.dumps(payload)
    assert isinstance(encoded, str)
    assert isinstance(payload["meaning_type"], str)
    assert isinstance(payload["bull_state"], str)


def test_deterministic_scoring() -> None:
    one = interpret_signal(build_raw_input()).to_dict()
    two = interpret_signal(build_raw_input()).to_dict()
    assert one == two


def test_clamp_behavior() -> None:
    result = interpret_signal(
        build_raw_input(
            signal_clarity=2.0,
            context_completeness=-1.0,
            observed_performance=4.0,
            expected_baseline=-0.5,
            exposure_time=3.0,
            chaos_level=2.0,
        )
    )
    for key, value in result.to_dict().items():
        if key.endswith("_score") or key.endswith("_risk") or key.endswith("_confidence"):
            assert 0.0 <= float(value) <= 1.0


def test_hidden_mechanism_scores_exist() -> None:
    result = interpret_signal(build_raw_input())
    keys = set(result.hidden_mechanism_scores)
    assert HiddenMechanism.RULE_COMPRESSION.value in keys
    assert HiddenMechanism.TABLE_READING.value in keys
    assert HiddenMechanism.TIMING_DISCIPLINE.value in keys
    assert HiddenMechanism.CONSTRAINT_NAVIGATION.value in keys
    assert HiddenMechanism.RECEIVER_DEPENDENCE.value in keys
    assert HiddenMechanism.RANDOM_VARIANCE.value in keys
    assert HiddenMechanism.STRUCTURAL_EDGE.value in keys


def test_one_off_anomaly_becomes_watchlist_not_truth() -> None:
    result = interpret_signal(
        build_raw_input(
            observed_performance=0.94,
            expected_baseline=0.30,
            exposure_time=0.02,
            repeatability=0.08,
            stress_survival=0.10,
            context_transferability=0.08,
            sample_size_risk=0.90,
            alternative_explanation_strength=0.70,
        )
    )
    assert result.recommended_action != InterpretationAction.PROMOTE_TO_ACTIONABLE


def test_pipeline_health_report_integration_if_integrated() -> None:
    report = run_diagnostics_pipeline(
        write_runtime=False,
        include_contextual_interpretation=True,
        contextual_interpretation_summary=True,
    )
    assert report["contextual_interpretation_enabled"] is True
    assert report["contextual_meaning_type"]
    assert isinstance(report["contextual_meaning_confidence"], (float, int))
    assert report["contextual_latent_capability_state"]
    assert report["contextual_recommended_action"]
    assert report["contextual_bull_state"]
    assert report["contextual_main_guardrail"]
