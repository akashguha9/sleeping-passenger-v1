"""Tests for Interpretation Quality Score (IQS)."""
from __future__ import annotations

from scripts.interpretation_quality_score import (
    GRADE_HIGH,
    GRADE_TRASHY,
    score_interpretation_quality,
)

SESSION = "2026-06-07"


def _clean(**over):
    base = {
        "ticker": "PLTR",
        "country": "United States",
        "region": "US",
        "sector": "Software",
        "theme": "AI",
        "source_payload": "today_news_events",
        "source_health": "VERIFIED_LIVE",
        "is_live": True,
        "generated_at": SESSION,
        "evidence_type": "LIVE_NEWS_EVENT",
        "live_evidence_count": 2,
        "last_live_seen_date": SESSION,
        "from_cache": False,
        "from_fallback": False,
        "from_moltbook": False,
        "from_trade_log": False,
        "allowed_in_fresh_discovery": True,
        "catalyst": "Govt contract win announced today",
        "invalidation_condition": "contract rescinded",
    }
    base.update(over)
    return base


def test_A_perfect_live_candidate_high_iqs():
    r = score_interpretation_quality(_clean(), run_date=SESSION)
    assert r["interpretation_quality_score"] >= 80
    assert r["grade"] == GRADE_HIGH
    assert r["advisory_only"] is True


def test_B_fallback_candidate_is_trashy():
    fb = _clean(
        source_health="UNVERIFIED", is_live=False, from_fallback=True,
        evidence_type="STATIC_UNIVERSE_FALLBACK", live_evidence_count=0,
    )
    r = score_interpretation_quality(fb, run_date=SESSION)
    assert r["interpretation_quality_score"] <= 25
    assert r["grade"] == GRADE_TRASHY


def test_C_context_poor_scores_lower_than_context_rich():
    rich = score_interpretation_quality(_clean(), run_date=SESSION)
    poor = score_interpretation_quality(
        _clean(country="UNKNOWN", sector="UNKNOWN", theme="UNKNOWN",
               source_payload=None, catalyst="", invalidation_condition="missing / not provided"),
        run_date=SESSION,
    )
    assert poor["interpretation_quality_score"] < rich["interpretation_quality_score"]
    assert poor["context_completeness"] < rich["context_completeness"]


def test_D_contradictory_models_reduce_iqs():
    candidate = _clean(evidence_type="LIVE_PRICE_MOVER")
    no_contra = score_interpretation_quality(candidate, run_date=SESSION)
    contra_outputs = [
        {"manual_consideration": [{"ticker": "PLTR"}]},
        {"avoid": [{"ticker": "PLTR"}]},
        {"risk_blocks": [{"ticker": "PLTR"}]},
    ]
    with_contra = score_interpretation_quality(
        candidate, run_date=SESSION, model_outputs=contra_outputs,
        aggregator_row={"avg_contradiction_risk": 0.6, "split_vote": True},
    )
    assert with_contra["contradiction_intensity"] > no_contra["contradiction_intensity"]
    assert with_contra["interpretation_quality_score"] <= no_contra["interpretation_quality_score"]


def test_E_missing_why_today_raises_ambiguity_warning():
    r = score_interpretation_quality(
        _clean(evidence_type="LIVE_PRICE_MOVER", catalyst=""), run_date=SESSION
    )
    assert "missing_why_today" in r["interpretation_warnings"]
    assert r["ambiguity_risk"] > 0


def test_F_iqs_does_not_invent_ticker():
    r = score_interpretation_quality(_clean(ticker="ZIM"), run_date=SESSION)
    assert r["ticker"] == "ZIM"


def test_G_advisory_only_always_true():
    assert score_interpretation_quality(_clean(), run_date=SESSION)["advisory_only"] is True
    fb = _clean(source_health="UNVERIFIED", is_live=False, live_evidence_count=0)
    assert score_interpretation_quality(fb, run_date=SESSION)["advisory_only"] is True


def test_zero_evidence_count_scores_zero():
    r = score_interpretation_quality(_clean(live_evidence_count=0), run_date=SESSION)
    assert r["interpretation_quality_score"] == 0.0
