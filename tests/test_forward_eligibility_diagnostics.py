"""Phase 1 — forward eligibility diagnostics tests (read-only, advisory-only)."""
from __future__ import annotations

import pytest

from scripts.forward_eligibility_diagnostics import (
    build_scored_candidates,
    candidate_reasons,
    diagnose,
    forward_eligibility_diagnostics,
)
from tests._forward_snapshot_helpers import init_db, seed_market_bar, seed_score_vector

_ELIGIBLE = {
    "source_name": "sec_edgar",
    "ticker": "AAPL",
    "model_probability": 0.55,
    "has_score_vector": True,
    "prediction_horizon_days": 5,
    "target_event_definition": "forward_return_ge_threshold",
    "entry_price": 200.0,
}


def _with(**over):
    c = dict(_ELIGIBLE)
    c.update(over)
    return c


def test_diagnostics_counts_missing_ticker():
    cands = [_with(ticker=None, source_name="event_registry") for _ in range(3)] + [_ELIGIBLE]
    out = diagnose(cands)
    assert out["missing_ticker"] == 3
    assert out["forward_eligible"] == 1


def test_diagnostics_counts_missing_entry_price():
    cands = [_with(entry_price=None) for _ in range(2)] + [_ELIGIBLE]
    out = diagnose(cands)
    assert out["missing_entry_price"] == 2
    assert out["forward_eligible"] == 1


def test_diagnostics_counts_missing_probability():
    cands = [_with(model_probability=None) for _ in range(2)] + [_ELIGIBLE]
    out = diagnose(cands)
    assert out["missing_probability"] == 2


def test_diagnostics_reports_by_source():
    cands = [
        _with(source_name="sec_edgar"),
        _with(source_name="event_registry", ticker=None),
        _with(source_name="event_registry", ticker=None),
    ]
    out = diagnose(cands)
    assert out["by_source"]["sec_edgar"]["eligible"] == 1
    assert out["by_source"]["event_registry"]["ineligible"] == 2


def test_diagnostics_reports_top_missing_entry_price_tickers():
    cands = [
        _with(ticker="NVDA", entry_price=None),
        _with(ticker="NVDA", entry_price=None),
        _with(ticker="TSLA", entry_price=None),
    ]
    out = diagnose(cands)
    top = {d["key"]: d["count"] for d in out["top_missing_entry_price_tickers"]}
    assert top["NVDA"] == 2
    assert top["TSLA"] == 1


def test_eligibility_rate_formula():
    cands = [_ELIGIBLE, _ELIGIBLE, _with(ticker=None), _with(ticker=None)]
    out = diagnose(cands)
    # 2 eligible / 4 total
    assert out["eligibility_rate"] == pytest.approx(0.5)
    assert out["total_decisions"] == 4


def test_diagnostics_preserves_advisory_only_context():
    out = diagnose([_ELIGIBLE])
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["predictive_claim_allowed"] is False
    assert out["calibration_status"] == "INSUFFICIENT_EVIDENCE"


def test_diagnostics_no_execution_language():
    out = diagnose([_ELIGIBLE])
    blob = repr(out).lower()
    for banned in ("place order", "buy/sell", "execute trade", "broker_api_called': true", "auto-trade"):
        assert banned not in blob


def test_candidate_reasons_multi_leak():
    # A candidate can leak on more than one factor at once.
    reasons = candidate_reasons(_with(ticker=None, entry_price=None))
    assert "MISSING_TICKER" in reasons
    assert "MISSING_ENTRY_PRICE" in reasons


def test_missing_score_vector_reason():
    reasons = candidate_reasons(_with(has_score_vector=False, model_probability=None))
    assert "MISSING_SCORE_VECTOR" in reasons
    assert "MISSING_PROBABILITY" in reasons


def test_build_scored_candidates_from_db(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    # AAPL scored + priceable; NVDA scored but no OHLCV.
    seed_score_vector(p, event_id="e1", source_name="sec_edgar", ticker="Apple Inc.")
    seed_market_bar(p, symbol="AAPL", timestamp="2026-05-20 00:00:00-04:00", close=200.0)
    seed_score_vector(p, event_id="e2", source_name="sec_edgar", ticker="NVIDIA CORP")
    cands = build_scored_candidates(p, decision_timestamp_utc="2026-05-22T00:00:00Z")
    by_ticker = {c["ticker"]: c for c in cands}
    assert by_ticker["AAPL"]["entry_price"] == 200.0
    assert by_ticker["NVDA"]["entry_price"] is None
    out = diagnose(cands)
    assert out["forward_eligible"] == 1  # only AAPL is priceable
    assert out["missing_entry_price"] == 1  # NVDA leaks
