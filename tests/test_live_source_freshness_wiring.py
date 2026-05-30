"""Phase 5 — source freshness contract drives live source health + gating.

Proves the canonical-truth route separates provider API health from canonical
fresh rows (OK + 0 rows => ZERO_FRESH_ROWS, never LIVE), that backfill/mock are
never live, and that a stale/zero-fresh source blocks promotion in the live
decision path while a fresh source lets the gate continue.
"""
from __future__ import annotations

from scripts.api.routers.source_health_router import build_canonical_source_truth
from scripts.live_decision_path import run_live_decision_path

_NOW = "2026-05-31T12:00:00Z"


def _row(**overrides):
    base = dict(
        source="yfinance",
        status="OK",
        rows_added=5,
        rows_filtered=0,
        created_at="2026-05-31T11:00:00Z",  # 1h old
    )
    base.update(overrides)
    return base


def test_source_health_route_separates_api_health_from_canonical_status():
    out = build_canonical_source_truth([_row()], now_iso=_NOW)
    s = out["sources"][0]
    assert s["api_health_status"] == "OK"
    assert s["canonical_signal_status"] == "LIVE_CANONICAL"
    assert s["is_live_canonical"] is True
    # All the requested separated fields are present.
    for key in (
        "api_health_status", "canonical_signal_status", "rows_added",
        "latest_canonical_signal_timestamp", "canonical_age_hours",
        "is_live_canonical", "source_truth_score",
    ):
        assert key in s


def test_ok_api_zero_rows_surfaces_zero_fresh_rows_in_live_route():
    out = build_canonical_source_truth([_row(rows_added=0)], now_iso=_NOW)
    s = out["sources"][0]
    assert s["api_health_status"] == "OK"
    assert s["canonical_signal_status"] == "ZERO_FRESH_ROWS"
    assert s["is_live_canonical"] is False
    assert s["source_truth_score"] == 0.0


def test_backfill_only_source_not_live_canonical_in_live_route():
    out = build_canonical_source_truth(
        [_row(backfill_only=True)], now_iso=_NOW
    )
    s = out["sources"][0]
    assert s["canonical_signal_status"] == "BACKFILL_NON_FRESH"
    assert s["is_live_canonical"] is False


def test_mock_source_not_live_canonical_in_live_route():
    out = build_canonical_source_truth([_row(mock_flag=True)], now_iso=_NOW)
    s = out["sources"][0]
    assert s["canonical_signal_status"] == "MOCK_NON_CANONICAL"
    assert s["is_live_canonical"] is False


def test_stale_canonical_timestamp_blocks_decision_promotion():
    # A source older than its TTL has C_s == 0, so the admission gate's
    # freshness check fails and the candidate cannot be promoted.
    out = run_live_decision_path(
        signal_id="S_STALE",
        axes={"EMS": 0.7, "EQS": 0.7, "DS": 0.7, "LS": 0.7, "EFS": 0.7, "APS": 0.7},
        ticker="X", country="India",
        api_health_status="OK", rows_added=5, canonical_age_hours=100.0, ttl_hours=24.0,
        state="HURACAN", capital=1_000_000.0, cash_available=500_000.0,
        entry_price=100.0, hard_stop_price=95.0, db_path=None,
    )
    assert out["is_live_canonical"] is False
    assert out["source_truth"]["canonical_signal_status"] == "STALE"
    assert out["final_advisory_class"] == "BLOCKED_BY_FRESHNESS"


def test_fresh_canonical_rows_allow_gate_to_continue():
    out = run_live_decision_path(
        signal_id="S_FRESH",
        axes={"EMS": 0.7, "EQS": 0.7, "DS": 0.7, "LS": 0.7, "EFS": 0.7, "APS": 0.7},
        ticker="X", country="India",
        api_health_status="OK", rows_added=5, canonical_age_hours=1.0, ttl_hours=24.0,
        state="HURACAN", capital=1_000_000.0, cash_available=500_000.0,
        entry_price=100.0, hard_stop_price=95.0, db_path=None,
    )
    assert out["is_live_canonical"] is True
    assert out["final_advisory_class"] != "BLOCKED_BY_FRESHNESS"


def test_source_truth_score_visible_in_advisory_metadata():
    out = run_live_decision_path(
        signal_id="S_SCORE",
        axes={"EMS": 0.7, "EQS": 0.7, "DS": 0.7, "LS": 0.7, "EFS": 0.7, "APS": 0.7},
        ticker="X", country="India",
        api_health_status="OK", rows_added=5, canonical_age_hours=1.0,
        state="HURACAN", capital=1_000_000.0, cash_available=500_000.0,
        entry_price=100.0, hard_stop_price=95.0, db_path=None,
    )
    assert "source_truth_score" in out
    assert out["source_truth"]["source_truth_score"] == out["source_truth_score"]


def test_canonical_truth_route_carries_safety_stamps():
    out = build_canonical_source_truth([_row()], now_iso=_NOW)
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
