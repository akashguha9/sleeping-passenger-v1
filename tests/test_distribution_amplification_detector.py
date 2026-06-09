"""Tests for the Distribution Amplification Detector (DA)."""
from __future__ import annotations

from scripts.distribution_amplification_detector import (
    GRADE_HYPE_LED,
    score_distribution_amplification,
)

SESSION = "2026-06-07"


def _cand(**over):
    base = {
        "ticker": "PLTR", "country": "United States", "sector": "Software", "theme": "AI",
        "source_health": "VERIFIED_LIVE", "is_live": True, "evidence_type": "LIVE_PRICE_MOVER",
        "live_evidence_count": 1, "last_live_seen_date": SESSION, "catalyst": "",
    }
    base.update(over)
    return base


def test_A_high_attention_high_fundamentals_not_hype():
    r = score_distribution_amplification(
        _cand(),
        attention={"social_velocity": 0.8, "news_velocity": 0.7, "price_move": 0.6},
        fundamentals={"earnings_growth": 0.7, "revenue_growth": 0.6, "filing_materiality": 0.7},
    )
    assert r["grade"] != GRADE_HYPE_LED
    assert r["advisory_only"] is True


def test_B_high_attention_missing_fundamentals_hype_led():
    r = score_distribution_amplification(
        _cand(),
        attention={"social_velocity": 0.9, "news_velocity": 0.8, "price_move": 0.9},
    )
    assert r["grade"] == GRADE_HYPE_LED
    assert "attention_ahead_of_substance" in r["amplification_flags"]


def test_C_low_attention_low_fundamentals_not_hype():
    r = score_distribution_amplification(
        _cand(),
        attention={"social_velocity": 0.1, "news_velocity": 0.1, "price_move": 0.1},
        fundamentals={"earnings_growth": 0.1},
    )
    assert r["grade"] != GRADE_HYPE_LED


def test_D_fallback_not_scored_as_live():
    r = score_distribution_amplification(
        _cand(source_health="UNVERIFIED", is_live=False, evidence_type="STATIC_UNIVERSE_FALLBACK")
    )
    assert "not_live_not_scored" in r["amplification_flags"]
    assert r["grade"] != GRADE_HYPE_LED


def test_E_advisory_only():
    assert score_distribution_amplification(_cand())["advisory_only"] is True


def test_F_no_invention_keeps_ticker():
    assert score_distribution_amplification(_cand(ticker="ZIM"))["ticker"] == "ZIM"


def test_missing_fundamentals_flagged():
    r = score_distribution_amplification(_cand(), attention={"price_move": 0.7})
    assert "fundamental_improvement" in r["missing_fields"]
