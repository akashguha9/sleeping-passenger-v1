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
    classify_next_human_action,
    compute_action_counts,
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


# ---------------------------------------------------------------------------
# Deterministic deduplication / aggregation
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_50_market_data_rows_for_one_symbol_collapse_to_one_card(self) -> None:
        rows = [
            _row(
                "market_data",
                {"symbol": "TMCV.NS", "close": 100 + i, "market_confirmation_score": 0.6},
                age_hours=1.0 + i * 0.01,
                event_id=f"tmcv_{i}",
            )
            for i in range(50)
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 1
        only = items[0]
        assert only["ticker"] == "TMCV.NS"
        assert only["event_count"] == 50
        assert only["duplicate_suppressed_count"] == 49
        # Representative should be one of the original event_ids.
        assert only["representative_event_id"].startswith("tmcv_")
        # Promotion reason explains why one card.
        assert "50" in only["promotion_reason"]

    def test_two_different_symbols_become_two_candidates(self) -> None:
        rows = [
            _row("market_data", {"symbol": "AAA"}, age_hours=1.0, event_id="a"),
            _row("market_data", {"symbol": "AAA"}, age_hours=2.0, event_id="a2"),
            _row("market_data", {"symbol": "BBB"}, age_hours=1.0, event_id="b"),
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        tickers = sorted(it["ticker"] for it in items)
        assert tickers == ["AAA", "BBB"]
        # AAA has 2 events, BBB has 1.
        by_t = {it["ticker"]: it for it in items}
        assert by_t["AAA"]["event_count"] == 2
        assert by_t["BBB"]["event_count"] == 1

    def test_news_repeated_title_aggregates(self) -> None:
        rows = [
            _row(
                "newsapi",
                {"title": "Fed holds rates steady", "publisher": "Reuters"},
                age_hours=float(i) + 1.0,
                event_id=f"n{i}",
            )
            for i in range(6)
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 1
        assert items[0]["event_count"] == 6
        assert items[0]["duplicate_suppressed_count"] == 5

    def test_event_registry_repeated_news_aggregates(self) -> None:
        rows = [
            _row(
                "event_registry",
                {"title": "Inflation print surprises to the upside"},
                age_hours=float(i) + 1.0,
                event_id=f"er{i}",
            )
            for i in range(4)
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 1
        assert items[0]["event_count"] == 4

    def test_polymarket_grouped_by_market_id(self) -> None:
        rows = [
            _row(
                "polymarket",
                {"title": "Topic A", "market_id": "0xAA", "volume": 100_000},
                age_hours=1.0,
                event_id="pm1",
            ),
            _row(
                "polymarket",
                {"title": "Topic A (updated)", "market_id": "0xAA", "volume": 100_000},
                age_hours=2.0,
                event_id="pm2",
            ),
            _row(
                "polymarket",
                {"title": "Topic B", "market_id": "0xBB", "volume": 50_000},
                age_hours=1.5,
                event_id="pm3",
            ),
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 2

    def test_etherscan_grouped_by_address(self) -> None:
        addr = "0xabcdef0123456789abcdef0123456789abcdef01"
        rows = [
            _row(
                "etherscan",
                {"to_address": addr, "from_address": "0xother", "value_wei": str(i)},
                age_hours=1.0 + i * 0.05,
                event_id=f"tx{i}",
            )
            for i in range(8)
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 1
        assert items[0]["event_count"] == 8

    def test_grok_grouped_by_interpreted_topic(self) -> None:
        rows = [
            _row(
                "grok_xai",
                {"interpreted_topic": "Macro Conditions", "confidence_score": 0.7},
                age_hours=1.0,
                event_id="g1",
            ),
            _row(
                "grok_xai",
                {"interpreted_topic": "Macro Conditions", "confidence_score": 0.65},
                age_hours=4.0,
                event_id="g2",
            ),
            _row(
                "grok_xai",
                {"interpreted_topic": "Geopolitical Tensions", "confidence_score": 0.55},
                age_hours=2.0,
                event_id="g3",
            ),
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 2

    def test_sec_edgar_grouped_by_cik_form(self) -> None:
        rows = [
            _row(
                "sec_edgar",
                {"cik": "0000320193", "form_type": "10-K"},
                age_hours=1.0,
                event_id="s1",
            ),
            _row(
                "sec_edgar",
                {"cik": "0000320193", "form_type": "10-K"},
                age_hours=2.0,
                event_id="s2",
            ),
            _row(
                "sec_edgar",
                {"cik": "0000320193", "form_type": "10-Q"},
                age_hours=2.0,
                event_id="s3",
            ),
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        # 2 unique (cik, form) groups
        assert len(items) == 2

    def test_dedup_preserves_safety_invariants(self) -> None:
        rows = [
            _row("market_data", {"symbol": "DUP"}, age_hours=float(i) + 1.0, event_id=f"d{i}")
            for i in range(10)
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 1
        only = items[0]
        assert only["advisory_status"] == "ADVISORY_ONLY"
        assert only["human_review_required"] is True
        assert only["execution_mode"] == "HUMAN_ONLY"
        assert only["execution_gate"] == "LOCKED"
        assert only["ai_execution_count"] == 0
        assert only["broker_api_called"] is False

    def test_first_and_last_observed_at_span_group(self) -> None:
        rows = [
            _row("market_data", {"symbol": "SPAN"}, age_hours=1.0, event_id="newest"),
            _row("market_data", {"symbol": "SPAN"}, age_hours=24.0, event_id="oldest"),
            _row("market_data", {"symbol": "SPAN"}, age_hours=10.0, event_id="middle"),
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        assert len(items) == 1
        only = items[0]
        # last_observed_at corresponds to the newest event (1h ago), first to oldest (24h ago).
        assert only["last_observed_at"] > only["first_observed_at"]
        assert only["representative_event_id"] == "newest"

    def test_cross_source_support_counted_when_same_ticker_via_two_sources(self) -> None:
        # market_data + global_filings both surface symbol "BHP" → cross_source_support = 2.
        rows = [
            _row("market_data", {"symbol": "BHP"}, age_hours=1.0, event_id="md_bhp"),
            _row(
                "global_filings",
                {"ticker_or_identifier": "BHP", "issuer_name": "BHP Group"},
                age_hours=2.0,
                event_id="gf_bhp",
            ),
            _row("market_data", {"symbol": "ALONE"}, age_hours=1.0, event_id="md_alone"),
        ]
        items = promote_signal_events_to_inbox(
            hours=72, limit=100, get_signal_events=lambda **kw: rows, now=_NOW,
        )
        by_t = {it["ticker"]: it for it in items}
        assert by_t["BHP"]["cross_source_support_count"] == 2
        assert by_t["ALONE"]["cross_source_support_count"] == 1


# ---------------------------------------------------------------------------
# classify_next_human_action — Python mirror of the frontend rules
# ---------------------------------------------------------------------------


def _candidate(**over: Any) -> dict[str, Any]:
    base = {
        "event_id": "x",
        "ticker": "X",
        "signal_state": "AVENTADOR",
        "entry_type": "MARKET_PRICE",
        "priority_score": 0.5,
        "persistence_score": 0.5,
        "kill_rate_score": 0.0,
        "blocker_pressure_score": 0.0,
        "rejection_dimensions": [],
        "user_status": "pending",
        "has_reflection": False,
        "has_ai_summary": False,
        "age_hours": 2.0,
        "source_name": "market_data",
        "source_file": "market_data",
        "event_count": 1,
        "cross_source_support_count": 1,
    }
    base.update(over)
    return base


class TestActionClassifier:
    def test_rejected_is_ignore(self) -> None:
        assert classify_next_human_action(_candidate(user_status="rejected")) == "IGNORE"

    def test_diablo_is_ignore(self) -> None:
        assert classify_next_human_action(_candidate(signal_state="DIABLO")) == "IGNORE"

    def test_high_kill_rate_is_ignore(self) -> None:
        assert classify_next_human_action(_candidate(kill_rate_score=0.9)) == "IGNORE"

    def test_high_blocker_is_ignore(self) -> None:
        assert (
            classify_next_human_action(_candidate(blocker_pressure_score=0.9)) == "IGNORE"
        )

    def test_stale_is_ignore(self) -> None:
        assert classify_next_human_action(_candidate(age_hours=200.0)) == "IGNORE"

    def test_unknown_source_is_ignore(self) -> None:
        cand = _candidate(source_name="placeholder", source_file="placeholder")
        assert classify_next_human_action(cand) == "IGNORE"

    def test_missing_ticker_is_ignore(self) -> None:
        assert classify_next_human_action(_candidate(ticker="")) == "IGNORE"

    def test_weak_candidate_is_have_a_look(self) -> None:
        cand = _candidate(priority_score=0.40, persistence_score=0.30)
        assert classify_next_human_action(cand) == "HAVE_A_LOOK"

    def test_moderate_candidate_is_watchlist(self) -> None:
        cand = _candidate(priority_score=0.60, persistence_score=0.50)
        assert classify_next_human_action(cand) == "WATCHLIST"

    def test_strong_candidate_is_human_review(self) -> None:
        cand = _candidate(
            priority_score=0.78, persistence_score=0.60, age_hours=1.0,
        )
        assert classify_next_human_action(cand) == "HUMAN_REVIEW"

    def test_very_strong_with_cross_source_is_manual_review_candidate(self) -> None:
        cand = _candidate(
            priority_score=0.90,
            persistence_score=0.80,
            kill_rate_score=0.0,
            blocker_pressure_score=0.0,
            cross_source_support_count=2,
            age_hours=1.0,
        )
        assert classify_next_human_action(cand) == "MANUAL_REVIEW_CANDIDATE"

    def test_very_strong_with_event_count_is_manual_review_candidate(self) -> None:
        cand = _candidate(
            priority_score=0.90,
            persistence_score=0.80,
            event_count=5,
            age_hours=1.0,
        )
        assert classify_next_human_action(cand) == "MANUAL_REVIEW_CANDIDATE"


class TestActionCounts:
    def test_compute_action_counts_distributes_across_buckets(self) -> None:
        items = [
            _candidate(user_status="rejected"),  # IGNORE
            _candidate(priority_score=0.40, persistence_score=0.30),  # HAVE_A_LOOK
            _candidate(priority_score=0.60, persistence_score=0.50),  # WATCHLIST
            _candidate(
                priority_score=0.78, persistence_score=0.60, age_hours=1.0,
            ),  # HUMAN_REVIEW
            _candidate(
                priority_score=0.90,
                persistence_score=0.80,
                cross_source_support_count=2,
                age_hours=1.0,
            ),  # MANUAL_REVIEW_CANDIDATE
        ]
        counts = compute_action_counts(items)
        assert counts["ignore"] >= 1
        assert counts["have_a_look"] >= 1
        assert counts["watchlist"] >= 1
        assert counts["human_review"] >= 1
        assert counts["manual_review_candidate"] >= 1


# ---------------------------------------------------------------------------
# list_inbox_items exposes action_counts derived from deduplicated items
# ---------------------------------------------------------------------------


class TestListInboxItemsActionCounts:
    def test_action_counts_exposed_on_response(self) -> None:
        from scripts import signal_inbox_api

        fake_items = [
            _candidate(user_status="rejected"),
            _candidate(priority_score=0.45, persistence_score=0.30),
            _candidate(priority_score=0.65, persistence_score=0.50),
        ]

        with patch.object(
            signal_inbox_api, "promote_signal_events_to_inbox", lambda **kw: fake_items
        ):
            with patch.object(signal_inbox_api, "_DB_AVAILABLE", True):
                with patch.object(signal_inbox_api, "_persistence", object()):
                    result = signal_inbox_api.list_inbox_items(hours=72, limit=50)

        assert "action_counts" in result
        assert result["action_counts"]["ignore"] >= 1
        assert result["action_counts"]["have_a_look"] >= 1
        assert result["action_counts"]["watchlist"] >= 1
