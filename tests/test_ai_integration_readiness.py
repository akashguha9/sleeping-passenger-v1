"""Tests for ``scripts.ai_integration_readiness``."""
from __future__ import annotations

import json

from scripts import ai_integration_readiness as air


def test_summary_writes(tmp_path):
    target = tmp_path / "air.json"
    out = air.write_summary(target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["ok"] is True
    assert on_disk["ai_integration_score"] >= 9.5
    assert out["summary_path"] == str(target)


def test_missing_model_lowers_coverage():
    reports = [
        {"model_name": "grok", "stance": "BULLISH",
         "confidence": 0.8, "asset_tags": ["A"]},
        {"model_name": "claude", "stance": "BULLISH",
         "confidence": 0.8, "asset_tags": ["A"]},
    ]
    summary = air.build_summary(reports)
    assert summary["model_coverage_score"] < 1.0
    assert summary["ai_integration_score"] < 9.5


def test_bad_schema_is_rejected():
    reports = [
        {"model_name": "grok"},  # missing stance/confidence/asset_tags
        {"model_name": "claude", "stance": "BULLISH",
         "confidence": 0.8, "asset_tags": ["A"]},
    ]
    summary = air.build_summary(reports)
    assert summary["reports_rejected"] >= 1


def test_pending_outcome_does_not_improve_completed():
    reports = [
        {"model_name": m, "stance": "BULLISH", "confidence": 0.8,
         "asset_tags": ["A"], "outcome_status": "PENDING"}
        for m in air.EXPECTED_MODELS
    ]
    summary = air.build_summary(reports)
    assert summary["pending_outcome_count"] == len(air.EXPECTED_MODELS)
    assert summary["completed_outcome_count"] == 0


def test_diablo_and_disagreement_routes_counted():
    summary = air.build_summary()
    # The fixture has at least one DIABLO and one high-disagreement asset.
    assert summary["diablo_veto_count"] >= 1
    assert summary["high_disagreement_count"] >= 1


def test_safety_invariants():
    summary = air.build_summary()
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
