"""Tests for the per-model reliability ledger + confidence calibration (Task 6)."""
from __future__ import annotations

from scripts import model_reliability_ledger as L


def test_no_history_uses_neutral_prior():
    led = L.build_ledger([])
    assert led["model_count"] == 0
    # An unobserved model gets the neutral prior, flagged as a prior.
    assert L.reliability_for(led, "never_seen") == 0.5
    one = L.build_ledger([{"model_name": "x"}])
    m = one["models"]["x"]
    assert m["sample_size"] == 1
    # No outcome fields -> every component falls to its False/empty value, so
    # reliability is low (not silently optimistic).
    assert m["is_prior"] is False
    assert m["reliability"] < 0.5


def test_directional_hit_rate_computed():
    recs = [
        {"model_name": "m", "directional_correct": True},
        {"model_name": "m", "directional_correct": True},
        {"model_name": "m", "directional_correct": False},
        {"model_name": "m", "directional_correct": False},
    ]
    m = L.build_ledger(recs)["models"]["m"]
    assert m["directional_hit_rate"] == 0.5


def test_missing_source_refs_lowers_diversity():
    rich = L.build_ledger([{"model_name": "a", "source_refs": ["x", "y", "z"]}])
    poor = L.build_ledger([{"model_name": "a", "source_refs": []}])
    assert rich["models"]["a"]["source_diversity"] == 1.0
    assert poor["models"]["a"]["source_diversity"] == 0.0


def test_calibration_error_is_abs_difference():
    assert L.calibration_error(0.9, 0.1) == 0.8
    assert L.calibration_error(0.3, 0.3) == 0.0
    assert L.calibration_error(None, 0.5) is None
    assert L.calibration_error(0.5, None) is None


def test_calibration_quality_penalizes_miscalibration():
    well = L.build_ledger([
        {"model_name": "w", "claimed_confidence": 0.8, "realized_outcome_score": 0.8},
    ])["models"]["w"]
    badly = L.build_ledger([
        {"model_name": "b", "claimed_confidence": 0.9, "realized_outcome_score": 0.1},
    ])["models"]["b"]
    assert well["calibration_quality"] == 1.0
    assert badly["calibration_quality"] < 0.3


def test_confidence_calibration_penalizes_overconfidence():
    # Claimed 0.9 but the model is unreliable -> calibrated confidence collapses.
    assert L.calibrate_confidence(0.9, 0.3, 1.0) == 0.27
    # Echoed sources (low independence) further reduce it.
    assert L.calibrate_confidence(0.9, 0.9, 0.5) == 0.405
    # Missing claimed confidence -> no earned confidence.
    assert L.calibrate_confidence(None, 0.9, 1.0) == 0.0


def test_models_aggregated_separately():
    recs = [
        {"model_name": "gpt", "directional_correct": True},
        {"model_name": "grok", "directional_correct": False},
    ]
    led = L.build_ledger(recs)
    assert set(led["models"]) == {"gpt", "grok"}
    assert led["models"]["gpt"]["directional_hit_rate"] == 1.0
    assert led["models"]["grok"]["directional_hit_rate"] == 0.0


def test_skips_unusable_records():
    led = L.build_ledger(["junk", {"no_model": 1}, {"model_name": "ok"}])
    assert led["skipped_records"] == 2
    assert led["model_count"] == 1


def test_advisory_only_no_execution():
    led = L.build_ledger([{"model_name": "m"}])
    assert led["advisory_status"] == "ADVISORY_ONLY"
    assert led["execution_gate"] == "LOCKED"
    assert led["broker_api_called"] is False
    assert led["ai_execution_count"] == 0
    assert led["human_review_required"] is True
