"""Tests for the expanded (P1+P2) interpretation defense engine."""
from __future__ import annotations

from scripts.interpretation_defense_engine import (
    GRADE_BLOCKED,
    GRADE_CLEAN,
    GRADE_DEFENSIVE,
    STATUS_SKIPPED,
    evaluate_candidate_expanded,
    run_expanded_interpretation_defense,
)

SESSION = "2026-06-07"
_STRONG = {
    "debt_to_equity": 0.2, "gross_margin": 0.85, "current_ratio": 2.5,
    "earnings_stability": 0.8, "interest_coverage": 10,
    "earnings_growth": 0.4, "revenue_growth": 0.3, "filing_materiality": 0.8,
}


def _clean(**over):
    base = {
        "ticker": "PLTR", "country": "United States", "region": "US", "sector": "Software",
        "theme": "Govt analytics", "currency": "USD", "source_payload": "today_filings_events",
        "source_health": "VERIFIED_LIVE", "is_live": True, "generated_at": SESSION,
        "evidence_type": "LIVE_FILING_EVENT", "live_evidence_count": 2, "last_live_seen_date": SESSION,
        "from_cache": False, "from_fallback": False, "from_moltbook": False, "from_trade_log": False,
        "allowed_in_fresh_discovery": True, "catalyst": "8-K contract award filed today",
        "invalidation_condition": "contract rescinded",
    }
    base.update(over)
    return base


def test_A_clean_p1_low_p2_stays_clean():
    r = evaluate_candidate_expanded(_clean(), run_date=SESSION, fundamentals=_STRONG)
    assert r["p1_interpretation_defense"]["interpretation_defense_grade"] == GRADE_CLEAN
    assert r["expanded_grade"] == GRADE_CLEAN
    assert r["advisory_only"] is True


def test_B_hype_led_caps_at_defensive_or_lower():
    r = evaluate_candidate_expanded(
        _clean(evidence_type="LIVE_PRICE_MOVER", catalyst="", theme="AI momentum"),
        run_date=SESSION,  # no fundamentals -> substance unevidenced
        attention={"social_velocity": 0.95, "news_velocity": 0.9, "price_move": 0.95},
    )
    assert r["p2_interpretation_expansion"]["distribution_amplification"]["grade"] == "HYPE_LED"
    assert r["expanded_grade"] in (GRADE_DEFENSIVE, GRADE_BLOCKED)


def test_C_exit_liquidity_caps_at_defensive_or_lower():
    r = evaluate_candidate_expanded(
        _clean(evidence_type="LIVE_PRICE_MOVER", catalyst="", theme="MEME"),
        run_date=SESSION,
        attention={"social_velocity": 0.95, "price_move": 0.95},
        liquidity={"fragility": 0.9},
    )
    assert r["p2_interpretation_expansion"]["incentive_who_benefits"]["grade"] == "EXIT_LIQUIDITY_RISK"
    assert r["expanded_grade"] in (GRADE_DEFENSIVE, GRADE_BLOCKED)


def test_D_blocked_p1_stays_blocked():
    r = evaluate_candidate_expanded(
        _clean(source_health="UNVERIFIED", is_live=False, from_fallback=True,
               evidence_type="STATIC_UNIVERSE_FALLBACK", live_evidence_count=0),
        run_date=SESSION,
    )
    assert r["p1_interpretation_defense"]["interpretation_defense_grade"] == GRADE_BLOCKED
    assert r["expanded_grade"] == GRADE_BLOCKED


def test_E_missing_p2_data_surfaced_as_warnings():
    r = evaluate_candidate_expanded(_clean(evidence_type="LIVE_PRICE_MOVER"), run_date=SESSION)
    assert any(w.startswith("missing:") for w in r["warnings"])


def test_F_no_fresh_discovery_skips():
    payload = {"fresh_discovery_status": "NO_FRESH_DISCOVERY_GENERATED", "run_date": SESSION, "candidates": []}
    r = run_expanded_interpretation_defense(payload)
    assert r["status"] == STATUS_SKIPPED
    assert r["board"] == []


def test_G_p2_cannot_promote_beyond_p1():
    # expanded IDS must never exceed P1 IDS (penalty is subtractive).
    r = evaluate_candidate_expanded(_clean(), run_date=SESSION, fundamentals=_STRONG)
    assert (r["expanded_interpretation_defense_score"]
            <= r["p1_interpretation_defense"]["interpretation_defense_score"] + 1e-6)
