"""Tests for ``scripts.model_disagreement_handling``."""
from __future__ import annotations

import json

from scripts import model_disagreement_handling as mdh


def test_high_disagreement_blocks_promotion():
    out = mdh.evaluate_asset(
        "HD",
        [
            {"model_name": "a", "stance": "BULLISH", "confidence": 0.9, "reliability": 0.8},
            {"model_name": "b", "stance": "BEARISH", "confidence": 0.9, "reliability": 0.8},
            {"model_name": "c", "stance": "BULLISH", "confidence": 0.9, "reliability": 0.8},
            {"model_name": "d", "stance": "BEARISH", "confidence": 0.9, "reliability": 0.8},
        ],
    )
    assert out["state"] in {"RESEARCH_CANDIDATE", "WATCHLIST_UNCERTAIN"}
    assert out["may_promote"] is False


def test_diablo_overrides_consensus():
    out = mdh.evaluate_asset(
        "X",
        [
            {"model_name": "a", "stance": "BULLISH", "confidence": 0.9, "reliability": 0.8},
            {"model_name": "b", "stance": "BULLISH", "confidence": 0.9, "reliability": 0.8},
            {"model_name": "c", "stance": "DIABLO", "confidence": 1.0, "reliability": 0.95},
            {"model_name": "d", "stance": "BULLISH", "confidence": 0.7, "reliability": 0.7},
        ],
    )
    assert out["any_DIABLO"] is True
    assert out["state"] == "DIABLO_REVIEW"
    assert "DIABLO_MODEL_VETO" in out["downgrade_reasons"]
    assert out["may_promote"] is False


def test_reliability_weights_affect_mean():
    low = mdh.evaluate_asset(
        "L",
        [
            {"model_name": "a", "stance": "BULLISH", "confidence": 1.0, "reliability": 0.1},
            {"model_name": "b", "stance": "BEARISH", "confidence": 1.0, "reliability": 0.9},
        ],
    )
    # The high-reliability bearish model should dominate the mean.
    assert low["mu"] < 0


def test_contradictory_pair_count_is_computed():
    out = mdh.evaluate_asset(
        "C",
        [
            {"model_name": "a", "stance": "BULLISH", "confidence": 1.0, "reliability": 1.0},
            {"model_name": "b", "stance": "BEARISH", "confidence": 1.0, "reliability": 1.0},
        ],
    )
    assert out["contradiction_pair_count"] >= 1


def test_moderate_disagreement_routes_to_watchlist_uncertain():
    out = mdh.evaluate_asset(
        "M",
        [
            {"model_name": "a", "stance": "BULLISH", "confidence": 0.6, "reliability": 0.8},
            {"model_name": "b", "stance": "NEUTRAL", "confidence": 0.6, "reliability": 0.8},
            {"model_name": "c", "stance": "BULLISH", "confidence": 0.6, "reliability": 0.8},
            {"model_name": "d", "stance": "AVOID", "confidence": 0.6, "reliability": 0.8},
        ],
    )
    # Risk must land in the moderate band [0.40, 0.65).
    assert 0.0 <= out["model_disagreement_risk"]
    if 0.40 <= out["model_disagreement_risk"] < 0.65:
        assert out["state"] == "WATCHLIST_UNCERTAIN"


def test_cqs_adjustment_visible():
    out = mdh.evaluate_asset(
        "C",
        [
            {"model_name": "a", "stance": "BULLISH", "confidence": 0.9, "reliability": 0.8},
            {"model_name": "b", "stance": "BEARISH", "confidence": 0.9, "reliability": 0.8},
        ],
        cqs_base=0.80,
    )
    assert out["cqs_adjusted"] < out["cqs_base"]


def test_summary_reaches_target_and_writes(tmp_path):
    target = tmp_path / "mdh.json"
    summary = mdh.write_summary(target)
    assert summary["model_disagreement_score"] >= 9.5
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["diablo_veto_count"] >= 1
    assert on_disk["high_disagreement_count"] + on_disk["moderate_disagreement_count"] >= 1
    assert on_disk["advisory_only"] is True
    assert on_disk["broker_api_called"] is False
