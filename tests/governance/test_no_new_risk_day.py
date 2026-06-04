"""Section 11 — No-new-risk day gate."""
from __future__ import annotations

import copy


def test_fixture_is_no_new_risk_yes(gov_result):
    assert gov_result.no_new_risk_day == "YES"
    assert gov_result.final_regime == "EXISTING_POSITION_MANAGEMENT_ONLY"
    assert gov_result.new_risk_permission is False


def test_missing_prices_for_all_H_forces_yes(gov_inputs, evaluate):
    res = evaluate(gov_inputs)
    assert res.source_health.current_prices_missing_for_all_H is True
    assert res.no_new_risk_day == "YES"


def test_4x_leverage_missing_price_forces_yes(gov_inputs, evaluate):
    data = copy.deepcopy(gov_inputs)
    # Give every holding a live price EXCEPT the 4x India names, and make the
    # market/news/filing payloads live so source health is no longer FAILED.
    live = {"provider": "POLYGON", "is_live": True, "provider_quality": 1.0,
            "freshness": 1.0, "completeness": 1.0, "records": [{"x": 1}]}
    data["today_market_snapshot"] = live
    data["today_price_movers"] = {**live, "movers": [{"x": 1}]}
    data["today_news_events"] = {**live, "events": [{"x": 1}]}
    data["today_filings_events"] = {**live, "events": [{"x": 1}]}
    prices = {h["ticker"]: 100.0 for h in data["verified_current_holdings"]}
    prices.pop("HDFCBANK.NS")
    prices.pop("RELIANCE.NS")
    data["current_prices"] = prices
    res = evaluate(data)
    # source health is no longer a blanket failure, but the 4x names still
    # lack a price => the hard override forces a no-new-risk day.
    assert res.no_new_risk_day == "YES"


def test_all_why_today_below_cannot_be_no(gov_inputs, evaluate):
    res = evaluate(gov_inputs)
    assert all(w < 0.70 for w in res.why_today_scores.values())
    assert res.no_new_risk_day != "NO"
