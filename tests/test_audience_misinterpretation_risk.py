"""Tests for Audience Misinterpretation Risk (AMR)."""
from __future__ import annotations

from scripts.audience_misinterpretation_risk import (
    GRADE_MISREAD,
    score_audience_misinterpretation,
)

SESSION = "2026-06-07"


def _cand(**over):
    base = {
        "ticker": "PLTR", "country": "United States", "sector": "Software", "theme": "Govt analytics",
        "source_health": "VERIFIED_LIVE", "is_live": True, "evidence_type": "LIVE_FILING_EVENT",
        "live_evidence_count": 2, "last_live_seen_date": SESSION, "catalyst": "8-K contract award filed today",
    }
    base.update(over)
    return base


def test_A_specific_filing_thesis_low_or_medium():
    r = score_audience_misinterpretation(_cand())
    assert r["grade"] in ("LOW", "MEDIUM")
    assert r["advisory_only"] is True


def test_B_vague_ai_thesis_high():
    promo = [{"manual_consideration": [{"ticker": "PLTR", "reason": "AI structural winner breakout momentum cheap"}]} for _ in range(4)]
    r = score_audience_misinterpretation(
        _cand(evidence_type="LIVE_PRICE_MOVER", catalyst="", theme="AI momentum"),
        narrative_gap={"narrative_substance_gap": 65.0},
        distribution={"distribution_amplification_score": 80.0},
        model_outputs=promo,
    )
    assert r["grade"] in ("HIGH", GRADE_MISREAD)
    assert r["ambiguous_terms"]


def test_C_model_agreement_without_live_evidence_flagged():
    promo = [{"manual_consideration": [{"ticker": "PLTR", "reason": "looks good"}]} for _ in range(5)]
    r = score_audience_misinterpretation(
        _cand(evidence_type="LIVE_PRICE_MOVER", catalyst=""),
        model_outputs=promo,
    )
    assert "model_agreement_without_strong_live_evidence" in r["misread_flags"]
    assert r["audience_risks"]["model"] == "HIGH"


def test_D_operator_misread_when_live_but_incomplete():
    r = score_audience_misinterpretation(
        _cand(evidence_type="LIVE_PRICE_MOVER", catalyst=""),
        p1={"interpretation_quality": {"ambiguity_risk": 0.6, "missing_context_fields": ["catalyst"]}},
    )
    assert "operator_misread_risk_live_but_incomplete" in r["misread_flags"]


def test_E_no_invention_keeps_ticker():
    assert score_audience_misinterpretation(_cand(ticker="RHM.DE"))["ticker"] == "RHM.DE"


def test_F_advisory_only():
    assert score_audience_misinterpretation(_cand())["advisory_only"] is True
