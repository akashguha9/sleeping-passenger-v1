"""
Tests for ``scripts.signal_sensitivity_diagnostics``.

Pin
---
- A stable, mid-range signal returns stability >= 0.9, fragile=False.
- A signal sitting right on a classification boundary is marked fragile.
- A signal with no numeric fields returns ``not_applicable``.
- Invalid input does not crash; returns ``validation_status="invalid"``.
- Perturbation count = numeric fields × perturbations × 2 signs.
- Every output carries the canonical safety stamps.
- The diagnostic never grants any form of execution permission.
- No DB writes; the function is pure.
- Output is deterministic for a deterministic classifier and fixed input.
"""
from __future__ import annotations

from scripts import signal_sensitivity_diagnostics as ssd


# ---------------------------------------------------------------------------
# Stable signal
# ---------------------------------------------------------------------------


def test_stable_signal_stays_stable():
    signal = {
        "confidence_score": 0.62,
        "reliability_score": 0.78,
        "contradiction_score": 0.15,
        "priority_score": 0.55,
        "kill_rate_score": 0.20,
    }
    result = ssd.diagnose_signal_sensitivity(signal)
    assert result["validation_status"] == "valid"
    assert result["fragile"] is False
    assert result["classification_stability_score"] >= 0.9
    assert result["chaos_sensitivity_score"] <= 0.1
    assert result["recommendation"] == "stable"
    assert result["baseline_classification"] == "REVIEW"
    assert result["perturbation_count"] > 0


# ---------------------------------------------------------------------------
# Borderline / fragile signal
# ---------------------------------------------------------------------------


def test_borderline_signal_is_fragile():
    # contradiction_score sitting right on the 0.7 BLOCKED boundary —
    # any small perturbation pushes it across.
    signal = {
        "contradiction_score": 0.7,
        "confidence_score": 0.55,
        "reliability_score": 0.5,
    }
    result = ssd.diagnose_signal_sensitivity(signal)
    assert result["fragile"] is True
    assert result["flip_count"] > 0
    assert result["recommendation"] in {
        "fragile_watchlist",
        "human_review_required",
    }


def test_priority_score_boundary_signal_is_fragile():
    signal = {
        "priority_score": 0.70,  # boundary for PROMOTE_FOR_HUMAN_REVIEW
        "confidence_score": 0.55,
        "reliability_score": 0.55,
    }
    result = ssd.diagnose_signal_sensitivity(signal)
    assert result["fragile"] is True
    assert result["flip_count"] > 0


# ---------------------------------------------------------------------------
# Not applicable: no numeric fields
# ---------------------------------------------------------------------------


def test_signal_with_no_numeric_fields_returns_not_applicable():
    signal = {"ticker": "XYZ", "narrative_text": "headline"}
    result = ssd.diagnose_signal_sensitivity(signal)
    assert result["validation_status"] == "not_applicable"
    assert result["recommendation"] == "not_applicable"
    assert result["fragile"] is False
    assert result["perturbation_count"] == 0


# ---------------------------------------------------------------------------
# Bad input
# ---------------------------------------------------------------------------


def test_non_dict_input_returns_invalid_safely():
    result = ssd.diagnose_signal_sensitivity("not a dict")  # type: ignore[arg-type]
    assert result["validation_status"] == "invalid"
    assert result["recommendation"] == "invalid_input"
    assert result["fragile"] is False


def test_none_input_returns_invalid_safely():
    result = ssd.diagnose_signal_sensitivity(None)  # type: ignore[arg-type]
    assert result["validation_status"] == "invalid"


def test_empty_dict_is_not_applicable():
    result = ssd.diagnose_signal_sensitivity({})
    assert result["validation_status"] == "not_applicable"


# ---------------------------------------------------------------------------
# Perturbation count maths
# ---------------------------------------------------------------------------


def test_perturbation_count_matches_field_grid():
    signal = {
        "confidence_score": 0.62,
        "reliability_score": 0.78,
    }
    result = ssd.diagnose_signal_sensitivity(
        signal, perturbations=(0.01, 0.03, 0.05)
    )
    # 2 fields * 3 perturbations * 2 signs = 12 probes
    assert result["perturbation_count"] == 12


def test_custom_perturbations_are_respected():
    signal = {"confidence_score": 0.6}
    result = ssd.diagnose_signal_sensitivity(signal, perturbations=(0.10,))
    # 1 field * 1 magnitude * 2 signs = 2 probes
    assert result["perturbation_count"] == 2


def test_invalid_perturbations_fall_back_to_default():
    signal = {"confidence_score": 0.6}
    result = ssd.diagnose_signal_sensitivity(signal, perturbations=())
    # Default has 3 magnitudes
    assert result["perturbation_count"] == 6


# ---------------------------------------------------------------------------
# Safety stamps
# ---------------------------------------------------------------------------


def test_safety_stamps_locked():
    signal = {"confidence_score": 0.5}
    result = ssd.diagnose_signal_sensitivity(signal)
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    assert result["execution_permission"] is False
    assert result["can_execute"] is False
    assert result["may_inform_human_review"] is True
    assert result["may_execute"] is False
    assert result["may_call_broker"] is False


def test_safety_stamps_locked_on_invalid_input():
    result = ssd.diagnose_signal_sensitivity(None)  # type: ignore[arg-type]
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_permission"] is False
    assert result["can_execute"] is False


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_output_is_deterministic():
    signal = {
        "confidence_score": 0.62,
        "reliability_score": 0.78,
        "contradiction_score": 0.15,
        "priority_score": 0.55,
        "kill_rate_score": 0.20,
        "persistence_score": 0.58,
    }
    a = ssd.diagnose_signal_sensitivity(signal)
    b = ssd.diagnose_signal_sensitivity(dict(signal))
    assert a == b


# ---------------------------------------------------------------------------
# Custom classifier
# ---------------------------------------------------------------------------


def test_classifier_callback_is_invoked():
    calls = []

    def always_block(sig):
        calls.append(sig)
        return "BLOCKED"

    result = ssd.diagnose_signal_sensitivity(
        {"confidence_score": 0.5}, classifier=always_block
    )
    # baseline + 1 field * 3 perturbations * 2 signs = 1 + 6 = 7 calls
    assert len(calls) == 7
    # With all probes labelled BLOCKED, no flips, stability=1.0
    assert result["flip_count"] == 0
    assert result["classification_stability_score"] == 1.0
    assert result["fragile"] is False


# ---------------------------------------------------------------------------
# Classifier categories are deterministic
# ---------------------------------------------------------------------------


def test_default_classifier_buckets():
    assert ssd.default_bucket_classifier({"contradiction_score": 0.9}) == "BLOCKED"
    assert ssd.default_bucket_classifier({"kill_rate_score": 0.95}) == "BLOCKED"
    assert ssd.default_bucket_classifier({"reliability_score": 0.1}) == "BLOCKED"
    assert ssd.default_bucket_classifier({"confidence_score": 0.2}) == "WATCHLIST"
    assert ssd.default_bucket_classifier({"persistence_score": 0.1}) == "WATCHLIST"
    assert (
        ssd.default_bucket_classifier({"priority_score": 0.85})
        == "PROMOTE_FOR_HUMAN_REVIEW"
    )
    assert ssd.default_bucket_classifier({}) == "REVIEW"


# ---------------------------------------------------------------------------
# Side-effect freedom
# ---------------------------------------------------------------------------


def test_input_signal_is_not_mutated():
    signal = {"confidence_score": 0.5, "reliability_score": 0.6}
    snapshot = dict(signal)
    ssd.diagnose_signal_sensitivity(signal)
    assert signal == snapshot
