"""Tests for the Narrative-Substance Gap (NSG)."""
from __future__ import annotations

from scripts.narrative_substance_gap import (
    GRADE_NARRATIVE_OVERHANG,
    GRADE_SUBSTANCE_LED,
    score_narrative_substance_gap,
)

SESSION = "2026-06-07"


def _cand(**over):
    base = {
        "ticker": "PLTR", "country": "United States", "sector": "Software", "theme": "AI",
        "source_health": "VERIFIED_LIVE", "is_live": True, "evidence_type": "LIVE_FILING_EVENT",
        "live_evidence_count": 2, "last_live_seen_date": SESSION, "catalyst": "8-K filed today",
    }
    base.update(over)
    return base


def test_A_filing_supported_substance_led():
    r = score_narrative_substance_gap(
        _cand(),
        fundamentals={"earnings_growth": 0.7, "revenue_growth": 0.6, "filing_materiality": 0.8},
    )
    assert r["grade"] in (GRADE_SUBSTANCE_LED, "BALANCED")
    assert r["narrative_substance_gap"] < 25
    assert r["advisory_only"] is True


def test_B_viral_price_only_narrative_overhang():
    promo = [{"manual_consideration": [{"ticker": "PLTR", "reason": "AI breakout momentum"}]} for _ in range(5)]
    r = score_narrative_substance_gap(
        _cand(evidence_type="LIVE_PRICE_MOVER", catalyst="", theme="AI momentum"),
        distribution={"attention_growth": 0.95, "fundamental_improvement": 0.05},
        model_outputs=promo,
    )
    assert r["grade"] == GRADE_NARRATIVE_OVERHANG
    assert r["narrative_substance_gap"] > 60


def test_C_missing_data_warns():
    r = score_narrative_substance_gap(_cand(evidence_type="LIVE_PRICE_MOVER"))
    assert "fundamentals" in r["missing_fields"]
    assert r["warnings"]


def test_D_static_excluded():
    r = score_narrative_substance_gap(_cand(source_health="UNVERIFIED", is_live=False))
    assert "not_live_not_scored" in r["narrative_flags"]


def test_E_no_invention_keeps_ticker():
    assert score_narrative_substance_gap(_cand(ticker="ASML"))["ticker"] == "ASML"
