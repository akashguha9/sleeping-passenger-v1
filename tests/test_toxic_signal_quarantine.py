"""
Tests for ``scripts.toxic_signal_quarantine``.

Pin
---
- Clean high-reliability signal stays clean and is promotion-allowed.
- Invalid AI output drives contamination up.
- Contradiction >= ~0.7 is enough on its own to enter monitor/quarantine.
- Non-canonical / fallback signals are escalated.
- Emotional manipulation and recycled narrative increase contamination.
- ``block_from_promotion`` is reached when multiple toxic dimensions stack.
- Safety stamps are locked on every output.
- The diagnostic is deterministic and has no side effects.
- Bad input does not crash; returns ``block_from_promotion`` with reasons.
"""
from __future__ import annotations

from scripts import toxic_signal_quarantine as tsq


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------


def test_clean_signal_stays_clean():
    signal = {
        "source_reliability": 0.95,
        "contradiction_score": 0.05,
        "ai_validation_status": "valid",
        "hallucination_risk": 0.05,
        "recycled_narrative_risk": 0.05,
        "emotional_manipulation_score": 0.05,
        "operator_desire_distortion_score": 0.05,
        "fallback_used": False,
        "truth_source": "sqlite",
        "canonical": True,
    }
    result = tsq.classify_toxic_signal(signal)
    assert result["toxic_quarantine_state"] == "clean"
    assert result["promotion_allowed"] is True
    assert result["contamination_score"] < 0.2
    assert result["quarantine_reasons"] == []


# ---------------------------------------------------------------------------
# AI invalidity
# ---------------------------------------------------------------------------


def test_invalid_ai_output_raises_contamination():
    signal = {
        "source_reliability": 0.85,
        "ai_validation_status": "invalid",
    }
    result = tsq.classify_toxic_signal(signal)
    assert result["toxic_quarantine_state"] != "clean"
    assert "ai_validation_invalid" in result["quarantine_reasons"]
    assert result["component_scores"]["ai_invalidity"] == 1.0


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------


def test_high_contradiction_enters_monitor_or_quarantine():
    signal = {
        "source_reliability": 0.9,
        "contradiction_score": 0.8,
    }
    result = tsq.classify_toxic_signal(signal)
    assert result["toxic_quarantine_state"] in {"monitor", "quarantine"}
    assert "high_contradiction" in result["quarantine_reasons"]


# ---------------------------------------------------------------------------
# Fallback / non-canonical signals
# ---------------------------------------------------------------------------


def test_non_canonical_fallback_escalates_state():
    signal = {
        "source_reliability": 0.85,
        "fallback_used": True,
        "truth_source": "legacy_fabric",
        "canonical": False,
    }
    result = tsq.classify_toxic_signal(signal)
    assert result["toxic_quarantine_state"] in {"monitor", "quarantine"}
    assert "fallback_used_for_signal_source" in result["quarantine_reasons"]


# ---------------------------------------------------------------------------
# Stacked toxicity
# ---------------------------------------------------------------------------


def test_block_from_promotion_when_multiple_toxic_dimensions_stack():
    signal = {
        "source_reliability": 0.05,
        "contradiction_score": 0.9,
        "ai_validation_status": "invalid",
        "hallucination_risk": 0.85,
        "recycled_narrative_risk": 0.85,
        "emotional_manipulation_score": 0.85,
        "operator_desire_distortion_score": 0.85,
        "fallback_used": True,
    }
    result = tsq.classify_toxic_signal(signal)
    assert result["toxic_quarantine_state"] == "block_from_promotion"
    assert result["promotion_allowed"] is False
    assert result["contamination_score"] >= 0.7


# ---------------------------------------------------------------------------
# Emotional manipulation and recycled narrative
# ---------------------------------------------------------------------------


def test_emotional_manipulation_and_recycled_narrative_compound():
    signal = {
        "source_reliability": 0.85,
        "emotional_manipulation_score": 0.85,
        "recycled_narrative_risk": 0.85,
    }
    result = tsq.classify_toxic_signal(signal)
    assert result["toxic_quarantine_state"] in {"monitor", "quarantine"}
    assert any("emotional_manipulation" in r for r in result["quarantine_reasons"])
    assert any("recycled_narrative" in r for r in result["quarantine_reasons"])


# ---------------------------------------------------------------------------
# Safety stamps and invariants
# ---------------------------------------------------------------------------


def test_safety_stamps_locked_on_every_result():
    for signal in (
        {"source_reliability": 1.0},
        {"contradiction_score": 1.0},
        {"ai_validation_status": "invalid"},
        {},
    ):
        result = tsq.classify_toxic_signal(signal)
        assert result["advisory_status"] == "ADVISORY_ONLY"
        assert result["execution_gate"] == "LOCKED"
        assert result["broker_api_called"] is False
        assert result["ai_execution_count"] == 0
        assert result["execution_permission"] is False
        assert result["can_execute"] is False
        assert result["may_execute"] is False
        assert result["may_call_broker"] is False


def test_bad_input_is_blocked_safely():
    result = tsq.classify_toxic_signal("not a dict")  # type: ignore[arg-type]
    assert result["validation_status"] == "invalid"
    assert result["toxic_quarantine_state"] == "block_from_promotion"
    assert result["promotion_allowed"] is False


# ---------------------------------------------------------------------------
# Determinism and side-effect freedom
# ---------------------------------------------------------------------------


def test_deterministic_output():
    signal = {
        "source_reliability": 0.55,
        "contradiction_score": 0.5,
        "ai_validation_status": "partial",
    }
    a = tsq.classify_toxic_signal(signal)
    b = tsq.classify_toxic_signal(dict(signal))
    assert a == b


def test_input_signal_not_mutated():
    signal = {"source_reliability": 0.5, "contradiction_score": 0.5}
    snapshot = dict(signal)
    tsq.classify_toxic_signal(signal)
    assert signal == snapshot


# ---------------------------------------------------------------------------
# Threshold and weight overrides
# ---------------------------------------------------------------------------


def test_threshold_override_changes_state():
    signal = {"contradiction_score": 0.4}
    default = tsq.classify_toxic_signal(signal)
    assert default["toxic_quarantine_state"] in {"clean", "monitor"}
    stricter = tsq.classify_toxic_signal(
        signal, thresholds={"monitor": 0.05, "quarantine": 0.06, "block_from_promotion": 0.07}
    )
    assert stricter["toxic_quarantine_state"] in {"quarantine", "block_from_promotion"}


def test_weight_override_changes_contamination():
    signal = {"contradiction_score": 0.5}
    default = tsq.classify_toxic_signal(signal)
    heavy = tsq.classify_toxic_signal(signal, weights={"contradiction": 0.9})
    assert heavy["contamination_score"] > default["contamination_score"]


# ---------------------------------------------------------------------------
# Missing-field tolerance
# ---------------------------------------------------------------------------


def test_missing_fields_treated_as_zero_contamination():
    result = tsq.classify_toxic_signal({})
    assert result["toxic_quarantine_state"] == "clean"
    assert result["contamination_score"] == 0.0
    assert result["promotion_allowed"] is True
