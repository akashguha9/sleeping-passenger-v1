"""Tests for scripts/fusion_thesis_engine.py."""

from __future__ import annotations

from scripts.fusion_thesis_engine import (
    FUSION_VALIDITIES,
    SAFETY_STAMPS,
    classify_fusion_candidate,
    compute_evidence_density,
    compute_fusion_thesis_strength,
)


def _assert_safety(payload: dict) -> None:
    safety = payload["safety"]
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False


def test_safety_stamps_constants():
    assert SAFETY_STAMPS["advisory_status"] == "ADVISORY_ONLY"


def test_empty_signals_safe():
    p = classify_fusion_candidate([])
    _assert_safety(p)
    assert p["fusion_validity"] == "insufficient_data"
    assert p["fusion_candidate"] is False


def test_none_handled_safely():
    p = classify_fusion_candidate(None)
    _assert_safety(p)
    assert p["fusion_validity"] == "insufficient_data"


def test_independent_weak_aligned_signals_produce_valid_fusion():
    signals = [
        {"source_name": "Reuters", "source_family": "news", "reliability": 0.8,
         "evidence_strength": 0.6, "market_confirmation": 0.5, "direction": 1,
         "intensity": 0.6, "durability_score": 0.7, "freshness_score": 0.8,
         "independence_score": 0.9, "contradiction_score": 0.0, "echo_risk_score": 0.1},
        {"source_name": "Bloomberg", "source_family": "news", "reliability": 0.8,
         "evidence_strength": 0.6, "market_confirmation": 0.5, "direction": 1,
         "intensity": 0.6, "durability_score": 0.7, "freshness_score": 0.8,
         "independence_score": 0.9, "contradiction_score": 0.0, "echo_risk_score": 0.1},
        {"source_name": "SEC", "source_family": "primary", "reliability": 0.95,
         "evidence_strength": 0.7, "market_confirmation": 0.6, "direction": 1,
         "intensity": 0.5, "durability_score": 0.8, "freshness_score": 0.9,
         "independence_score": 0.95, "contradiction_score": 0.0, "echo_risk_score": 0.0},
    ]
    p = classify_fusion_candidate(signals)
    _assert_safety(p)
    assert p["fusion_candidate"] is True
    assert p["fusion_validity"] == "valid_fusion"


def test_repeated_same_source_produces_echo_not_fusion():
    signals = [
        {"source_name": "BlogX", "source_family": "social", "reliability": 0.3,
         "evidence_strength": 0.3, "market_confirmation": 0.0, "direction": 1,
         "intensity": 0.8, "independence_score": 0.0, "echo_risk_score": 0.9},
        {"source_name": "BlogX", "source_family": "social", "reliability": 0.3,
         "evidence_strength": 0.3, "market_confirmation": 0.0, "direction": 1,
         "intensity": 0.8, "independence_score": 0.0, "echo_risk_score": 0.9},
        {"source_name": "BlogX", "source_family": "social", "reliability": 0.3,
         "evidence_strength": 0.3, "market_confirmation": 0.0, "direction": 1,
         "intensity": 0.8, "independence_score": 0.0, "echo_risk_score": 0.9},
    ]
    p = classify_fusion_candidate(signals)
    _assert_safety(p)
    assert p["fusion_validity"] == "echo_not_fusion"
    assert p["fusion_candidate"] is False


def test_high_contradiction_does_not_produce_valid_fusion():
    signals = [
        {"source_name": "A", "source_family": "news", "reliability": 0.7,
         "evidence_strength": 0.6, "direction": 1, "intensity": 0.6,
         "contradiction_score": 0.8, "independence_score": 0.7},
        {"source_name": "B", "source_family": "news", "reliability": 0.7,
         "evidence_strength": 0.6, "direction": 1, "intensity": 0.6,
         "contradiction_score": 0.8, "independence_score": 0.7},
    ]
    p = classify_fusion_candidate(signals)
    _assert_safety(p)
    assert p["fusion_validity"] != "valid_fusion"


def test_low_durability_weakens_fusion():
    signals = [
        {"source_name": "A", "source_family": "news", "reliability": 0.7,
         "evidence_strength": 0.6, "direction": 1, "intensity": 0.5,
         "durability_score": 0.05, "freshness_score": 0.1, "independence_score": 0.7},
        {"source_name": "B", "source_family": "news", "reliability": 0.7,
         "evidence_strength": 0.6, "direction": 1, "intensity": 0.5,
         "durability_score": 0.05, "freshness_score": 0.1, "independence_score": 0.7},
    ]
    p = classify_fusion_candidate(signals)
    _assert_safety(p)
    assert p["fusion_validity"] in {"weak_fusion", "insufficient_data"}


def test_high_heat_low_containment_flags_overheated():
    signals = [
        {"source_name": "A", "source_family": "social", "reliability": 0.6,
         "evidence_strength": 0.4, "direction": 1, "intensity": 0.95,
         "contradiction_score": 0.8, "independence_score": 0.7,
         "echo_risk_score": 0.5, "durability_score": 0.5, "freshness_score": 0.5},
        {"source_name": "B", "source_family": "social", "reliability": 0.6,
         "evidence_strength": 0.4, "direction": 1, "intensity": 0.95,
         "contradiction_score": 0.9, "independence_score": 0.7,
         "echo_risk_score": 0.5, "durability_score": 0.5, "freshness_score": 0.5},
    ]
    p = classify_fusion_candidate(signals)
    _assert_safety(p)
    assert p["fusion_validity"] == "overheated_uncontained"


def test_missing_fields_safe():
    p = classify_fusion_candidate([{}, {}, {}])
    _assert_safety(p)
    assert p["fusion_candidate"] is False
    assert p["fusion_thesis_strength"] >= 0.0


def test_evidence_density_clamped_for_garbage():
    p = compute_evidence_density([{"reliability": 99, "evidence_strength": "wat",
                                    "contradiction_score": -5}])
    _assert_safety(p)
    assert 0.0 <= p["evidence_density"] <= 1.0


def test_fusion_thesis_strength_clamped():
    p = compute_fusion_thesis_strength([{"reliability": 1.0, "evidence_strength": 1.0,
                                          "intensity": 1.0, "durability_score": 1.0,
                                          "freshness_score": 1.0, "independence_score": 1.0,
                                          "source_name": "A"}])
    _assert_safety(p)
    assert 0.0 <= p["fusion_thesis_strength"] <= 1.0


def test_no_execution_fields_in_output():
    p = classify_fusion_candidate([{"source_name": "A", "direction": 1, "intensity": 0.5}])
    _assert_safety(p)
    for k in p.keys():
        assert "execute" not in k.lower()
        assert "broker" not in k.lower()


def test_fusion_validities_set_complete():
    for v in ("valid_fusion", "weak_fusion", "echo_not_fusion",
              "overheated_uncontained", "insufficient_data"):
        assert v in FUSION_VALIDITIES


def test_deterministic():
    signals = [
        {"source_name": "A", "direction": 1, "intensity": 0.5, "reliability": 0.8},
    ]
    a = classify_fusion_candidate(signals)
    b = classify_fusion_candidate(signals)
    assert a == b
