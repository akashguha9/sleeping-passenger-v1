"""Tests — live-mark integration with position_context."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.live_price_marks import (
    DELAYED_BUT_USABLE,
    LIVE_VERIFIED,
    STALE_PRICE,
    LiveMark,
    fetch_live_marks,
)
from scripts.portfolio_lifecycle import (
    EXIT_DATA_BLOCKED,
    EXIT_HOLD_OK,
    EXIT_PARTIAL_TP_NOW,
    classify_exit_status,
)
from scripts.position_context import (
    REASON_LIVE_MARK_FROM_YFINANCE,
    REASON_LIVE_MARK_MERGED,
    REASON_LIVE_MARK_MISSING,
    REASON_LIVE_MARK_STALE,
    load_position_context,
    merge_position_context,
    position_context_to_lifecycle_input,
)


NOW = datetime(2026, 5, 26, 16, 0, 0, tzinfo=timezone.utc)


def _holding(**overrides):
    base = {
        "ticker": "NASDAQ:GOOGL",
        "normalized_ticker": "GOOGL",
        "status": "OPEN",
        "quantity": 1.0,
        "entry_price": 350.0,
        "tp_price": 400.0,
        "stop_loss": 330.0,
        "currency": "USD",
        "country": "United States",
        "leverage": 1,
        "opened_at": "2026-05-10T00:00:00Z",
    }
    base.update(overrides)
    return base


def _live_mark(**overrides) -> LiveMark:
    base = LiveMark(
        ticker="GOOGL",
        raw_ticker="NASDAQ:GOOGL",
        provider_symbol="GOOGL",
        live_price=380.0,
        currency="USD",
        provider="existing_yfinance_provider",
        source_health=LIVE_VERIFIED,
        live_mark_quality_score=0.91,
        freshness_score=0.97,
        is_usable=True,
        is_stale=False,
        reason_codes=[REASON_LIVE_MARK_FROM_YFINANCE],
        fetched_at=NOW.isoformat(),
        market_time=NOW.isoformat(),
        age_hours=0.5,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_merge_uses_usable_live_mark_for_mechanical_price():
    ctxs = merge_position_context(
        holdings=[_holding()],
        trade_rows=[],
        live_marks={"GOOGL": _live_mark()},
        now_utc=NOW,
    )
    ctx = ctxs[0]
    assert ctx.live_price == 380.0
    assert ctx.display_live_price == 380.0
    assert ctx.mechanical_live_price_usable is True
    assert ctx.live_mark_quality_score == 0.91
    assert ctx.live_mark_source == "existing_yfinance_provider"
    assert ctx.live_mark_source_health == LIVE_VERIFIED
    assert REASON_LIVE_MARK_MERGED in ctx.reason_codes
    assert REASON_LIVE_MARK_FROM_YFINANCE in ctx.reason_codes


def test_merge_usable_live_mark_prevents_data_blocked():
    ctxs = merge_position_context(
        holdings=[_holding()],
        trade_rows=[],
        live_marks={"GOOGL": _live_mark()},
        now_utc=NOW,
    )
    payload = position_context_to_lifecycle_input(ctxs[0])
    result = classify_exit_status(payload)
    assert result["exit_status"] != EXIT_DATA_BLOCKED
    assert result["exit_status"] == EXIT_HOLD_OK


def test_merge_stale_live_mark_blocks_mechanical_decisions():
    stale = _live_mark(
        is_usable=False,
        is_stale=True,
        live_mark_quality_score=0.45,
        source_health=STALE_PRICE,
        reason_codes=[REASON_LIVE_MARK_STALE],
    )
    ctxs = merge_position_context(
        holdings=[_holding()],
        trade_rows=[],
        live_marks={"GOOGL": stale},
        now_utc=NOW,
    )
    ctx = ctxs[0]
    # Display value still set, mechanical price hidden, reason explains why.
    assert ctx.display_live_price == 380.0
    assert ctx.live_price is None
    assert ctx.mechanical_live_price_usable is False
    assert REASON_LIVE_MARK_STALE in ctx.reason_codes

    payload = position_context_to_lifecycle_input(ctx)
    result = classify_exit_status(payload)
    assert result["exit_status"] == EXIT_DATA_BLOCKED
    assert "live_price" in result["missing_fields"]
    assert any("LIVE_MARK" in code for code in result["reason_codes"])


def test_merge_missing_live_mark_yields_missing_field_and_reason():
    missing = _live_mark(
        live_price=None,
        is_usable=False,
        is_stale=False,
        source_health="NO_LIVE_MARK",
        live_mark_quality_score=0.0,
        reason_codes=[REASON_LIVE_MARK_MISSING],
    )
    ctxs = merge_position_context(
        holdings=[_holding()],
        trade_rows=[],
        live_marks={"GOOGL": missing},
        now_utc=NOW,
    )
    ctx = ctxs[0]
    assert ctx.live_price is None
    assert ctx.display_live_price is None
    assert "live_price" in ctx.missing_fields
    assert REASON_LIVE_MARK_MISSING in ctx.reason_codes


def test_merge_usable_live_mark_pushes_to_partial_tp_now():
    over_tp = _live_mark(live_price=410.0)
    ctxs = merge_position_context(
        holdings=[_holding()],
        trade_rows=[],
        live_marks={"GOOGL": over_tp},
        now_utc=NOW,
    )
    payload = position_context_to_lifecycle_input(ctxs[0])
    result = classify_exit_status(payload)
    assert result["exit_status"] == EXIT_PARTIAL_TP_NOW


def test_live_mark_keyed_by_normalized_ticker_joins_position():
    # The position is NASDAQ:GOOGL; the live mark key should still match
    # via the normalised "GOOGL" key.
    ctxs = merge_position_context(
        holdings=[_holding()],
        trade_rows=[],
        live_marks={"NASDAQ:GOOGL": _live_mark()},
        now_utc=NOW,
    )
    assert ctxs[0].live_price == 380.0


def test_load_position_context_auto_fetches_live_marks(tmp_path: Path):
    holdings_path = tmp_path / "verified_current_holdings.json"
    holdings_path.write_text(
        json.dumps(
            {
                "run_date": "2026-05-26",
                "positions": [
                    {
                        "ticker": "NASDAQ:GOOGL",
                        "normalized_ticker": "GOOGL",
                        "status": "OPEN",
                        "quantity": 1.0,
                        "entry_price": 350.0,
                        "tp_price": 400.0,
                        "stop_loss": 330.0,
                        "currency": "USD",
                        "country": "United States",
                        "leverage": 1,
                        "opened_at": "2026-05-10T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake(symbol: str):
        return {
            "last_price": 382.97,
            "currency": "USD",
            "regular_market_time": NOW.isoformat(),
        }

    result = load_position_context(
        holdings_path=holdings_path,
        db_path=tmp_path / "missing.db",
        live_mark_fetcher=fake,
        allow_network=False,
        now_utc=NOW,
    )
    assert result.live_mark_result is not None
    assert result.live_mark_result.aggregate_source_health in {
        LIVE_VERIFIED,
        DELAYED_BUT_USABLE,
    }
    ctx = result.contexts[0]
    assert ctx.live_price == pytest.approx(382.97)
    assert ctx.mechanical_live_price_usable is True
    assert ctx.live_mark_source == "existing_yfinance_provider"
