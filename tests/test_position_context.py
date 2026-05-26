"""Tests — scripts/position_context.py merge + quality scoring."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.position_context import (
    CONTEXT_COMPLETE,
    CONTEXT_INSUFFICIENT,
    CONTEXT_PARTIAL,
    CONTEXT_USABLE,
    PositionContext,
    REASON_CONTEXT_FROM_MANUAL_LOG,
    REASON_CONTEXT_FROM_VERIFIED_HOLDINGS,
    REASON_CONTEXT_MERGED,
    REASON_CURRENCY_UNKNOWN,
    REASON_HISTORICAL_NOT_OPEN,
    REASON_LEVERAGE_DEFAULTED,
    REASON_LIVE_MARK_MISSING,
    REASON_THESIS_CONTEXT_MISSING,
    SOURCE_MANUAL_LOG,
    SOURCE_VERIFIED_HOLDINGS,
    compute_context_quality,
    load_position_context,
    merge_position_context,
    normalize_position_ticker,
    position_context_to_lifecycle_input,
)
from scripts.portfolio_lifecycle import (
    EXIT_DATA_BLOCKED,
    EXIT_HOLD_OK,
    EXIT_PARTIAL_TP_NOW,
    EXIT_RUNNER_HOLD,
    classify_exit_status,
    classify_position,
)


NOW = datetime(2026, 5, 26, tzinfo=timezone.utc)


def _holding(**overrides):
    base = {
        "ticker": "NASDAQ:NVDA",
        "normalized_ticker": "NVDA",
        "status": "OPEN",
        "quantity": 1.0,
        "entry_price": 100.0,
        "tp_price": 130.0,
        "currency": "USD",
        "country": "United States",
        "leverage": 1,
        "opened_at": "2026-05-20T00:00:00Z",
    }
    base.update(overrides)
    return base


def _trade(**overrides):
    base = {
        "ticker": "NVDA",
        "side": "BUY",
        "quantity": 1.0,
        "price": 100.0,
        "leverage": 1.0,
        "executed_at": "2026-05-20T00:00:00Z",
        "thesis": "AI infrastructure thesis",
        "entry_reason": "breakout from base",
        "risk_reason": "loses 95",
        "exit_plan": "trim 50% at 130 then trail",
        "invalidation_level": "95",
        "expected_horizon": "20 days",
        "currency": "USD",
        "ai_model_used": "claude-opus",
        "cancelled_at": "",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# normalize_position_ticker
# ---------------------------------------------------------------------------


def test_normalize_position_ticker_strips_exchange_prefix():
    assert normalize_position_ticker("NASDAQ:GOOGL") == "GOOGL"
    assert normalize_position_ticker("NYSE:GD") == "GD"
    assert normalize_position_ticker("NSE:HDFCBANK") == "HDFCBANK"
    assert normalize_position_ticker("EPA:AIR") == "AIR"


def test_normalize_position_ticker_preserves_country_suffix():
    assert normalize_position_ticker("HDFCBANK.NS") == "HDFCBANK.NS"
    assert normalize_position_ticker("SAP.DE") == "SAP.DE"


def test_normalize_position_ticker_handles_blank():
    assert normalize_position_ticker("") == ""
    assert normalize_position_ticker(None) == ""


# ---------------------------------------------------------------------------
# Quality scoring (Section 3)
# ---------------------------------------------------------------------------


def _complete_ctx(**overrides) -> PositionContext:
    ctx = PositionContext(
        ticker="NVDA",
        trade_state="OPEN",
        buy_price=100.0,
        live_price=110.0,
        stop_loss=95.0,
        tp_price=130.0,
        leverage=1.0,
        currency="USD",
        opened_at="2026-05-20T00:00:00Z",
        last_updated_at="2026-05-25T00:00:00Z",
    )
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


def test_compute_context_quality_complete():
    ctx = _complete_ctx()
    score, label, missing = compute_context_quality(ctx)
    assert score >= 0.90
    assert label == CONTEXT_COMPLETE
    assert missing == []


def test_compute_context_quality_missing_live_drops_to_partial_or_usable():
    ctx = _complete_ctx(live_price=None)
    score, label, missing = compute_context_quality(ctx)
    assert "live_price" in missing
    assert label in (CONTEXT_USABLE, CONTEXT_PARTIAL)


def test_compute_context_quality_only_buy_price_is_insufficient():
    ctx = PositionContext(
        ticker="X",
        buy_price=100.0,
        currency="UNKNOWN",
        leverage=0.0,
    )
    score, label, missing = compute_context_quality(ctx)
    assert label in (CONTEXT_INSUFFICIENT, CONTEXT_PARTIAL)
    assert "live_price" in missing
    assert "stop_loss" in missing
    assert "tp_price" in missing


# ---------------------------------------------------------------------------
# merge_position_context — Section 4
# ---------------------------------------------------------------------------


def test_merge_complete_manual_trade_row_yields_COMPLETE_quality():
    holding = _holding()
    trade = _trade()
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=[trade],
        live_marks={"NVDA": 110.0},
        now_utc=NOW,
    )
    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx.context_quality == CONTEXT_COMPLETE
    assert ctx.context_quality_score >= 0.90
    assert ctx.buy_price == 100.0
    assert ctx.live_price == 110.0
    assert ctx.stop_loss == 95.0
    assert ctx.expected_horizon_days == 20.0
    assert ctx.thesis
    assert REASON_CONTEXT_FROM_MANUAL_LOG in ctx.reason_codes
    assert REASON_CONTEXT_MERGED in ctx.reason_codes


def test_merge_missing_thesis_does_not_block_lifecycle():
    holding = _holding()
    trade = _trade(thesis="", entry_reason="", risk_reason="", exit_plan="")
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=[trade],
        live_marks={"NVDA": 110.0},
        now_utc=NOW,
    )
    ctx = contexts[0]
    # The merge should record the soft-context-missing reason code…
    assert REASON_THESIS_CONTEXT_MISSING in ctx.reason_codes
    # …but the lifecycle classifier must NOT see DATA_BLOCKED, because
    # all mechanical fields are present.
    payload = position_context_to_lifecycle_input(ctx)
    # Add tp_price since it does not come from the manual trade row.
    payload["tp_price"] = 130.0
    result = classify_exit_status(payload)
    assert result["exit_status"] != EXIT_DATA_BLOCKED
    assert "THESIS_CONTEXT_MISSING" in result["reason_codes"]


def test_merge_missing_live_price_marks_field_missing():
    holding = _holding()
    trade = _trade()
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=[trade],
        live_marks={},  # no live mark
        now_utc=NOW,
    )
    ctx = contexts[0]
    assert ctx.live_price is None
    assert "live_price" in ctx.missing_fields
    assert REASON_LIVE_MARK_MISSING in ctx.reason_codes


def test_closed_holding_row_marked_historical_not_open():
    holding = _holding(status="OPEN")  # legacy stale row
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=[_trade()],
        closed_tickers=["NVDA"],
        now_utc=NOW,
    )
    ctx = contexts[0]
    assert ctx.trade_state == "CLOSED"
    assert REASON_HISTORICAL_NOT_OPEN in ctx.reason_codes


def test_partial_tp_row_with_sells_becomes_partial_tp_logged():
    holding = _holding(quantity=2.0, entry_price=100.0)
    trades = [
        _trade(side="BUY", quantity=2.0, price=100.0),
        _trade(side="SELL", quantity=1.4, price=120.0, executed_at="2026-05-25T00:00:00Z"),
    ]
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=trades,
        live_marks={"NVDA": 125.0},
        now_utc=NOW,
    )
    ctx = contexts[0]
    assert ctx.partial_tp_logged is True
    assert ctx.booked_pct == pytest.approx(70.0)
    assert ctx.ride_pct == pytest.approx(30.0)


def test_partial_tp_row_becomes_RUNNER_HOLD_in_lifecycle():
    holding = _holding(quantity=2.0)
    trades = [
        _trade(side="BUY", quantity=2.0, price=100.0),
        _trade(side="SELL", quantity=1.4, price=120.0, executed_at="2026-05-25T00:00:00Z"),
    ]
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=trades,
        live_marks={"NVDA": 125.0},
        now_utc=NOW,
    )
    payload = position_context_to_lifecycle_input(contexts[0])
    payload["tp_price"] = 130.0
    result = classify_exit_status(
        payload,
        {"thesis_status": "THESIS_CONFIRMED"},
    )
    assert result["exit_status"] == EXIT_RUNNER_HOLD


def test_tp_due_row_with_partial_unlogged_is_PARTIAL_TP_NOW():
    holding = _holding(quantity=1.0)
    trade = _trade()
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=[trade],
        live_marks={"NVDA": 131.0},
        now_utc=NOW,
    )
    payload = position_context_to_lifecycle_input(contexts[0])
    payload["tp_price"] = 130.0
    result = classify_exit_status(payload)
    assert result["exit_status"] == EXIT_PARTIAL_TP_NOW


def test_air_dual_listing_collapses_to_AIRBUS_economic_key():
    holdings = [
        _holding(ticker="EPA:AIR", normalized_ticker="AIR", currency="EUR"),
    ]
    contexts = merge_position_context(
        holdings=holdings,
        trade_rows=[],
        live_marks={},
        now_utc=NOW,
    )
    assert contexts[0].economic_exposure_key == "AIRBUS"


def test_latest_reconciled_value_wins_over_stale():
    holding = _holding(quantity=1.0)
    trades = [
        _trade(
            side="BUY",
            quantity=1.0,
            price=100.0,
            executed_at="2026-05-01T00:00:00Z",
            thesis="stale thesis",
            invalidation_level="80",
            expected_horizon="30 days",
        ),
        _trade(
            side="BUY",
            quantity=0.0,
            price=100.0,
            executed_at="2026-05-25T00:00:00Z",
            thesis="updated thesis",
            invalidation_level="95",
            expected_horizon="20 days",
        ),
    ]
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=trades,
        live_marks={"NVDA": 110.0},
        now_utc=NOW,
    )
    ctx = contexts[0]
    assert ctx.thesis == "updated thesis"
    assert ctx.stop_loss == 95.0
    assert ctx.expected_horizon_days == 20.0


def test_leverage_defaults_to_one_with_reason_code():
    holding = _holding(leverage=0)
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=[],
        live_marks={},
        now_utc=NOW,
    )
    ctx = contexts[0]
    assert ctx.leverage == 1.0
    assert REASON_LEVERAGE_DEFAULTED in ctx.reason_codes


def test_unknown_currency_records_reason_and_lowers_quality():
    holding = _holding(currency="")
    contexts = merge_position_context(
        holdings=[holding],
        trade_rows=[_trade(currency="")],
        live_marks={"NVDA": 110.0},
        now_utc=NOW,
    )
    ctx = contexts[0]
    assert ctx.currency == "UNKNOWN"
    assert REASON_CURRENCY_UNKNOWN in ctx.reason_codes
    assert "currency" in ctx.missing_fields


# ---------------------------------------------------------------------------
# load_position_context — integration with a tmp SQLite DB
# ---------------------------------------------------------------------------


def _make_tmp_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE manual_trades (
            trade_id TEXT PRIMARY KEY,
            event_id TEXT, ticker TEXT, side TEXT,
            quantity REAL, price REAL, executed_at TEXT,
            thesis TEXT, notes TEXT, leverage REAL,
            invalidation_level TEXT, expected_horizon TEXT,
            risk_reason TEXT, entry_reason TEXT, exit_plan TEXT,
            confidence_before REAL, emotional_state TEXT,
            mistake_tags TEXT, lesson TEXT,
            reactor_state_at_decision TEXT,
            decision_grade_energy_at_decision REAL,
            echo_risk_score_at_decision REAL,
            meltdown_risk_at_decision REAL,
            fusion_validity_at_decision TEXT,
            fission_branch_clarity_at_decision REAL,
            operator_heat_at_decision REAL,
            gallardo_block_at_decision INTEGER,
            preflight_state_at_decision TEXT,
            trade_mode TEXT,
            reconciliation_status TEXT, cancel_reason TEXT,
            cancelled_at TEXT, created_via TEXT,
            currency TEXT, ai_model_used TEXT,
            logged_by TEXT, execution_mode TEXT, ai_execution_count INTEGER,
            advisory_status TEXT, human_review_required INTEGER,
            broker_order_id TEXT, broker_api_called INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


def test_load_position_context_with_injected_db_and_holdings(tmp_path: Path):
    holdings_path = tmp_path / "verified_current_holdings.json"
    holdings_path.write_text(
        json.dumps(
            {
                "run_date": "2026-05-26",
                "positions": [
                    {
                        "ticker": "NASDAQ:NVDA",
                        "normalized_ticker": "NVDA",
                        "status": "OPEN",
                        "quantity": 1.0,
                        "entry_price": 100.0,
                        "currency": "USD",
                        "leverage": 1,
                        "opened_at": "2026-05-20T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "mvp_local.db"
    _make_tmp_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO manual_trades (
            trade_id, event_id, ticker, side, quantity, price,
            executed_at, thesis, notes, leverage,
            invalidation_level, expected_horizon, risk_reason,
            entry_reason, exit_plan, currency, ai_model_used,
            cancelled_at, logged_by, execution_mode,
            ai_execution_count, advisory_status, human_review_required,
            broker_order_id, broker_api_called, trade_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "T1", "E1", "NVDA", "BUY", 1.0, 100.0,
            "2026-05-20T00:00:00Z", "AI thesis", "", 1.0,
            "95", "20 days", "loses 95",
            "breakout", "trim 50% at 130", "USD", "claude-opus",
            "", "human", "HUMAN_ONLY", 0, "ADVISORY_ONLY", 1, "NONE", 0, "REAL_MANUAL",
        ),
    )
    conn.commit()
    conn.close()

    result = load_position_context(
        db_path=db_path,
        holdings_path=holdings_path,
        now_utc=NOW,
    )
    assert result.open_positions_loaded == 1
    ctx = result.contexts[0]
    assert ctx.ticker == "NVDA"
    assert ctx.stop_loss == 95.0
    assert ctx.expected_horizon_days == 20.0
    assert ctx.thesis == "AI thesis"
    assert ctx.source_health == SOURCE_MANUAL_LOG
    assert "COMPLETE" in result.quality_counts or "USABLE" in result.quality_counts


def test_load_position_context_returns_advisory_stamps(tmp_path: Path):
    result = load_position_context(now_utc=NOW)
    # Top-level safety invariants on the result bag.
    assert result.advisory_only is True
    assert result.broker_api_called is False
    assert result.ai_execution_count == 0
    assert result.human_execution_required is True
    assert result.execution_permission == "ADVISORY_ONLY"


def test_classify_position_passes_missing_fields_through_to_row():
    pos = {
        "ticker": "X",
        "buy_price": 100.0,
        "stop_loss": 95.0,
        "tp_price": 130.0,
        # live_price intentionally missing
        "source_health": "LIVE_VERIFIED",
    }
    row = classify_position(pos)
    assert row["exit_status"] == EXIT_DATA_BLOCKED
    assert "live_price" in row.get("missing_fields", [])
