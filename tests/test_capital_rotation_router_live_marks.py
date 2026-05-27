"""Tests — /capital-rotation/* surfaces live_mark_summary."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.api.routers import capital_rotation_router


_SUMMARY_STUB = {
    "generated_at_utc": "2026-05-26T08:00:00Z",
    "source_health": "LIVE_VERIFIED",
    "portfolio_regime": "BUY_ALLOWED",
    "portfolio_capacity_score": 7.6,
    "allowed_new_entries": 3,
    "max_size_per_entry": 100.0,
    "max_total_new_capital": 300.0,
    "leverage_allowed": 1,
    "capacity_components": {
        "S_live": 0.9, "S_recon": 0.8, "S_stop": 0.7, "S_cash": 0.8,
        "S_theme": 0.7, "S_lev": 1.0, "P_dup": 0.0, "P_unreviewed": 0.0,
        "P_dirty": 0.0, "P_tp": 0.0, "P_stop": 0.0,
    },
    "exit_review_board": {
        "rows": [
            {
                "ticker": "GOOGL",
                "exit_status": "HOLD_OK",
                "thesis_status": "THESIS_CONFIRMED",
                "live_price": 382.97,
                "display_live_price": 382.97,
                "mechanical_live_price_usable": True,
                "live_mark_quality_score": 0.91,
                "live_mark_source": "existing_yfinance_provider",
                "live_mark_source_health": "LIVE_VERIFIED",
                "live_mark_age_hours": 0.5,
                "stop_loss": 350.0,
                "tp_price": 420.0,
                "pnl_pct": 0.05,
                "distance_to_stop_pct": 0.085,
                "distance_to_tp_pct": 0.097,
                "reason_codes": ["all_checks_passed"],
                "missing_fields": [],
                "human_action_required": False,
            }
        ],
        "counts": {"HOLD_OK": 1},
        "duplicate_exposures": [],
        "open_position_count": 1,
        "stop_breach_count": 0,
        "phantom_open_count": 0,
        "live_price_missing_count": 0,
        "partial_tp_due_count": 0,
        "runner_exit_review_count": 0,
        "data_blocked_count": 0,
    },
    "theme_slot_summary": {"themes": [], "over_cap_themes": [], "near_cap_themes": []},
    "buy_admission_board": {"rows": [], "counts": {}, "candidate_count": 0},
    "risk_budget": {
        "available_new_risk_budget": 300.0,
        "cash_budget_unknown": False,
        "buffers": {},
        "allowed_new_entries": 3,
        "max_size_per_entry": 100.0,
        "max_total_new_capital": 300.0,
    },
    "exit_review_counts": {"HOLD_OK": 1},
    "buy_admission_counts": {},
    "juego_de_posicion": {"press_intensity": "BUY_ALLOWED"},
    "position_context_status": {
        "open_positions_loaded": 1,
        "quality_counts": {"COMPLETE": 1},
        "source_counts": {"MANUAL_LOG": 1},
        "reason_codes": [],
        "db_available": True,
        "holdings_present": True,
    },
    "candidate_feed_status": {
        "status": "NO_CANDIDATE_FILE",
        "candidate_count": 0,
        "source_files": [],
        "reason_codes": [],
    },
    "live_mark_summary": {
        "generated_at": "2026-05-26T16:00:00Z",
        "aggregate_source_health": "LIVE_VERIFIED",
        "coverage_ratio": 1.0,
        "usable_coverage_ratio": 1.0,
        "average_quality_score": 0.91,
        "requested_tickers": ["GOOGL"],
        "resolved_tickers": ["GOOGL"],
        "missing_tickers": [],
        "stale_tickers": [],
        "provider_status": {"yfinance": {"ok": True}},
        "marks": [{"ticker": "GOOGL"}],
        "reason_codes": ["LIVE_MARK_COVERAGE_FULL"],
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "ADVISORY_ONLY",
    },
    "advisory_only": True,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "human_execution_required": True,
    "execution_permission": "ADVISORY_ONLY",
}


def test_snapshot_includes_live_mark_summary():
    with patch.object(
        capital_rotation_router,
        "build_capital_rotation_summary",
        return_value=_SUMMARY_STUB,
    ):
        payload = capital_rotation_router.get_capital_rotation()
    assert "live_mark_summary" in payload
    assert payload["live_mark_summary"]["aggregate_source_health"] == "LIVE_VERIFIED"
    assert payload["live_mark_summary"]["coverage_ratio"] == 1.0
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["advisory_only"] is True


def test_exit_review_rows_carry_live_mark_metadata():
    with patch.object(
        capital_rotation_router,
        "build_capital_rotation_summary",
        return_value=_SUMMARY_STUB,
    ):
        payload = capital_rotation_router.get_exit_review()
    rows = payload["rows"]
    assert rows[0]["live_mark_source_health"] == "LIVE_VERIFIED"
    assert rows[0]["live_mark_quality_score"] == 0.91
    assert payload["live_mark_summary"]["aggregate_source_health"] == "LIVE_VERIFIED"


def test_no_live_marks_returns_degraded_payload_not_error():
    degraded = dict(_SUMMARY_STUB)
    degraded["live_mark_summary"] = {
        "aggregate_source_health": "NO_LIVE_MARKS",
        "coverage_ratio": 0.0,
        "usable_coverage_ratio": 0.0,
        "average_quality_score": 0.0,
        "requested_tickers": ["GOOGL"],
        "resolved_tickers": [],
        "missing_tickers": ["GOOGL"],
        "stale_tickers": [],
        "provider_status": {},
        "marks": [],
        "reason_codes": ["NO_LIVE_MARKS"],
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_execution_required": True,
        "execution_permission": "ADVISORY_ONLY",
    }
    with patch.object(
        capital_rotation_router,
        "build_capital_rotation_summary",
        return_value=degraded,
    ):
        payload = capital_rotation_router.get_capital_rotation()
    assert payload["live_mark_summary"]["aggregate_source_health"] == "NO_LIVE_MARKS"
    assert payload["live_mark_summary"]["missing_tickers"] == ["GOOGL"]
    assert payload["advisory_only"] is True


def test_no_forbidden_route_segments_added():
    router = capital_rotation_router.build_router()
    paths: list[str] = []
    for _method, path, _fn in getattr(router, "_routes", []) or []:
        paths.append(path)
    forbidden_segments = {
        "orders",
        "order",
        "buy",
        "sell",
        "execute",
        "portfolio",
        "fills",
        "positions",
        "deposit",
        "withdrawal",
        "balance",
        "api_keys",
        "broker",
    }
    for path in paths:
        segments = {seg.lower() for seg in path.split("/") if seg}
        assert not (segments & forbidden_segments), (
            f"forbidden segment(s) in route {path}"
        )


def test_admission_endpoint_includes_live_mark_summary():
    with patch.object(
        capital_rotation_router,
        "build_capital_rotation_summary",
        return_value=_SUMMARY_STUB,
    ):
        payload = capital_rotation_router.get_buy_admission()
    assert "live_mark_summary" in payload
    assert payload["live_mark_summary"]["aggregate_source_health"] == "LIVE_VERIFIED"
