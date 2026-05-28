"""Tests for scripts.model_portfolio.

Locks down: weights sum to 100%, cash exists, baskets are real, risk
caps are enforced, advisory flags are present, validation catches the
obvious failure modes.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.basket_registry import list_baskets
from scripts.customer_language import (
    CUSTOMER_LABEL_AVOID_EXIT_RISK,
    KNOWN_CUSTOMER_LABELS,
)
from scripts.model_portfolio import (
    get_basket_allocation_table,
    get_default_model_portfolio,
    get_model_portfolio_summary,
    get_portfolio_drawdown_rules,
    validate_model_portfolio,
)


def test_default_portfolio_sums_to_100():
    mp = get_default_model_portfolio()
    total = sum(row["target_weight"] for row in mp["allocation"])
    assert total == 100
    assert mp["total_target_weight"] == 100


def test_default_portfolio_has_cash_basket():
    mp = get_default_model_portfolio()
    ids = {row["basket_id"] for row in mp["allocation"]}
    assert "cash_risk_off" in ids


def test_every_referenced_basket_exists_in_registry():
    mp = get_default_model_portfolio()
    valid_ids = {b["basket_id"] for b in list_baskets()}
    for row in mp["allocation"]:
        assert row["basket_id"] in valid_ids


def test_every_allocation_row_has_thesis_and_invalidation():
    mp = get_default_model_portfolio()
    for row in mp["allocation"]:
        assert row["thesis_summary"], row
        assert row["invalidation_summary"], row
        assert row["rebalance_rule"], row


def test_default_portfolio_has_advisory_flags():
    mp = get_default_model_portfolio()
    assert mp["advisory_only"] is True
    assert mp["human_decision_required"] is True
    assert mp["human_execution_required"] is True
    assert mp["no_execution"] is True
    assert mp["execution_permission"] == "LOCKED"


def test_default_portfolio_uses_customer_action_labels_only():
    mp = get_default_model_portfolio()
    for row in mp["allocation"]:
        assert row["current_action_label"] in KNOWN_CUSTOMER_LABELS


def test_default_portfolio_validates_cleanly():
    mp = get_default_model_portfolio()
    result = validate_model_portfolio(mp)
    assert result["ok"] is True, result["errors"]
    assert result["total_weight"] == 100
    assert result["basket_count"] == len(mp["allocation"])


def test_validate_rejects_non_100_total():
    mp = get_default_model_portfolio()
    mp["allocation"][0]["target_weight"] += 5
    result = validate_model_portfolio(mp)
    assert result["ok"] is False
    assert any("sum" in e or "100" in e for e in result["errors"])


def test_validate_rejects_missing_cash():
    mp = get_default_model_portfolio()
    mp["allocation"] = [r for r in mp["allocation"] if r["basket_id"] != "cash_risk_off"]
    # Rebalance the remainder to 100 so the only failure is missing cash.
    leftover = 100 - sum(r["target_weight"] for r in mp["allocation"])
    mp["allocation"][0]["target_weight"] += leftover
    result = validate_model_portfolio(mp)
    assert result["ok"] is False
    assert any("cash" in e.lower() for e in result["errors"])


def test_validate_rejects_unknown_basket():
    mp = get_default_model_portfolio()
    mp["allocation"][0]["basket_id"] = "made_up_basket"
    result = validate_model_portfolio(mp)
    assert result["ok"] is False
    assert any("unknown basket" in e for e in result["errors"])


def test_validate_rejects_extreme_basket_over_cap():
    mp = get_default_model_portfolio()
    # Move all of AI infrastructure into shipping (Extreme, cap 10%).
    for row in mp["allocation"]:
        if row["basket_id"] == "shipping_dislocation":
            row["target_weight"] = 25
        if row["basket_id"] == "ai_infrastructure":
            row["target_weight"] = 0
    result = validate_model_portfolio(mp)
    assert result["ok"] is False
    assert any("exceeds risk-level cap" in e for e in result["errors"])


def test_validate_rejects_avoid_exit_risk_with_allocation():
    mp = get_default_model_portfolio()
    mp["allocation"][0]["current_action_label"] = CUSTOMER_LABEL_AVOID_EXIT_RISK
    result = validate_model_portfolio(mp)
    assert result["ok"] is False
    assert any("Avoid/Exit Risk" in e for e in result["errors"])


def test_validate_rejects_missing_safety_flags():
    mp = get_default_model_portfolio()
    mp.pop("no_execution")
    result = validate_model_portfolio(mp)
    assert result["ok"] is False
    assert any("no_execution" in e for e in result["errors"])


def test_validate_handles_garbage_input():
    assert validate_model_portfolio({})["ok"] is False  # type: ignore[arg-type]
    assert validate_model_portfolio({"allocation": []})["ok"] is False
    assert validate_model_portfolio({"allocation": "nope"})["ok"] is False


def test_summary_endpoint_returns_safety_metadata():
    summary = get_model_portfolio_summary()
    assert summary["advisory_only"] is True
    assert summary["execution_permission"] == "LOCKED"
    assert summary["basket_count"] == 7
    assert summary["total_target_weight"] == 100


def test_drawdown_rules_present():
    rules = get_portfolio_drawdown_rules()
    assert "review_trigger" in rules
    assert "defensive_trigger" in rules
    assert "thesis_audit_trigger" in rules


def test_basket_allocation_table_is_flat_list():
    table = get_basket_allocation_table()
    assert isinstance(table, list)
    assert all(isinstance(row, dict) for row in table)
    assert all("basket_id" in row and "target_weight" in row for row in table)


def test_get_default_model_portfolio_returns_fresh_copies():
    a = get_default_model_portfolio()
    a["allocation"][0]["target_weight"] = 999
    b = get_default_model_portfolio()
    assert b["allocation"][0]["target_weight"] != 999
    _ = deepcopy(a)
