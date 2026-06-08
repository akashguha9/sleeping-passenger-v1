"""Tests for the Signal Half-Life Estimator (HL) — P3 edge-durability module."""
from __future__ import annotations

from scripts.signal_half_life_estimator import (
    CLASS_DURABLE,
    CLASS_SNACK,
    score_signal_half_life,
)

SESSION = "2026-06-08"
_STRONG = {"earnings_growth": 0.4, "revenue_growth": 0.3, "filing_materiality": 0.8}


def _cand(**over):
    base = {
        "ticker": "PLTR", "country": "United States", "sector": "Software",
        "source_health": "VERIFIED_LIVE", "is_live": True,
        "evidence_type": "LIVE_FILING_EVENT", "live_evidence_count": 2,
        "last_live_seen_date": SESSION,
        "catalyst": "8-K contract award filed today", "invalidation_condition": "contract rescinded",
    }
    base.update(over)
    return base


def test_A_structural_filing_with_fundamentals_is_durable():
    r = score_signal_half_life(_cand(), fundamentals=_STRONG)
    assert r["half_life_class"] == CLASS_DURABLE
    assert r["short_half_life_risk"] <= 45.0
    assert r["advisory_only"] is True


def test_B_pure_momentum_no_substance_is_a_snack():
    r = score_signal_half_life(
        _cand(evidence_type="LIVE_PRICE_MOVER", catalyst="meme squeeze viral rally", invalidation_condition=""),
        attention={"social_velocity": 0.95, "price_move": 0.95, "search_spike": 0.9},
    )
    assert r["half_life_class"] == CLASS_SNACK
    assert "short_half_life_edge" in r["half_life_flags"]
    assert r["short_half_life_risk"] > 70.0


def test_C_decay_lambda_matches_half_life_days():
    import math

    r = score_signal_half_life(_cand(), fundamentals=_STRONG)
    expected = math.log(2) / r["estimated_half_life_days"]
    assert abs(r["decay_lambda_per_day"] - expected) < 1e-6


def test_D_not_live_not_scored():
    r = score_signal_half_life(
        _cand(source_health="UNVERIFIED", is_live=False, evidence_type="STATIC_UNIVERSE_FALLBACK")
    )
    assert "not_live_not_scored" in r["half_life_flags"]


def test_E_missing_feeds_surfaced():
    r = score_signal_half_life(_cand())  # no fundamentals/attention/crowding feeds
    assert "fundamental_backing" in r["missing_fields"]
    assert "crowding_feed" in r["missing_fields"]


def test_F_no_invalidation_condition_flagged():
    r = score_signal_half_life(_cand(invalidation_condition=""), fundamentals=_STRONG)
    assert "no_invalidation_condition" in r["half_life_flags"]


def test_G_crowding_shortens_durability():
    base = score_signal_half_life(_cand(), fundamentals=_STRONG)
    crowded = score_signal_half_life(_cand(), fundamentals=_STRONG, crowding={"crowding": 0.9})
    assert crowded["short_half_life_risk"] >= base["short_half_life_risk"]


def test_H_advisory_only_and_keeps_ticker():
    r = score_signal_half_life(_cand(ticker="ZIM"), fundamentals=_STRONG)
    assert r["ticker"] == "ZIM"
    assert r["advisory_only"] is True
