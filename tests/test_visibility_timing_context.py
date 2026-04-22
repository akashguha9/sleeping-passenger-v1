from datetime import datetime, timezone

from scripts.crowding_detector import compute_crowding_context
from scripts.phase_classifier import classify_moon_phase
from scripts.temporal_position_engine import compute_temporal_position
from scripts.visibility_engine import compute_light_score, compute_shadow_score
from scripts.visibility_timing_sync import build_visibility_timing_context


def test_light_score_is_normalized_and_reports_inputs() -> None:
    payload = compute_light_score(
        validation_score=0.72,
        cross_source_confirmation_score=0.5,
        source_quality_score=0.6,
        price_lead_score=0.7,
        novelty_score=0.4,
        pre_entry_state="CLEAN_READY_PENDING_TRIGGER",
        status="WATCHLIST",
        crowding_state="HEATING_UP",
        persistence_count=2,
    )

    assert 0.0 <= payload["light_score"] <= 1.0
    assert payload["light_method"] == "VISIBILITY_PROXY_BLEND_V1"
    assert "validation_score" in payload["light_inputs_used"]


def test_shadow_score_is_inverse_light_with_hidden_risk_flag() -> None:
    payload = compute_shadow_score(
        light_score=0.64,
        validation_state="NEEDS_CONFIRMATION",
        blocker_clearance_score=0.0,
    )

    assert payload["shadow_score"] == 0.36
    assert payload["shadow_method"] == "INVERSE_LIGHT_V1"
    assert payload["hidden_risk_flag"] is True


def test_phase_classifier_respects_thresholds() -> None:
    assert classify_moon_phase(light_score=0.05)["moon_phase"] == "new_moon"
    assert classify_moon_phase(light_score=0.2)["moon_phase"] == "crescent"
    assert classify_moon_phase(light_score=0.4)["moon_phase"] == "quarter"
    assert classify_moon_phase(light_score=0.7)["moon_phase"] == "gibbous"
    assert classify_moon_phase(light_score=0.9)["moon_phase"] == "full_moon"


def test_phase_classifier_detects_waning_when_light_declines_from_peak() -> None:
    payload = classify_moon_phase(
        light_score=0.68,
        previous_light_score=0.86,
        light_velocity=-0.18,
    )

    assert payload["moon_phase"] == "waning"
    assert payload["phase_reason"] == "visibility_declining_from_prior_peak"


def test_temporal_position_stays_in_bounds() -> None:
    payload = compute_temporal_position(
        event_emergence_ts="2026-04-10T00:00:00+00:00",
        as_of=datetime(2026, 4, 22, tzinfo=timezone.utc),
        pre_entry_state="CLEAN_ENTRY_ELIGIBLE",
        status="WATCHLIST",
        persistence_count=3,
    )

    assert 0.0 <= payload["temporal_position"] <= 1.0
    assert payload["temporal_method"] == "SUNDIAL_PROXY_BLEND_V1"


def test_crowding_detector_flags_full_moon_trap() -> None:
    payload = compute_crowding_context(
        light_score=0.9,
        temporal_position=0.8,
        crowding_state="CROWDED",
        cross_source_confirmation_score=0.8,
        novelty_score=0.1,
    )

    assert payload["crowding_score"] > 0.75
    assert payload["full_moon_trap_flag"] is True


def test_visibility_timing_context_produces_bounded_context_and_waning_velocity() -> None:
    payload = build_visibility_timing_context(
        signal_row={"signal_id": "SIG_2026_04_20_RTX", "ticker": "RTX"},
        validation_score=0.74,
        cross_source_confirmation_score=0.5,
        source_quality_score=0.65,
        price_lead_score=0.7,
        novelty_score=0.25,
        blocker_clearance_score=1.0,
        crowding_state="HEATING_UP",
        pre_entry_state="CLEAN_ENTRY_ELIGIBLE",
        status="WATCHLIST",
        validation_state="VALIDATED",
        event_emergence_ts="2026-04-20T00:00:00+00:00",
        persistence_count=2,
        as_of=datetime(2026, 4, 22, tzinfo=timezone.utc),
        previous_context={"light_score": 0.9, "shadow_score": 0.1, "temporal_position": 0.85},
    )

    assert 0.0 <= payload["light_score"] <= 1.0
    assert 0.0 <= payload["shadow_score"] <= 1.0
    assert 0.0 <= payload["temporal_position"] <= 1.0
    assert payload["light_velocity"] < 0
    assert payload["moon_phase"] == "waning"
    assert "edge_context_score" in payload
