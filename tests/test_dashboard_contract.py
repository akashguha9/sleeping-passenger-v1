"""Tests for scripts/dashboard_contract.py — stable unified JSON contract."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.google_sheet_schema import load_trade_log_csv
from scripts.dashboard_contract import CONTRACT_VERSION, build_dashboard

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trade_log_sample.csv"
REPORT = date(2026, 6, 2)


@pytest.fixture()
def contract():
    rows = load_trade_log_csv(FIXTURE).rows
    return build_dashboard(rows, 4000.0, REPORT)


def test_contract_top_level_shape(contract):
    for key in (
        "capital", "win_rate", "expectancy", "diversity",
        "outcome_maturity", "model_versions", "advisory_safety", "warnings",
    ):
        assert key in contract
    assert contract["contract_version"] == CONTRACT_VERSION


def test_capital_labels_distinguish_equity_and_free_cash(contract):
    cap = contract["capital"]
    assert cap["marked_equity"] == pytest.approx(4029.76)
    assert cap["free_cash"] == pytest.approx(2623.934293)
    assert cap["capital_after_row_is_total_equity"] is False
    # Realised + unrealised are reported separately.
    assert "realised_pl" in cap and "unrealised_marked_pl" in cap
    assert "free_cash" in contract["labels"]


def test_closed_only_evidence_flagged_immature(contract):
    assert contract["win_rate"]["closed_only_evidence_immature"] is True


def test_advisory_safety_block_locked(contract):
    safety = contract["advisory_safety"]
    assert safety["advisory_only"] is True
    assert safety["human_execution_required"] is True
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_gate"] == "LOCKED"
    assert safety["real_money_sizing_impact"] == "PROHIBITED"


def test_optional_discovery_board_attaches(contract):
    rows = load_trade_log_csv(FIXTURE).rows
    board = {"total_discovered": 0, "concentration_warnings": []}
    c = build_dashboard(rows, 4000.0, REPORT, discovery_board=board)
    assert c["discovery_board"] == board
