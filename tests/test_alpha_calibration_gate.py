"""Calibration gate: tiered verdict unlocking, severe-trap overrides."""

from __future__ import annotations

from src.alpha.opportunity import apply_calibration_gate


def _gate(support, verdict="core_candidate", score=70.0, confidence=80.0, **kwargs):
    return apply_calibration_gate(
        verdict, score, confidence, support, **kwargs
    )


def test_uncalibrated_caps_at_deep_research() -> None:
    result = _gate(0.0)
    assert result["verdict"] == "deep_research"
    assert result["calibration_tier"] == "uncalibrated"
    assert any("locked" in warning for warning in result["warnings"])


def test_early_calibration_unlocks_small_position_only_with_strength() -> None:
    strong = _gate(20.0, evidence_quality=75.0)
    assert strong["verdict"] == "small_position_candidate"  # never core at this tier
    weak_confidence = _gate(20.0, confidence=40.0, evidence_quality=75.0)
    assert weak_confidence["verdict"] == "deep_research"
    weak_evidence = _gate(20.0, evidence_quality=30.0)
    assert weak_evidence["verdict"] == "deep_research"
    weak_score = _gate(20.0, score=30.0, evidence_quality=75.0)
    assert weak_score["verdict"] == "deep_research"


def test_partial_calibration_allows_ladder_with_warning() -> None:
    result = _gate(45.0)
    assert result["verdict"] == "core_candidate"
    assert result["calibration_tier"] == "partial_calibration"
    assert any("calibration limited" in warning for warning in result["warnings"])


def test_high_calibration_unlocks_full_ladder() -> None:
    result = _gate(80.0)
    assert result["verdict"] == "core_candidate"
    assert result["calibration_tier"] == "calibrated"


def test_severe_trap_flags_override_every_tier() -> None:
    for support in (5.0, 20.0, 45.0, 95.0):
        result = _gate(support, trap_flags=["high_narrative_low_proof"])
        assert result["verdict"] == "watchlist", support
        assert any("override" in warning for warning in result["warnings"])


def test_non_severe_trap_flags_do_not_override() -> None:
    result = _gate(80.0, trap_flags=["risk_disclosure_overhang"])
    assert result["verdict"] == "core_candidate"


def test_low_outcome_coverage_warns() -> None:
    result = _gate(45.0, outcome_coverage=0.2)
    assert any("coverage" in warning for warning in result["warnings"])


def test_non_ladder_verdicts_pass_through() -> None:
    result = apply_calibration_gate("avoid_trap", 60.0, 70.0, 0.0)
    assert result["verdict"] == "avoid_trap"
    result = apply_calibration_gate("event_trade_only", 60.0, 70.0, 0.0)
    assert result["verdict"] == "event_trade_only"


def test_no_execution_language_at_any_tier() -> None:
    for support in (0.0, 20.0, 45.0, 95.0):
        result = _gate(support)
        text = str(result).lower()
        for forbidden in ("buy now", "guaranteed", "execute", "broker"):
            assert forbidden not in text
        assert "no tier permits execution" in result["explanation"].lower()
