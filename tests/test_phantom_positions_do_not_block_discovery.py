"""Phantom positions must never block fresh discovery."""
from __future__ import annotations

from pathlib import Path

from daily_payload_factory import write_daily_payload, write_stale_ledger

from scripts.fresh_market_discovery import build_fresh_market_discovery
from scripts.portfolio_truth_gate import build_portfolio_truth_gate


def _setup(tmp_path: Path):
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        verified=[],
        sold=["GLD"],
        closed=[{"ticker": "GLD", "status": "CLOSED"}],
        not_owned=["UNG", "TIP", "TLT", "FCG"],
        closed_or_sold=["GLD"],
        movers=[
            {"ticker": "RTX", "freshness": "UNVERIFIED"},
            {"ticker": "ZIM", "freshness": "UNVERIFIED"},
            {"ticker": "SAP.DE", "freshness": "UNVERIFIED"},
            {"ticker": "ANET", "freshness": "UNVERIFIED"},
            {"ticker": "BHP", "freshness": "UNVERIFIED"},
        ],
    )
    op, sl = write_stale_ledger(
        tmp_path / "stale",
        open_positions=[{"ticker": "UNG", "state": "OPEN", "stop_loss": 13.0}],
        signal_ledger=[{"ticker": "UNG", "status": "EXECUTED_CHAOS"}],
    )
    gate = build_portfolio_truth_gate(
        payload_dir=payload_dir, open_positions_path=op, signal_ledger_path=sl
    )
    discovery = build_fresh_market_discovery(payload_dir=payload_dir, truth_gate=gate)
    return gate, discovery


def test_discovery_permission_true_despite_phantom(tmp_path: Path) -> None:
    gate, discovery = _setup(tmp_path)
    assert "UNG" in gate["phantom_position_candidates"]
    assert gate["global_discovery_permission"] is True
    assert discovery["global_discovery_permission"] is True


def test_fresh_candidates_still_appear(tmp_path: Path) -> None:
    _gate, discovery = _setup(tmp_path)
    universe = set(discovery["discovery_universe"])
    for ticker in ("RTX", "ZIM", "SAP.DE", "ANET", "BHP"):
        assert ticker in universe


def test_discovery_underpowered_but_not_skipped(tmp_path: Path) -> None:
    _gate, discovery = _setup(tmp_path)
    assert discovery["discovery_underpowered"] is True
    assert discovery["discovery_universe"], "universe must not be empty"
    assert any("not skipped" in note.lower() for note in discovery["discovery_notes"])
