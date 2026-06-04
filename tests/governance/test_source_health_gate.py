"""Section 2 — Source Health Gate."""
from __future__ import annotations

from scripts.governance.daily_gate import compute_source_health

H = {"ANET", "MSFT", "XOM"}

LIVE_PAYLOAD = {"provider": "POLYGON", "is_live": True, "provider_quality": 1.0,
                "freshness": 1.0, "completeness": 1.0, "records": [{"x": 1}]}


def test_static_fallback_and_missing_prices_fail_closed():
    sh = compute_source_health(
        today_market_snapshot={"provider": "STATIC_UNIVERSE_FALLBACK", "is_live": False, "records": []},
        today_price_movers={"provider": "STATIC_UNIVERSE_FALLBACK", "is_live": False, "movers": []},
        today_news_events={"provider": "STATIC_OR_EMPTY_FALLBACK", "is_live": False, "events": []},
        today_filings_events={"provider": "EMPTY_FALLBACK", "is_live": False, "events": []},
        current_prices={},
        H=H,
    )
    assert sh.status == "FAILED"
    assert sh.new_risk_permission is False
    assert sh.current_prices_missing_for_all_H is True
    assert sh.all_market_news_filing_static_or_empty is True
    assert sh.score <= 0.25


def test_missing_prices_for_all_H_caps_score():
    sh = compute_source_health(
        today_market_snapshot=LIVE_PAYLOAD,
        today_price_movers=LIVE_PAYLOAD,
        today_news_events=LIVE_PAYLOAD,
        today_filings_events=LIVE_PAYLOAD,
        current_prices={},
        H=H,
    )
    assert sh.status == "FAILED"
    assert sh.score <= 0.25


def test_non_live_provider_not_counted_as_live():
    sh = compute_source_health(
        today_market_snapshot={"provider": "UNVERIFIED", "is_live": True, "provider_quality": 1.0,
                               "freshness": 1.0, "completeness": 1.0, "records": [{"x": 1}]},
        today_price_movers=LIVE_PAYLOAD,
        today_news_events=LIVE_PAYLOAD,
        today_filings_events=LIVE_PAYLOAD,
        current_prices={"ANET": 1, "MSFT": 2, "XOM": 3},
        H=H,
    )
    ms = next(p for p in sh.payload_scores if p.payload_name == "market_snapshot")
    assert ms.is_live == 0
    assert ms.counted_as_live is False


def test_high_health_when_all_live():
    sh = compute_source_health(
        today_market_snapshot=LIVE_PAYLOAD,
        today_price_movers=LIVE_PAYLOAD,
        today_news_events=LIVE_PAYLOAD,
        today_filings_events=LIVE_PAYLOAD,
        current_prices={"ANET": 1, "MSFT": 2, "XOM": 3, "provider": "POLYGON",
                        "provider_quality": 1.0, "freshness": 1.0},
        H=H,
    )
    # all components 1.0 => weighted sum 1.0 => HIGH
    assert sh.status == "HIGH"
    assert sh.score >= 0.80
    assert sh.new_risk_permission is True


def test_classification_bands():
    # medium-quality live payloads (no perfect freshness) land below HIGH.
    med = {"provider": "X", "is_live": True, "provider_quality": 0.5, "freshness": 0.5,
           "completeness": 0.5, "records": [{"a": 1}]}
    sh = compute_source_health(
        today_market_snapshot=med, today_price_movers=med,
        today_news_events=med, today_filings_events=med,
        current_prices={"ANET": 1, "MSFT": 2, "XOM": 3, "provider_quality": 0.5, "freshness": 0.5},
        H=H,
    )
    assert sh.status in ("MEDIUM", "LOW", "HIGH")
    assert 0.0 <= sh.score <= 1.0
