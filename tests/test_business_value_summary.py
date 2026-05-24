"""Tests for the business value defensive-alpha summary (Integrated Sprint Part 6)."""
from __future__ import annotations

import json

from scripts import business_value_report as bvr


def test_defensive_alpha_proxy_empty_returns_labelled_zero():
    out = bvr.defensive_alpha_proxy([])
    assert out["candidate_count"] == 0
    assert out["defensive_alpha_proxy"] == 0.0
    assert "paper/advisory proxy" in out["labels"]


def test_defensive_alpha_proxy_counts_avoided_loss():
    rows = [
        {"blocked": True, "r_candidate": -0.10, "r_benchmark": 0.01,
         "block_reason": "PRICE_SOURCE_STALE"},
        {"blocked": True, "r_candidate": -0.02, "r_benchmark": 0.00,
         "block_reason": "MODEL_DISAGREEMENT_HIGH"},
        {"blocked": False, "r_candidate": 0.04, "r_benchmark": 0.02},
    ]
    out = bvr.defensive_alpha_proxy(rows, loss_threshold=0.05)
    assert out["candidate_count"] == 3
    assert out["blocked_count"] == 2
    assert out["blocked_with_outcome"] == 2
    # Only -10% beats the -5% threshold → 0.10 / 3
    assert abs(out["defensive_alpha_proxy"] - (0.10 / 3.0)) < 1e-6


def test_build_business_value_summary_writes_artifact(tmp_path):
    rows = [
        {"blocked": True, "r_candidate": -0.20, "r_benchmark": 0.05,
         "block_reason": "PRICE_SOURCE_STALE"},
        {"blocked": True, "r_candidate": -0.10, "r_benchmark": 0.01,
         "block_reason": "DIABLO_MODEL_VETO"},
    ]
    out_path = tmp_path / "bv.json"
    summary = bvr.build_business_value_summary(
        db_path=tmp_path / "nope.db",
        candidate_outcomes=rows,
        source_verified_ratio=0.8,
        demo_sessions_logged=3,
        operator_time_saved_score=0.5,
        write_summary=True,
        summary_path=out_path,
    )
    assert summary["ok"] is True
    assert summary["candidates_reviewed"] == 2
    assert summary["blocked_count"] == 2
    assert summary["diablo_blocks"] >= 1
    assert summary["stale_blocks"] >= 1
    assert "paper/advisory proxy" in summary["labels"]
    persisted = json.loads(out_path.read_text(encoding="utf-8"))
    assert persisted["claims_pl_improvement"] is False
    assert persisted["execution_gate"] == "LOCKED"
    assert persisted["broker_api_called"] is False


def test_business_value_score_bounded():
    score = bvr.business_value_score(
        days_with_records=30,
        blocked_candidates_with_outcome=25,
        source_verified_ratio=1.0,
        demo_sessions_logged=5,
        operator_time_saved_score=1.0,
    )
    assert score == 1.0


def test_read_summary_returns_none_when_missing(tmp_path):
    assert bvr.read_summary(tmp_path / "nope.json") is None
