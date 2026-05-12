"""
Tests for scripts/signal_inbox_bridge — promote fresh signal_events into
Signal Inbox candidates without touching execution or broker logic.

All tests use injected `get_signal_events` fakes — zero live network, zero
real SQLite hits. The bridge is pure functions; signal_inbox_api integration
is tested with the same DI mechanism plus monkey-patching for the global
fabric path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from scripts.signal_inbox_bridge import (
    DEFAULT_HOURS,
    DEFAULT_LIMIT,
    MAX_HOURS,
    build_inbox_diagnostics,
    promote_signal_events_to_inbox,
)


_NOW = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)


def _row(
    source_name: str,
    payload: dict[str, Any],
    *,
    age_hours: float = 1.0,
    event_id: str | None = None,
    now: datetime = _NOW,
) -> dict[str, Any]:
    ts = (now - timedelta(hours=age_hours)).isoformat()
    return {
        "id": abs(hash((source_name, event_id or "", age_hours))) % 100000,
        "event_id": event_id or f"{source_name}_{int(age_hours * 1000)}",
        "source_name": source_name,
        "raw_payload": payload,
        "fetched_at": ts,
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_gate": "LOCKED",
        "ai_execution_count": 0,
    }


# ---------------------------------------------------------------------------
# Freshness window
# ---------------------------------------------------------------------------


class TestFreshnessWindow:
    def test_old_events_are_excluded(self) -> None:
        rows = [
            _row("market_data", {"symbol": "OLD"}, age_hours=200.0, event_id="old_one"),
            _row("market_data", {"symbol": "NEW"}, age_hours=2.0, event_id="new_one"),
        ]
        items = promote_signal_events_to_inbox(
            hours=72,
            limit=50,
            get_signal_events=lambda **kw: rows,
            now=_NOW,
        )
        event_ids = {it["event_id"] for it in items}
        assert "new_one" in event_ids
        assert "old_one" not in event_ids

    def test_zero_fresh_returns_empty(self) -> None:
        rows = [
            _row("market_data", {"symbol": "OLD"}, age_hours=200.0),
        ]
        items = promote_signal_events_to_inbox(
            hours=24,
            limit=50,
            get_signal_events=lambda **kw: rows,
            now=_NOW,
        )
        assert items == []

    def test_hours_clamped_to_max(self) -> None:
        rows = [
            _row("market_data", {"symbol": "X"}, age_hours=10.0, event_id="x"),
        ]
        items = promote_signal_events_to_inbox(
            hours=99_999,
            limit=10,
            get_signal_events=lambda **kw: rows,
            now=_NOW,
        )
        # Should not raise; clamp prevents huge cutoffs that wrap timestamps.
        assert len(items) == 1

    def test_limit_clamped_and_respected(self) -> None:
        rows = [
            _row("market_data", {"symbol": f"S{i}"}, age_hours=1.0, event_id=f"e{i}")
            for i in range(20)
        ]
        items = promote_signal_events_to_inbox(
            hours=24,
            limit=5,
            get_signal_events=lambda **kw: rows,
            now=_NOW,
        )
        assert len(items) == 5


# ---------------------------------------------------------------------------
# Ticker / display mapping
# ---------------------------------------------------------------------------


class TestTickerMapping:
    def _promote_one(self, source: str, payload: dict[str, Any]) -> dict[str, Any]:
        rows = [_row(source, payload, age_hours=1.0)]
        items = promote_signal_events_to_inbox(
            hours=72,
            limit=10,
            get_signal_events=lambda **kw: rows,
            now=_NOW,
        )
        assert len(items) == 1
        return items[0]

    def test_market_data_uses_symbol(self) -> None:
        item = self._promote_one("market_data", {"symbol": "AAPL", "latest_price": 200})
        assert item["ticker"] == "AAPL"

    def test_polymarket_uses_topic_not_fake_ticker(self) -> None:
        item = self._promote_one(
            "polymarket",
            {"title": "Will inflation be above 3% by Q4?", "market_id": "0xABCD"},
        )
        # Ticker should be the market topic, not a fake stock symbol
        assert "inflation" in item["ticker"].lower()

    def test_grok_xai_uses_interpreted_topic(self) -> None:
        item = self._promote_one(
            "grok_xai",
            {
                "interpreted_topic": "Macro Market Conditions",
                "model_name": "grok-3-mini",
            },
        )
        assert item["ticker"] == "Macro Market Conditions"

    def test_sec_edgar_uses_cik_form(self) -> None:
        item = self._promote_one(
            "sec_edgar",
            {"cik": "0000320193", "form_type": "10-K"},
        )
        assert "CIK0000320193" in item["ticker"]
        assert "10-K" in item["ticker"]

    def test_global_filings_uses_ticker(self) -> None:
        item = self._promote_one(
            "global_filings",
            {"ticker_or_identifier": "BHP", "issuer_name": "BHP Group"},
        )
        assert item["ticker"] == "BHP"

    def test_asia_disclosure_falls_back_to_issuer(self) -> None:
        item = self._promote_one(
            "asia_disclosure",
            {"issuer_name": "Sony Group", "exchange_or_regulator": "TDnet"},
        )
        assert "Sony" in item["ticker"]

    def test_india_uses_index_name(self) -> None:
        item = self._promote_one("india", {"index_name": "NIFTY 50"})
        assert item["ticker"] == "NIFTY 50"

    def test_news_uses_title(self) -> None:
        item = self._promote_one(
            "newsapi", {"title": "Fed holds rates steady", "publisher": "Reuters"}
        )
        assert "Fed" in item["ticker"]

    def test_gdelt_fallback_keeps_fallback_origin_visible(self) -> None:
        item = self._promote_one(
            "gdelt_fallback",
            {"title": "Macro update", "provider_fallback": "newsapi"},
        )
        assert item["source_name"] == "gdelt_fallback"
        assert "Macro" in item["ticker"]

    def test_unknown_source_does_not_blow_up(self) -> None:
        item = self._promote_one("totally_new_source", {})
        # Falls back to source-name shaped placeholder, never empty.
        assert item["ticker"] != ""


# ---------------------------------------------------------------------------
# Scoring + persistence
# ---------------------------------------------------------------------------


class TestScoring:
    def test_market_confirmation_drives_priority(self) -> None:
        rows = [
            _row(
                "market_data",
                {"symbol": "STRONG", "market_confirmation_score": 0.9},
                event_id="strong",
            ),
            _row(
                "market_data",
                {"symbol": "WEAK", "market_confirmation_score": 0.1},
                event_id="weak",
            ),
        ]
        items = promote_signal_events_to_inbox(
            hours=24, limit=10, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        by_t = {it["ticker"]: it for it in items}
        assert by_t["STRONG"]["priority_score"] > by_t["WEAK"]["priority_score"]

    def test_persistence_boosts_with_repeat_ticker(self) -> None:
        rows = [
            _row("market_data", {"symbol": "REPEAT"}, age_hours=1.0, event_id="r1"),
            _row("market_data", {"symbol": "REPEAT"}, age_hours=2.0, event_id="r2"),
            _row("market_data", {"symbol": "REPEAT"}, age_hours=3.0, event_id="r3"),
            _row("market_data", {"symbol": "ONCE"}, age_hours=1.0, event_id="o1"),
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=10, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        by_t: dict[str, list[dict[str, Any]]] = {}
        for it in items:
            by_t.setdefault(it["ticker"], []).append(it)
        # Pick first repeat and the lone one
        repeat = by_t["REPEAT"][0]
        once = by_t["ONCE"][0]
        assert repeat["persistence_score"] > once["persistence_score"]

    def test_kill_and_blocker_default_zero(self) -> None:
        rows = [_row("market_data", {"symbol": "X"})]
        items = promote_signal_events_to_inbox(
            hours=24, limit=10, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert items[0]["kill_rate_score"] == 0.0
        assert items[0]["blocker_pressure_score"] == 0.0


# ---------------------------------------------------------------------------
# Advisory safety invariants
# ---------------------------------------------------------------------------


class TestAdvisoryInvariants:
    def _all_items(self) -> list[dict[str, Any]]:
        rows = [
            _row("market_data", {"symbol": "SPY"}, event_id="m1"),
            _row("polymarket", {"title": "Topic", "market_id": "0xA"}, event_id="p1"),
            _row("grok_xai", {"interpreted_topic": "Macro"}, event_id="g1"),
            _row("sec_edgar", {"cik": "1", "form_type": "10-K"}, event_id="s1"),
        ]
        return promote_signal_events_to_inbox(
            hours=24, limit=10, get_signal_events=lambda **kw: rows, now=_NOW,
        )

    def test_advisory_status_locked_on_every_item(self) -> None:
        for it in self._all_items():
            assert it["advisory_status"] == "ADVISORY_ONLY"

    def test_human_review_required_true(self) -> None:
        for it in self._all_items():
            assert it["human_review_required"] is True

    def test_execution_mode_human_only(self) -> None:
        for it in self._all_items():
            assert it["execution_mode"] == "HUMAN_ONLY"

    def test_ai_execution_count_zero(self) -> None:
        for it in self._all_items():
            assert it["ai_execution_count"] == 0

    def test_no_buy_sell_fields(self) -> None:
        forbidden = {"side", "order_id", "broker_order_id", "trade_id", "fill_price"}
        for it in self._all_items():
            assert forbidden.isdisjoint(it.keys()), (
                f"forbidden execution field surfaced in inbox item: {it.keys() & forbidden}"
            )


# ---------------------------------------------------------------------------
# Overlay merging
# ---------------------------------------------------------------------------


class TestOverlay:
    def test_user_status_overlay_applied(self) -> None:
        rows = [_row("market_data", {"symbol": "X"}, event_id="x_evt")]
        items = promote_signal_events_to_inbox(
            hours=24,
            limit=10,
            overlay={"x_evt": {"user_status": "watchlist"}},
            get_signal_events=lambda **kw: rows,
            now=_NOW,
        )
        assert items[0]["user_status"] == "watchlist"

    def test_user_status_defaults_pending(self) -> None:
        rows = [_row("market_data", {"symbol": "X"}, event_id="x_evt")]
        items = promote_signal_events_to_inbox(
            hours=24, limit=10, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert items[0]["user_status"] == "pending"


# ---------------------------------------------------------------------------
# Diagnostics endpoint
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_diagnostics_counts_source(self) -> None:
        rows = [
            _row("market_data", {"symbol": "A"}, age_hours=1.0),
            _row("market_data", {"symbol": "B"}, age_hours=2.0),
            _row("polymarket", {"title": "Topic"}, age_hours=3.0),
            _row("newsapi", {"title": "Stale"}, age_hours=200.0),
        ]
        diag = build_inbox_diagnostics(
            hours=72, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert diag["signal_events_total"] == 4
        # 3 within 72h window, 1 outside
        assert diag["promoted_candidate_count"] == 3
        assert diag["source_counts"]["market_data"] == 2
        assert diag["source_counts"]["newsapi"] == 1
        assert diag["fresh_source_counts"]["market_data"] == 2
        assert diag["fresh_source_counts"].get("newsapi", 0) == 0
        assert diag["mock_fallback"] is False

    def test_diagnostics_safety_fields(self) -> None:
        diag = build_inbox_diagnostics(
            hours=72, get_signal_events=lambda **kw: [], now=_NOW,
        )
        assert diag["advisory_status"] == "ADVISORY_ONLY"
        assert diag["execution_mode"] == "HUMAN_ONLY"
        assert diag["ai_execution_count"] == 0
        assert diag["human_review_required"] is True

    def test_diagnostics_handles_persistence_runtime_error(self) -> None:
        def boom(*_a, **_kw):
            raise RuntimeError("persistence broken")

        diag = build_inbox_diagnostics(hours=72, get_signal_events=boom, now=_NOW)
        # Must not raise — operators rely on /signals/diagnostics to surface
        # backend errors, not crash the route.
        assert diag["mock_fallback"] is False
        assert diag["promoted_candidate_count"] == 0
        assert diag["signal_events_total"] == 0
        assert "error" in diag


# ---------------------------------------------------------------------------
# signal_inbox_api.list_inbox_items integration with bridge
# ---------------------------------------------------------------------------


class TestListInboxItemsBridge:
    def test_bridge_items_preferred_when_fresh(self) -> None:
        from scripts import signal_inbox_api

        rows = [_row("market_data", {"symbol": "BRIDGE"}, age_hours=1.0)]

        def fake_promote(**kwargs):
            # Use kwargs.get for overlay/limit/hours but pass our rows.
            return [
                {
                    "event_id": "brg_1",
                    "ticker": "BRIDGE",
                    "signal_state": "AVENTADOR",
                    "entry_type": "MARKET_PRICE",
                    "priority_score": 0.7,
                    "observed_at": rows[0]["fetched_at"],
                    "source_file": "market_data",
                    "source_name": "market_data",
                    "rejection_dimensions": [],
                    "rejection_reason": "",
                    "persistence_score": 0.6,
                    "blocker_pressure_score": 0.0,
                    "kill_rate_score": 0.0,
                    "blocker_attribution": "NONE",
                    "user_status": "pending",
                    "has_reflection": False,
                    "has_ai_summary": False,
                    "advisory_status": "ADVISORY_ONLY",
                    "human_review_required": True,
                    "execution_mode": "HUMAN_ONLY",
                    "ai_execution_count": 0,
                    "signal_origin": "live_event",
                    "age_hours": 1.0,
                }
            ]

        with patch.object(signal_inbox_api, "promote_signal_events_to_inbox", fake_promote):
            with patch.object(signal_inbox_api, "_DB_AVAILABLE", True):
                # _persistence is not None — but we don't call into it because
                # the promote mock returns items directly
                with patch.object(signal_inbox_api, "_persistence", object()):
                    result = signal_inbox_api.list_inbox_items(hours=72, limit=50)

        assert result["signal_source"] == "live_events"
        assert result["item_count"] == 1
        assert result["items"][0]["ticker"] == "BRIDGE"
        assert result["mock_fallback"] is False
        # advisory invariants
        assert result["advisory_status"] == "ADVISORY_ONLY"
        assert result["ai_execution_count"] == 0
        assert result["human_review_required"] is True
        assert result["execution_mode"] == "HUMAN_ONLY"

    def test_falls_back_to_legacy_when_bridge_empty(self) -> None:
        from scripts import signal_inbox_api

        with patch.object(
            signal_inbox_api, "promote_signal_events_to_inbox", lambda **kw: []
        ):
            with patch.object(signal_inbox_api, "_DB_AVAILABLE", True):
                with patch.object(signal_inbox_api, "_persistence", object()):
                    result = signal_inbox_api.list_inbox_items(hours=72, limit=50)

        # Legacy fabric path — signal_source should reflect that
        assert result["signal_source"] == "legacy_fabric"
        assert result["mock_fallback"] is False
