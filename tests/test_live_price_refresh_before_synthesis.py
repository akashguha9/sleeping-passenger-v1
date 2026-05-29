"""Tests — safe live price refresh before synthesis (P3).

Deterministic, offline (mock provider), no broker. Proves price marks populate
market_data, the bridge then sees valid_price, C_price rises, H_price_coverage
is computed, a missing provider degrades honestly, and price alone can never
make a static-fallback name executable.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.persistence import init_schema
from scripts.refresh_live_price_marks import (
    PRICE_PROVIDER_NOT_CONFIGURED,
    build_price_coverage,
    compute_h_price_coverage,
    evaluate_new_risk_gate,
    refresh_price_marks,
)
from scripts.live_price_movers_bridge import build_live_price_movers
from scripts.why_today import executable_candidate

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
_FIXTURE = {
    "AAPL": ("USD", 190.0),       # United States
    "RELIANCE.NS": ("INR", 2900.0),  # India
    "SAP.DE": ("EUR", 175.0),     # Germany
    "SHEL.L": ("GBP", 28.0),      # United Kingdom
    "7203.T": ("JPY", 3100.0),    # Japan
}


def _mock_provider(ticker):
    key = ticker.strip().upper()
    if key not in _FIXTURE:
        return None
    cur, price = _FIXTURE[key]
    return {"price": price, "timestamp_utc": NOW.isoformat(), "currency": cur, "volume": 1e6}


def _fresh_db():
    db = Path(tempfile.mkdtemp()) / "px.db"
    init_schema(db)
    return db


# 1: mock provider writes marks for 5 fixture countries -----------------------

def test_mock_provider_writes_multi_country_marks():
    db = _fresh_db()
    res = refresh_price_marks(list(_FIXTURE), provider=_mock_provider, db_path=db, now_utc=NOW)
    assert res["written"] == 5
    assert res["is_live"] is True
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0


# 2: build_live_price_movers after refresh sees valid_price=true --------------

def test_bridge_sees_valid_price_after_refresh():
    db = _fresh_db()
    refresh_price_marks(list(_FIXTURE), provider=_mock_provider, db_path=db, now_utc=NOW)
    movers = build_live_price_movers(
        db, now_utc=NOW, candidate_tickers=list(_FIXTURE), market_state="open"
    )
    valid = [r for r in movers["new_candidate_price_movers"] if r["valid_price"]]
    assert len(valid) == 5
    assert movers["meta"]["valid_price_count"] == 5


# 3-4: C_price > 0 and H_price_coverage computed ------------------------------

def test_c_price_positive_and_h_price_coverage():
    db = _fresh_db()
    refresh_price_marks(list(_FIXTURE), provider=_mock_provider, db_path=db, now_utc=NOW)
    cov = build_price_coverage(
        db, holdings=["AAPL", "SAP.DE"], candidate_tickers=["RELIANCE.NS", "SHEL.L", "7203.T"],
        now_utc=NOW, market_state="open",
    )
    assert cov["C_price"] > 0.0
    assert cov["H_price_coverage"] == 1.0  # both holdings have fresh marks


# 5: missing provider -> honest fallback, C_price stays 0 ---------------------

def test_missing_provider_keeps_c_price_zero():
    db = _fresh_db()
    res = refresh_price_marks(list(_FIXTURE), provider=None, db_path=db, now_utc=NOW)
    assert res["status"] == PRICE_PROVIDER_NOT_CONFIGURED
    assert res["written"] == 0
    cov = build_price_coverage(
        db, candidate_tickers=list(_FIXTURE), now_utc=NOW, market_state="open"
    )
    assert cov["C_price"] == 0.0


def test_h_price_coverage_degraded_warns():
    # One holding has a fresh mark, one does not -> coverage 0.5 < theta -> warn.
    db = _fresh_db()
    refresh_price_marks(["AAPL"], provider=_mock_provider, db_path=db, now_utc=NOW)
    cov = build_price_coverage(
        db, holdings=["AAPL", "SAP.DE"], now_utc=NOW, market_state="open"
    )
    assert cov["H_price_coverage"] == 0.5
    gate = evaluate_new_risk_gate(cov["H_price_coverage"], cov["C_price"])
    assert gate["new_risk_allowed"] is False
    assert "EXISTING_RISK_VISIBILITY_DEGRADED" in gate["warnings"]
    assert gate["execution_gate"] == "LOCKED"  # gate never unlocks execution


# 7: price alone cannot make a static-fallback name executable ----------------

def test_static_fallback_not_executable_even_with_price():
    assert (
        executable_candidate(
            why_today_score_value=1.0,
            source_health_score=1.0,
            valid_price=True,            # price exists
            mapping_confidence=1.0,
            country_coverage_confidence=1.0,
            in_phantom_closed_sold=False,
            is_static_universe_only=True,  # ...but still static -> veto
        )
        is False
    )


# 8: live mapped name can be a candidate, but stays advisory ------------------

def test_live_mapped_name_is_candidate_but_advisory():
    eligible = executable_candidate(
        why_today_score_value=0.8,
        source_health_score=0.8,
        valid_price=True,
        mapping_confidence=0.85,
        country_coverage_confidence=0.6,
        in_phantom_closed_sold=False,
        is_static_universe_only=False,
    )
    assert eligible is True
    # The new-risk gate (the advisory authority around candidacy) never unlocks
    # execution regardless of eligibility.
    gate = evaluate_new_risk_gate(1.0, 0.5)
    assert gate["broker_api_called"] is False
    assert gate["ai_execution_count"] == 0
    assert gate["execution_gate"] == "LOCKED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
