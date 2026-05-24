"""Tests for AI report ingestion (Integrated Sprint Part 4)."""
from __future__ import annotations

import json

from scripts import ai_report_ingestion as ari


def test_normalize_report_default_stance_when_unknown():
    rec = ari.normalize_report({"model_name": "x", "stance": "MAYBE",
                                "confidence": 0.7, "asset_tags": ["AAPL"],
                                "generated_at_utc": "2026-05-24T00:00:00Z"})
    assert rec["stance"] == "NEUTRAL"
    assert rec["stance_numeric"] == 0.0
    assert rec["confidence"] == 0.7
    assert rec["asset_tags"] == ["AAPL"]


def test_normalize_report_diablo_sets_hard_veto():
    rec = ari.normalize_report({"model_name": "x", "stance": "DIABLO",
                                "confidence": 0.9, "asset_tags": ["AAPL"],
                                "generated_at_utc": "2026-05-24T00:00:00Z"})
    assert rec["hard_veto"] is True
    assert rec["stance_numeric"] == -1.0


def test_normalize_report_missing_confidence_zero():
    rec = ari.normalize_report({"model_name": "x", "stance": "BULLISH",
                                "asset_tags": ["AAPL"]})
    assert rec["confidence"] == 0.0


def test_consensus_disagreement_for_split_models():
    reports = [
        ari.normalize_report({"model_name": "a", "stance": "BULLISH",
                              "confidence": 1.0, "asset_tags": ["AAPL"]}),
        ari.normalize_report({"model_name": "b", "stance": "BEARISH",
                              "confidence": 1.0, "asset_tags": ["AAPL"]}),
    ]
    out = ari.compute_consensus(reports, asset="AAPL")
    assert out["model_count"] == 2
    assert abs(out["mean_signal"]) < 1e-6
    assert out["disagreement"] >= 0.5


def test_cqs_ai_adjustment_reduces_with_disagreement():
    assert ari.cqs_ai_adjustment(1.0, 0.0) == 1.0
    assert ari.cqs_ai_adjustment(1.0, 0.8) < 1.0
    assert ari.cqs_ai_adjustment(1.0, 1.0) == 0.75


def test_reliability_update_clamps():
    val = ari.reliability_update(
        calibration_score=1.0,
        directional_hit=True,
        invalidation_quality=1.0,
        evidence_quality=1.0,
        why_today_score=1.0,
    )
    assert 0.0 <= val <= 1.0


def test_rolling_reliability_ewma():
    new_val = ari.rolling_reliability(0.5, 1.0, lambda_=0.85)
    # EWMA: 0.85 * 0.5 + 0.15 * 1.0 = 0.575
    assert abs(new_val - 0.575) < 1e-3


def test_build_ingestion_summary_writes_artifact(tmp_path):
    reports = [
        {"model_name": "a", "stance": "BULLISH", "confidence": 0.8,
         "asset_tags": ["AAPL"]},
        {"model_name": "b", "stance": "DIABLO", "confidence": 0.9,
         "asset_tags": ["AAPL"]},
    ]
    out_path = tmp_path / "ai_ingest.json"
    summary = ari.build_ingestion_summary(
        reports,
        cqs_base=0.9,
        write_summary=True,
        summary_path=out_path,
    )
    assert summary["ai_ingestion_ok"] is True
    assert summary["any_hard_veto"] is True
    assert summary["report_count"] == 2
    assert out_path.exists()
    persisted = json.loads(out_path.read_text(encoding="utf-8"))
    assert persisted["advisory_only"] is True
    assert persisted["execution_permission"] == "ADVISORY_ONLY"


def test_pending_outcomes_do_not_set_reliability_without_evidence():
    # Reliability update with zero direction + zero everything else = 0
    val = ari.reliability_update(
        calibration_score=0.0,
        directional_hit=False,
        invalidation_quality=0.0,
        evidence_quality=0.0,
        why_today_score=0.0,
    )
    assert val == 0.0


def test_advisory_invariants_always_set():
    rec = ari.normalize_report({"model_name": "x", "stance": "BULLISH"})
    assert rec["advisory_only"] is True
    assert rec["human_review_required"] is True
    assert rec["execution_permission"] == "ADVISORY_ONLY"
