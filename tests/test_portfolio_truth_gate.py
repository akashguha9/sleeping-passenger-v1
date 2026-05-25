"""Layer 1 — Portfolio Truth Gate tests.

Phantom holdings (UNG/TIP/TLT/FCG) and sold names (GLD) must never be treated
as open, even when stale ledger artifacts still list them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daily_payload_factory import holding, write_daily_payload, write_stale_ledger

from scripts.portfolio_truth_gate import (
    build_portfolio_truth_gate,
    classify_ticker,
    forbidden_management,
    management_permission,
    may_generate_management_action,
    open_verified,
)

PHANTOMS = ["UNG", "TIP", "TLT", "FCG"]


@pytest.fixture
def gate_no_holdings(tmp_path: Path):
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        verified=[],
        sold=["GLD"],
        closed=[{"ticker": "GLD", "status": "CLOSED"}],
        not_owned=PHANTOMS,
        closed_or_sold=["GLD"],
    )
    op, sl = write_stale_ledger(
        tmp_path / "stale",
        open_positions=[
            {"ticker": "UNG", "state": "OPEN"},
            {"ticker": "FCG", "state": "EXIT_PENDING"},
            {"ticker": "TLT", "state": "OPEN"},
            {"ticker": "TIP", "state": "OPEN"},
        ],
        signal_ledger=[{"ticker": "GLD", "status": "WATCHLIST"}],
    )
    return build_portfolio_truth_gate(
        payload_dir=payload_dir, open_positions_path=op, signal_ledger_path=sl
    )


def test_phantoms_and_gld_not_open(gate_no_holdings) -> None:
    gate = gate_no_holdings
    assert gate["verified_open_holdings"] == []
    assert gate["can_manage_positions"] is False
    for ticker in PHANTOMS + ["GLD"]:
        assert open_verified(ticker, gate) == 0
        assert management_permission(ticker, gate) == 0
        assert forbidden_management(ticker, gate) == 1
        assert may_generate_management_action(ticker, gate) is False


def test_phantom_labels(gate_no_holdings) -> None:
    gate = gate_no_holdings
    for ticker in PHANTOMS:
        assert classify_ticker(ticker, gate) == "DO_NOT_TREAT_AS_OPEN"
    assert classify_ticker("GLD", gate) in {"DO_NOT_TREAT_AS_OPEN", "CLOSED_OR_SOLD"}


def test_phantom_candidates_surfaced(gate_no_holdings) -> None:
    gate = gate_no_holdings
    assert "UNG" in gate["phantom_position_candidates"]
    assert "GLD" in gate["phantom_position_candidates"]


def test_discovery_permission_always_true(gate_no_holdings) -> None:
    assert gate_no_holdings["global_discovery_permission"] is True


def test_h_equals_v_minus_forbidden(tmp_path: Path) -> None:
    # V = {ANET, RTX, TLT}; D includes TLT -> TLT excluded from H.
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        verified=[holding("ANET"), holding("RTX"), holding("TLT")],
        not_owned=["TLT"],
    )
    gate = build_portfolio_truth_gate(payload_dir=payload_dir)
    assert set(gate["verified_open_holdings"]) == {"ANET", "RTX"}
    assert open_verified("ANET", gate) == 1
    assert management_permission("TLT", gate) == 0  # D wins regardless of V
    assert any("TLT" in err for err in gate["portfolio_truth_errors"])


def test_exchange_prefix_normalized(tmp_path: Path) -> None:
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        verified=[{"ticker": "NYSE:ZIM", "normalized_ticker": "ZIM", "status": "OPEN"}],
    )
    gate = build_portfolio_truth_gate(payload_dir=payload_dir)
    assert gate["verified_open_holdings"] == ["ZIM"]
    assert open_verified("NYSE:ZIM", gate) == 1
