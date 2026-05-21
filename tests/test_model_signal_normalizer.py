"""Canonical multi-model report normalizer — advisory-only, echo-aware.

Kanté "no uncontrolled model echo": five models echoing one public catalyst
must score lower independence than five genuinely independent catalysts, and
no normalized output may become an execution instruction.
"""
from __future__ import annotations

import json

from scripts import model_signal_normalizer as norm

_MODELS = ["grok", "claude", "codex", "gemini", "mistral"]


def _report(model, catalyst, *, invalidation="below 180", ticker="NVDA"):
    return {
        "model_name": model,
        "ticker": ticker,
        "direction": "bullish",
        "confidence": 0.7,
        "catalysts": [catalyst],
        "source_refs": [f"https://example.com/{model}"],
        "invalidation": invalidation,
        "thesis": f"{model} thesis on {ticker}",
    }


def test_repeated_catalyst_across_5_models_reduces_independence():
    repeated = [_report(m, "fed rate cut") for m in _MODELS]
    out = norm.normalize_model_reports(repeated, run_date="2026-05-20")
    assert out["consensus"]["repeated_catalyst_count"] >= 1
    assert out["consensus"]["echo_chamber_risk"] >= 0.5
    assert out["consensus"]["independence_score"] <= 0.5


def test_independent_catalysts_score_higher_than_repeated():
    independent = [_report(m, f"catalyst_{i}") for i, m in enumerate(_MODELS)]
    repeated = [_report(m, "fed rate cut") for m in _MODELS]
    ind = norm.normalize_model_reports(independent)
    rep = norm.normalize_model_reports(repeated)
    assert ind["consensus"]["independence_score"] > rep["consensus"]["independence_score"]
    assert ind["consensus"]["unique_catalyst_count"] > rep["consensus"]["unique_catalyst_count"]


def test_missing_invalidation_blocks_promotion():
    r = _report("grok", "earnings beat", invalidation=None)
    del r["invalidation"]
    normalized = norm.normalize_model_report(r)
    assert normalized["promotion_blocked"] is True
    assert "missing_invalidation" in normalized["risk_flags"]


def test_missing_catalysts_degrades_to_insufficient_data():
    r = {"model_name": "claude", "ticker": "AAPL", "thesis": "vibes",
         "invalidation": "below 180"}
    normalized = norm.normalize_model_report(r)
    assert normalized["advisory_status"] == norm.INSUFFICIENT_DATA
    assert "missing_catalysts" in normalized["risk_flags"]


def test_bad_parse_degrades_safely():
    for junk in (None, 42, "just a string", ["a", "list"]):
        normalized = norm.normalize_model_report(junk)
        assert normalized["advisory_status"] == norm.INSUFFICIENT_DATA
        assert normalized["ai_execution_count"] == 0
        assert normalized["promotion_blocked"] is True


def test_no_execution_language_in_output():
    reports = [_report(m, "fed rate cut") for m in _MODELS]
    out = norm.normalize_model_reports(reports)
    blob = json.dumps(out).lower()
    for forbidden in ("buy", "sell", "execute order", "place order",
                      "submit order", '"can_execute": true'):
        assert forbidden not in blob, forbidden


def test_direction_bias_never_buy_sell():
    for raw_dir in ("buy", "bullish", "long", "sell", "bearish", "garbage"):
        r = _report("grok", "x")
        r["direction"] = raw_dir
        out = norm.normalize_model_report(r)
        assert out["direction_bias"] in {
            norm.DIRECTION_LONG, norm.DIRECTION_SHORT, norm.DIRECTION_NONE
        }


def test_batch_output_is_advisory_only():
    out = norm.normalize_model_reports([_report("grok", "x")])
    assert out["advisory_status"] in {norm.REVIEW, norm.INSUFFICIENT_DATA}
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
