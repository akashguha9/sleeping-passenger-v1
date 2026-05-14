"""Tests for scripts/signal_field_geometry.py — pure deterministic helper."""

from __future__ import annotations

from scripts.signal_field_geometry import (
    FIELD_GEOMETRY_LABELS,
    SAFETY_STAMPS,
    TRACE_LABELS,
    classify_field_geometry,
    classify_signal_trace,
    compute_damping_score,
    compute_phase_alignment,
    compute_resonance_score,
)


def _assert_safety(payload: dict) -> None:
    assert isinstance(payload, dict)
    safety = payload["safety"]
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False


def test_safety_stamps_constants():
    assert SAFETY_STAMPS["advisory_status"] == "ADVISORY_ONLY"
    assert SAFETY_STAMPS["execution_gate"] == "LOCKED"
    assert SAFETY_STAMPS["broker_api_called"] is False
    assert SAFETY_STAMPS["ai_execution_count"] == 0


def test_classify_signal_trace_empty_input_is_low_signal():
    payload = classify_signal_trace({})
    _assert_safety(payload)
    assert payload["digital_sign_type"] == "low_signal"
    assert payload["digital_sign_strength"] == 0.0
    assert payload["hypothesis_only"] is True


def test_classify_signal_trace_handles_none_safely():
    payload = classify_signal_trace(None)
    _assert_safety(payload)
    assert payload["digital_sign_type"] == "low_signal"


def test_repetition_echo_detected_when_many_mentions_few_independent_sources():
    payload = classify_signal_trace({
        "mention_count": 12,
        "independent_source_count": 1,
        "narrative_intensity": 0.6,
    })
    _assert_safety(payload)
    assert payload["digital_sign_type"] == "repetition_echo"
    assert payload["hypothesis_only"] is True
    assert payload["operator_action"] == "decay_archive"


def test_absence_gap_detected_when_expected_confirmation_missing():
    payload = classify_signal_trace({
        "expected_confirmation_count": 5,
        "actual_confirmation_count": 1,
        "mention_count": 0,
    })
    _assert_safety(payload)
    assert payload["digital_sign_type"] == "absence_gap"
    assert payload["absence_confirmation_gap"] > 0.5
    assert payload["operator_action"] == "review_later"


def test_velocity_spike_with_market_confirmation():
    payload = classify_signal_trace({
        "price_velocity": 0.8,
        "market_confirmation": 0.8,
        "source_reliability": 0.9,
        "freshness_score": 0.9,
        "independent_source_count": 3,
    })
    _assert_safety(payload)
    assert payload["digital_sign_type"] == "velocity_spike"


def test_emotional_language_with_low_evidence_flags_hypothesis_only():
    payload = classify_signal_trace({
        "narrative_intensity": 0.9,
        "emotional_language_score": 0.9,
        "source_reliability": 0.1,
        "independent_source_count": 1,
        "mention_count": 1,
    })
    _assert_safety(payload)
    assert payload["hypothesis_only"] is True
    assert payload["pattern_overfit_risk"] > 0.4


def test_timing_anomaly_when_simultaneous_timestamps():
    payload = classify_signal_trace({
        "timestamp": 1234567890.0,
        "previous_timestamp": 1234567890.0,
        "narrative_intensity": 0.3,
    })
    _assert_safety(payload)
    assert payload["timing_integrity_score"] in {0.0, 1.0}


def test_scores_are_clamped_for_garbage_input():
    payload = classify_signal_trace({
        "narrative_intensity": 99,
        "attention_velocity": -5,
        "source_reliability": "not a number",
        "mention_count": "lots",
    })
    _assert_safety(payload)
    for field in (
        "digital_sign_strength",
        "signal_energy",
        "absence_confirmation_gap",
        "timing_integrity_score",
        "evidence_quality_score",
        "pattern_overfit_risk",
    ):
        v = payload[field]
        assert 0.0 <= v <= 1.0, f"{field} not clamped: {v}"


def test_classify_signal_trace_is_deterministic():
    payload_a = classify_signal_trace({"narrative_intensity": 0.5, "mention_count": 7})
    payload_b = classify_signal_trace({"narrative_intensity": 0.5, "mention_count": 7})
    assert payload_a == payload_b


def test_trace_label_set_complete():
    expected = {
        "frequency_spike", "velocity_spike", "acceleration_spike",
        "repetition_echo", "absence_gap", "timing_anomaly",
        "directional_move", "low_signal", "unknown",
    }
    assert set(TRACE_LABELS) == expected


def test_phase_alignment_no_signals_safe():
    payload = compute_phase_alignment(None)
    _assert_safety(payload)
    assert payload["signal_count"] == 0
    assert payload["phase_alignment_score"] == 0.0


def test_phase_alignment_aligned_bullish_signals():
    signals = [
        {"direction": 1, "intensity": 0.8},
        {"direction": 1, "intensity": 0.7},
        {"direction": 1, "intensity": 0.9},
    ]
    payload = compute_phase_alignment(signals)
    _assert_safety(payload)
    assert payload["phase_alignment_score"] > 0.5
    assert payload["direction_balance"] == 1.0


def test_phase_alignment_split_directions_low():
    signals = [
        {"direction": 1, "intensity": 0.5},
        {"direction": -1, "intensity": 0.5},
    ]
    payload = compute_phase_alignment(signals)
    _assert_safety(payload)
    assert payload["phase_alignment_score"] < 0.3


def test_resonance_score_high_when_aligned_with_charge():
    signals = [
        {"direction": 1, "intensity": 0.8, "narrative_charge": 0.9, "confirmation": 0.7},
        {"direction": 1, "intensity": 0.8, "narrative_charge": 0.8, "confirmation": 0.6},
    ]
    payload = compute_resonance_score(signals)
    _assert_safety(payload)
    assert payload["resonance_score"] > 0.4


def test_resonance_score_safe_for_empty():
    payload = compute_resonance_score([])
    _assert_safety(payload)
    assert payload["resonance_score"] == 0.0


def test_damping_score_new_signal_low_decay():
    payload = compute_damping_score({
        "age_hours": 0.0,
        "freshness_score": 1.0,
        "confirmation": 1.0,
    })
    _assert_safety(payload)
    assert payload["decay_factor"] == 1.0
    assert payload["damping_score"] < 0.5


def test_damping_score_old_signal_high():
    payload = compute_damping_score({
        "age_hours": 240.0,
        "half_life_hours": 24.0,
        "freshness_score": 0.0,
        "confirmation": 0.0,
        "contradiction_score": 1.0,
    })
    _assert_safety(payload)
    assert payload["decay_factor"] < 0.05
    assert payload["damping_score"] > 0.3


def test_classify_field_geometry_no_signals_returns_insufficient_data():
    payload = classify_field_geometry([])
    _assert_safety(payload)
    assert payload["field_geometry_label"] == "INSUFFICIENT_DATA"


def test_classify_field_geometry_single_high_intensity_signal_is_spiking():
    payload = classify_field_geometry([
        {"direction": 1, "intensity": 0.95, "narrative_charge": 0.9, "source_name": "S1"},
    ])
    _assert_safety(payload)
    assert payload["field_geometry_label"] == "SPIKING"


def test_classify_field_geometry_convergent_signals_label():
    payload = classify_field_geometry([
        {"direction": 1, "intensity": 0.5, "source_name": "A"},
        {"direction": 1, "intensity": 0.6, "source_name": "B"},
        {"direction": 1, "intensity": 0.5, "source_name": "C"},
    ])
    _assert_safety(payload)
    assert payload["field_geometry_label"] in {"CONVERGENT", "RESONANT"}


def test_classify_field_geometry_divergent_signals_label():
    payload = classify_field_geometry([
        {"direction": 1, "intensity": 0.5, "source_name": "A"},
        {"direction": -1, "intensity": 0.5, "source_name": "B"},
    ])
    _assert_safety(payload)
    assert payload["field_geometry_label"] in {"DIVERGENT", "CHAOTIC"}


def test_classify_field_geometry_echo_when_same_source_repeats():
    payload = classify_field_geometry([
        {"direction": 1, "intensity": 0.4, "source_name": "S"},
        {"direction": 1, "intensity": 0.4, "source_name": "S"},
        {"direction": 1, "intensity": 0.4, "source_name": "S"},
    ])
    _assert_safety(payload)
    assert payload["field_geometry_label"] == "ECHOING"


def test_classify_field_geometry_resonant_with_charge():
    payload = classify_field_geometry([
        {"direction": 1, "intensity": 0.9, "narrative_charge": 0.9, "confirmation": 0.8, "source_name": "A"},
        {"direction": 1, "intensity": 0.85, "narrative_charge": 0.85, "confirmation": 0.8, "source_name": "B"},
        {"direction": 1, "intensity": 0.9, "narrative_charge": 0.9, "confirmation": 0.8, "source_name": "C"},
    ])
    _assert_safety(payload)
    assert payload["field_geometry_label"] in {"RESONANT", "CONVERGENT", "SPIKING"}


def test_classify_field_geometry_geometry_label_set_complete():
    assert "INSUFFICIENT_DATA" in FIELD_GEOMETRY_LABELS
    assert "ECHOING" in FIELD_GEOMETRY_LABELS
    assert "RESONANT" in FIELD_GEOMETRY_LABELS
    assert "CHAOTIC" in FIELD_GEOMETRY_LABELS


def test_classify_field_geometry_handles_dirty_input():
    payload = classify_field_geometry("not a list")
    _assert_safety(payload)
    assert payload["field_geometry_label"] == "INSUFFICIENT_DATA"


def test_classify_field_geometry_deterministic():
    signals = [
        {"direction": 1, "intensity": 0.5, "source_name": "A"},
        {"direction": 1, "intensity": 0.6, "source_name": "B"},
    ]
    a = classify_field_geometry(signals)
    b = classify_field_geometry(signals)
    assert a == b
