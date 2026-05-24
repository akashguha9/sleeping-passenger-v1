"""Tests for ``scripts.signal_input_quality``."""
from __future__ import annotations

import json

from scripts import signal_input_quality as siq


def test_low_input_quality_reduces_cqs_final():
    high_iq = siq.cqs_final(cqs_raw=0.8, input_quality_value=0.9,
                            model_disagreement_risk=0.0)
    low_iq = siq.cqs_final(cqs_raw=0.8, input_quality_value=0.2,
                           model_disagreement_risk=0.0)
    assert low_iq < high_iq
    assert low_iq < 0.4


def test_high_ers_blocks_promotion():
    cand = {
        "id": "X", "cqs_raw": 0.9, "verified_source_ratio": 0.9,
        "fresh_source_ratio": 0.9, "cross_source_ratio": 1.0,
        "source_reliability_weighted_mean": 0.9, "schema_completeness": 1.0,
        "evidence_anchor_completeness": 0.9,
        "model_disagreement_risk": 0.1, "lpq": 0.85, "why_today_score": 0.8,
        "chaos_risk": 1.0, "stale_risk": 1.0,
        "source_unverified_risk": 1.0, "operator_risk": 1.0,
    }
    out = siq.evaluate_candidate(cand)
    assert out["ERS"] > siq.GATE_THRESHOLDS["ERS"]
    assert out["can_promote"] is False
    assert "ERS" in out["blocked_by"]


def test_high_cqs_alone_cannot_promote():
    cand = {
        "id": "X", "cqs_raw": 0.99,
        "verified_source_ratio": 0.1, "fresh_source_ratio": 0.1,
        "cross_source_ratio": 0.0, "source_reliability_weighted_mean": 0.1,
        "schema_completeness": 0.0, "evidence_anchor_completeness": 0.0,
        "model_disagreement_risk": 0.0, "lpq": 0.0,
        "why_today_score": 0.0, "chaos_risk": 0.0, "stale_risk": 0.0,
        "source_unverified_risk": 0.0, "operator_risk": 0.0,
    }
    out = siq.evaluate_candidate(cand)
    assert out["can_promote"] is False


def test_fresh_verified_cross_source_evidence_improves_scores():
    good = siq.evaluate_candidate({
        "id": "G", "cqs_raw": 0.85,
        "verified_source_ratio": 0.95, "fresh_source_ratio": 0.95,
        "cross_source_ratio": 1.0, "source_reliability_weighted_mean": 0.9,
        "schema_completeness": 1.0, "evidence_anchor_completeness": 0.9,
        "model_disagreement_risk": 0.05, "lpq": 0.95,
        "why_today_score": 0.85, "chaos_risk": 0.1, "stale_risk": 0.05,
        "source_unverified_risk": 0.05, "operator_risk": 0.05,
    })
    poor = siq.evaluate_candidate({
        "id": "P", "cqs_raw": 0.85,
        "verified_source_ratio": 0.2, "fresh_source_ratio": 0.2,
        "cross_source_ratio": 0.3, "source_reliability_weighted_mean": 0.3,
        "schema_completeness": 0.4, "evidence_anchor_completeness": 0.4,
        "model_disagreement_risk": 0.05, "lpq": 0.4, "why_today_score": 0.4,
        "chaos_risk": 0.1, "stale_risk": 0.1,
        "source_unverified_risk": 0.4, "operator_risk": 0.1,
    })
    assert good["CQS_final"] > poor["CQS_final"]
    assert good["EQS"] > poor["EQS"]
    assert good["FCS"] > poor["FCS"]


def test_output_includes_exact_formula_components():
    summary = siq.build_summary()
    for c in summary["candidates"]:
        comp = c["formula_components"]
        assert "verified_source_ratio" in comp
        assert "lpq" in comp
        assert "why_today_score" in comp
        assert "model_disagreement_risk" in comp


def test_summary_reaches_target_and_writes(tmp_path):
    target = tmp_path / "siq.json"
    summary = siq.write_summary(target)
    assert summary["signal_input_quality_score"] >= 8.8
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["promotable_count"] >= 1
    assert on_disk["blocked_count"] >= 2


def test_safety_invariants():
    summary = siq.build_summary()
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
