"""Tests for the unified Interpretation Defense Engine (IDS)."""
from __future__ import annotations

from scripts.interpretation_defense_engine import (
    GRADE_BLOCKED,
    GRADE_CLEAN,
    GRADE_DEFENSIVE,
    STATUS_SKIPPED,
    evaluate_candidate,
    run_interpretation_defense,
)

SESSION = "2026-06-07"
_STRONG = {
    "debt_to_equity": 0.2, "gross_margin": 0.85, "current_ratio": 2.5,
    "earnings_stability": 0.8, "interest_coverage": 10,
}


def _clean(**over):
    base = {
        "ticker": "PLTR",
        "country": "United States",
        "region": "US",
        "sector": "Software",
        "theme": "AI",
        "currency": "USD",
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
        "catalyst": "Govt contract win today",
        "invalidation_condition": "contract rescinded",
    }
    base.update(over)
    return base


def test_A_clean_candidate_is_clean():
    r = evaluate_candidate(_clean(), run_date=SESSION, fundamentals=_STRONG)
    assert r["interpretation_defense_grade"] == GRADE_CLEAN
    assert r["interpretation_defense_score"] >= 80
    assert r["advisory_only"] is True


def test_B_ambiguous_candidate_not_clean():
    r = evaluate_candidate(
        _clean(evidence_type="LIVE_PRICE_MOVER", catalyst="", theme="UNKNOWN",
               source_payload=None, invalidation_condition="missing / not provided"),
        run_date=SESSION, fundamentals=_STRONG,
    )
    assert r["interpretation_defense_grade"] != GRADE_CLEAN


def test_C_fallback_candidate_blocked():
    r = evaluate_candidate(
        _clean(source_health="UNVERIFIED", is_live=False, from_fallback=True,
               evidence_type="STATIC_UNIVERSE_FALLBACK", live_evidence_count=0,
               allowed_in_fresh_discovery=True),
        run_date=SESSION,
    )
    assert r["interpretation_defense_grade"] == GRADE_BLOCKED


def test_D_high_mtr_caps_grade():
    ref = {"geography": "INDIA", "sector": "FINANCIALS", "currency": "INR", "leverage": 4.0}
    r = evaluate_candidate(_clean(), run_date=SESSION, fundamentals=_STRONG, reference_regime=ref)
    assert r["metric_transfer_risk"]["metric_regime_transfer_risk"] > 75
    assert r["interpretation_defense_grade"] in (GRADE_DEFENSIVE, GRADE_BLOCKED)


def test_E_insufficient_stress_caps_grade():
    r = evaluate_candidate(_clean(), run_date=SESSION)  # no fundamentals
    assert r["adverse_regime_stress"]["grade"] == "INSUFFICIENT_DATA"
    assert r["interpretation_defense_grade"] in (GRADE_DEFENSIVE, GRADE_BLOCKED)


def test_F_does_not_invent_keeps_ticker():
    r = evaluate_candidate(_clean(ticker="ASML"), run_date=SESSION, fundamentals=_STRONG)
    assert r["ticker"] == "ASML"


def test_G_no_fresh_discovery_skips():
    payload = {"fresh_discovery_status": "NO_FRESH_DISCOVERY_GENERATED", "run_date": SESSION, "candidates": []}
    r = run_interpretation_defense(payload)
    assert r["status"] == STATUS_SKIPPED
    assert r["board"] == []
    assert r["blocked_count"] == 0


def test_H_advisory_only_always_true():
    assert evaluate_candidate(_clean(), run_date=SESSION, fundamentals=_STRONG)["advisory_only"] is True


def test_run_over_clean_payload_board():
    payload = {
        "fresh_discovery_status": "FRESH_DISCOVERY_OK",
        "run_date": SESSION,
        "candidates": [_clean(), _clean(ticker="ZIM", catalyst="", theme="UNKNOWN", evidence_type="LIVE_PRICE_MOVER")],
    }
    r = run_interpretation_defense(payload, fundamentals_by_ticker={"PLTR": _STRONG})
    assert r["status"] == "INTERPRETATION_DEFENSE_COMPLETED"
    assert {b["ticker"] for b in r["board"]} == {"PLTR", "ZIM"}
