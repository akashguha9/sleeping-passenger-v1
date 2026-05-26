"""Tests — capital rotation summary writer + safety stamps (group G)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.capital_rotation_summary import (
    build_capital_rotation_summary,
    write_release_files,
)


def _clean_pos(**overrides) -> dict:
    base = {
        "ticker": "NVDA",
        "buy_price": 100.0,
        "live_price": 110.0,
        "stop_loss": 95.0,
        "tp_price": 130.0,
        "leverage": 1.0,
        "age_days": 5,
        "expected_horizon_days": 20,
        "source_health": "LIVE_VERIFIED",
        "status": "OPEN",
    }
    base.update(overrides)
    return base


def test_summary_built_from_injected_positions_is_self_contained() -> None:
    summary = build_capital_rotation_summary(
        positions=[_clean_pos(ticker="NVDA"), _clean_pos(ticker="MSFT")],
        source_health="LIVE_VERIFIED",
        cash_available=1000.0,
        target_cash_buffer=1000.0,
    )
    assert summary["portfolio_regime"] in {"BUY_ALLOWED", "BUY_LIMITED", "BUY_BLOCKED"}
    assert summary["portfolio_capacity_score"] >= 0
    assert summary["portfolio_capacity_score"] <= 10
    assert summary["exit_review_board"]["open_position_count"] == 2
    assert isinstance(summary["theme_slot_summary"]["themes"], list)
    assert isinstance(summary["buy_admission_board"]["rows"], list)


def test_summary_carries_advisory_stamps() -> None:
    summary = build_capital_rotation_summary(
        positions=[_clean_pos()],
        source_health="LIVE_VERIFIED",
        cash_available=1000.0,
        target_cash_buffer=1000.0,
    )
    # Group G — every output must carry the advisory invariants.
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["human_execution_required"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["execution_permission"] == "ADVISORY_ONLY"
    assert summary["advisory_status"] == "ADVISORY_ONLY"


def test_summary_serialises_to_json(tmp_path: Path) -> None:
    summary = build_capital_rotation_summary(
        positions=[_clean_pos()],
        source_health="LIVE_VERIFIED",
        cash_available=1000.0,
        target_cash_buffer=1000.0,
    )
    paths = write_release_files(summary, release_dir=tmp_path)
    for key, path_str in paths.items():
        path = Path(path_str)
        assert path.exists(), f"{key} not written"
        data = json.loads(path.read_text(encoding="utf-8"))
        # Every sibling file carries the safety stamps.
        assert data.get("advisory_only") is True
        assert data.get("broker_api_called") is False
        assert data.get("ai_execution_count") == 0


def test_juego_de_posicion_block_present() -> None:
    summary = build_capital_rotation_summary(
        positions=[_clean_pos()],
        source_health="LIVE_VERIFIED",
        cash_available=1000.0,
        target_cash_buffer=1000.0,
    )
    juego = summary["juego_de_posicion"]
    assert juego["press_intensity"] == summary["portfolio_regime"]
    assert "rotation_pressure" in juego
    assert "zones_overcrowded" in juego
    assert "zones_near_cap" in juego


def test_india_4x_auto_detection_increments_unreviewed_counter() -> None:
    positions = [
        _clean_pos(
            ticker="NSE:HDFCBANK",
            leverage=4,
            country="India",
        )
    ]
    summary = build_capital_rotation_summary(
        positions=positions,
        source_health="LIVE_VERIFIED",
        cash_available=1000.0,
        target_cash_buffer=1000.0,
    )
    assert summary["india_4x_unreviewed_count"] >= 1
    assert summary["portfolio_regime"] == "BUY_BLOCKED"


def test_summary_with_candidates_populates_buy_admission_board() -> None:
    summary = build_capital_rotation_summary(
        positions=[_clean_pos()],
        candidates=[
            {
                "ticker": "MU",
                "candidate_score": 0.9,
                "execution_readiness_score": 0.9,
                "why_today_score": 0.8,
            }
        ],
        source_health="LIVE_VERIFIED",
        cash_available=1000.0,
        target_cash_buffer=1000.0,
    )
    board = summary["buy_admission_board"]
    assert board["candidate_count"] == 1
    assert len(board["rows"]) == 1


def test_no_broker_or_execute_strings_in_serialised_summary() -> None:
    """Group G — forbidden execution tokens must not leak into the artefact."""
    summary = build_capital_rotation_summary(
        positions=[_clean_pos()],
        candidates=[
            {"ticker": "MU", "candidate_score": 0.9}
        ],
        source_health="LIVE_VERIFIED",
        cash_available=1000.0,
        target_cash_buffer=1000.0,
    )
    text = json.dumps(summary).lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "auto-trading",
        "auto_execute",
    ):
        assert forbidden not in text, forbidden
