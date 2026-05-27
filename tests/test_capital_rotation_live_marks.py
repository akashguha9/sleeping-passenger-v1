"""Tests — live_mark_summary flows into capital_rotation_summary."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.capital_rotation_summary import (
    LIVE_PRICE_MARKS_SUMMARY_PATH,
    build_capital_rotation_summary,
    write_release_files,
)
from scripts.live_price_marks import LIVE_MARK_SUMMARY_FILENAME


NOW = datetime(2026, 5, 26, 16, 0, 0, tzinfo=timezone.utc)


def _open_position(**overrides):
    base = {
        "ticker": "NVDA",
        "normalized_ticker": "NVDA",
        "trade_state": "OPEN",
        "status": "OPEN",
        "buy_price": 100.0,
        "stop_loss": 95.0,
        "tp_price": 130.0,
        "leverage": 1.0,
        "currency": "USD",
        "country": "United States",
        "money_allocated": 100.0,
        "quantity": 1.0,
        "age_days": 10,
        "expected_horizon_days": 30,
        "opened_at": "2026-05-16T00:00:00Z",
        "thesis": "AI infrastructure thesis",
        "source_health": "LIVE_VERIFIED",
    }
    base.update(overrides)
    return base


def test_build_summary_no_live_marks_keeps_no_live_marks_status():
    summary = build_capital_rotation_summary(
        positions=[_open_position(live_price=None)],
        candidates=[],
        live_price_lookup=None,
        source_health="LIVE_VERIFIED",
    )
    assert "live_mark_summary" in summary
    lm = summary["live_mark_summary"]
    assert lm["aggregate_source_health"] in {"NO_LIVE_MARKS"}
    assert lm["advisory_only"] is True
    assert lm["broker_api_called"] is False
    assert lm["ai_execution_count"] == 0


def test_build_summary_includes_coverage_metrics():
    summary = build_capital_rotation_summary(
        positions=[_open_position(live_price=110.0, mechanical_live_price_usable=True)],
        candidates=[],
        live_price_lookup={"NVDA": 110.0},
    )
    lm = summary["live_mark_summary"]
    assert "coverage_ratio" in lm
    assert "usable_coverage_ratio" in lm
    assert lm["coverage_ratio"] >= 0.0


def test_exit_review_classifies_partial_tp_when_price_at_tp():
    summary = build_capital_rotation_summary(
        positions=[
            _open_position(live_price=131.0, mechanical_live_price_usable=True)
        ],
        candidates=[],
        live_price_lookup={"NVDA": 131.0},
    )
    rows = summary["exit_review_board"]["rows"]
    assert rows[0]["exit_status"] == "PARTIAL_TP_NOW"


def test_exit_review_classifies_exit_now_when_price_at_stop():
    summary = build_capital_rotation_summary(
        positions=[
            _open_position(live_price=90.0, mechanical_live_price_usable=True)
        ],
        candidates=[],
        live_price_lookup={"NVDA": 90.0},
    )
    rows = summary["exit_review_board"]["rows"]
    assert rows[0]["exit_status"] == "EXIT_NOW"


def test_write_release_files_writes_live_price_marks_summary(tmp_path: Path):
    summary = build_capital_rotation_summary(
        positions=[_open_position()],
        candidates=[],
        live_price_lookup={"NVDA": 110.0},
    )
    paths = write_release_files(summary, release_dir=tmp_path)
    assert "live_price_marks_summary" in paths
    live_path = tmp_path / LIVE_MARK_SUMMARY_FILENAME
    assert live_path.exists()
    payload = json.loads(live_path.read_text(encoding="utf-8"))
    assert payload["advisory_only"] is True
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert "aggregate_source_health" in payload


def test_advisory_stamps_on_summary_and_release():
    summary = build_capital_rotation_summary(
        positions=[_open_position()],
        candidates=[],
        live_price_lookup={"NVDA": 110.0},
    )
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    lm = summary["live_mark_summary"]
    assert lm["advisory_only"] is True
    assert lm["execution_permission"] == "ADVISORY_ONLY"
