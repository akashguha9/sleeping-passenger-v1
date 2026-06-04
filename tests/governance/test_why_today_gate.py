"""Section 3 — WHY-TODAY score."""
from __future__ import annotations

from scripts.governance.daily_gate import why_today_score


def test_full_live_triggers_high():
    score, _ = why_today_score({
        "ticker": "AAA",
        "live_price_trigger": 1.0, "live_news_catalyst": 1.0,
        "live_filing_catalyst": 1.0, "abnormal_volume_or_move": 1.0,
        "fresh_model_consensus": 1.0,
    })
    assert score == 1.0


def test_static_fallback_capped_at_025():
    score, comp = why_today_score({
        "ticker": "RHM.DE",
        "models": ["a", "b", "c", "d"],
        "static_fallback_only": True,
        "live_price_trigger": 0.0, "live_news_catalyst": 0.0,
        "live_filing_catalyst": 0.0, "abnormal_volume_or_move": 0.0,
    })
    assert score <= 0.25
    assert comp["static_fallback_only"] is True


def test_stale_repeat_capped_at_010():
    score, comp = why_today_score(
        {"ticker": "OLD", "live_price_trigger": 0.0, "live_news_catalyst": 0.0,
         "live_filing_catalyst": 0.0, "abnormal_volume_or_move": 0.0, "fresh_model_consensus": 1.0},
        previous_tickers={"OLD"},
    )
    assert score <= 0.10
    assert comp["stale_repeat"] is True


def test_watchlist_names_below_promotion_threshold(gov_result):
    for t in ("RHM.DE", "AIR.PA", "SAP.DE"):
        assert gov_result.why_today_scores[t] <= 0.25
        assert gov_result.why_today_scores[t] < 0.70
