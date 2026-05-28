"""Tests for scripts.basket_registry.

Locks down: every basket has the required fields, ids are unique,
ticker mapping works, unknown tickers degrade gracefully, advisory
flags are present, and no forbidden trading-instruction phrase leaks
into basket copy.
"""
from __future__ import annotations

import pytest

from scripts.basket_registry import (
    FORBIDDEN_BASKET_PHRASES,
    VALID_RISK_LEVELS,
    explain_ticker_basket_mapping,
    find_baskets_for_ticker,
    get_basket_by_id,
    get_unclassified_ticker_response,
    list_baskets,
    validate_basket_registry,
)


def test_registry_validates_cleanly():
    result = validate_basket_registry()
    assert result["ok"] is True, result["errors"]
    assert result["basket_count"] == 7


def test_basket_ids_are_unique():
    ids = [b["basket_id"] for b in list_baskets()]
    assert len(ids) == len(set(ids))


REQUIRED_BASKET_FIELDS = (
    "basket_id",
    "basket_name",
    "plain_english_thesis",
    "customer_description",
    "example_tickers",
    "risk_level",
    "default_model_weight_range",
    "min_weight",
    "max_weight",
    "max_drawdown_trigger",
    "rebalance_rule",
    "what_would_break_thesis",
    "customer_status",
    "advisory_disclaimer",
    "human_decision_required",
    "advisory_only",
    "no_execution",
)


@pytest.mark.parametrize("basket", list_baskets())
def test_every_basket_has_all_required_fields(basket):
    for field in REQUIRED_BASKET_FIELDS:
        assert field in basket, f"basket {basket.get('basket_id')} missing {field}"


@pytest.mark.parametrize("basket", list_baskets())
def test_every_basket_has_valid_risk_level(basket):
    assert basket["risk_level"] in VALID_RISK_LEVELS


@pytest.mark.parametrize("basket", list_baskets())
def test_every_basket_has_advisory_flags(basket):
    assert basket["advisory_only"] is True
    assert basket["human_decision_required"] is True
    assert basket["no_execution"] is True


@pytest.mark.parametrize(
    "ticker, expected_basket_id",
    [
        ("RHM.DE", "defense_sovereignty"),
        ("LMT", "defense_sovereignty"),
        ("VALE", "commodity_repricing"),
        ("BHP", "commodity_repricing"),
        ("ZIM", "shipping_dislocation"),
        ("NVDA", "ai_infrastructure"),
        ("ASML", "ai_infrastructure"),
        ("XOM", "energy_shock"),
        ("SHEL", "energy_shock"),
        ("NSE:BHARTIARTL", "india_domestic_compounding"),
        ("NSE:HDFCBANK", "india_domestic_compounding"),
        ("CASH", "cash_risk_off"),
        ("GLD", "cash_risk_off"),
    ],
)
def test_known_ticker_maps_to_expected_basket(ticker, expected_basket_id):
    explanation = explain_ticker_basket_mapping(ticker)
    assert explanation["basket_id"] == expected_basket_id
    assert explanation["advisory_only"] is True
    assert explanation["no_execution"] is True


def test_ticker_lookup_is_case_insensitive():
    upper = explain_ticker_basket_mapping("nvda")
    assert upper["basket_id"] == "ai_infrastructure"
    matches = find_baskets_for_ticker("rhm.de")
    assert matches and matches[0]["basket_id"] == "defense_sovereignty"


@pytest.mark.parametrize(
    "unknown", ["XYZNOMAP", "FOOBAR", "NOT_A_TICKER", "", None]
)
def test_unknown_ticker_returns_unclassified(unknown):
    result = explain_ticker_basket_mapping(unknown)
    assert result["basket_id"] == "unclassified_research_required"
    assert result["advisory_only"] is True
    assert result["human_decision_required"] is True
    assert result["no_execution"] is True


def test_get_basket_by_id_round_trip():
    for basket in list_baskets():
        got = get_basket_by_id(basket["basket_id"])
        assert got is not None
        assert got["basket_id"] == basket["basket_id"]
    assert get_basket_by_id("does_not_exist") is None
    assert get_basket_by_id(None) is None


def test_unclassified_response_does_not_leak_a_basket():
    res = get_unclassified_ticker_response("ZZZ")
    assert res["basket_id"] == "unclassified_research_required"
    assert "ZZZ" in res["customer_explanation"]


def test_no_basket_copy_contains_forbidden_phrases():
    for basket in list_baskets():
        haystack = " ".join(
            str(basket.get(f, ""))
            for f in (
                "basket_name",
                "plain_english_thesis",
                "customer_description",
                "rebalance_rule",
                "what_would_break_thesis",
                "advisory_disclaimer",
                "customer_status",
            )
        ).lower()
        for phrase in FORBIDDEN_BASKET_PHRASES:
            assert phrase not in haystack, (
                f"basket {basket['basket_id']} contains forbidden {phrase!r}"
            )


def test_cash_risk_off_exists_and_is_low_risk():
    cash = get_basket_by_id("cash_risk_off")
    assert cash is not None
    assert cash["risk_level"] == "Low"


def test_extreme_risk_basket_has_bounded_max_weight():
    shipping = get_basket_by_id("shipping_dislocation")
    assert shipping is not None
    assert shipping["risk_level"] == "Extreme"
    assert shipping["max_weight"] <= 10.0
