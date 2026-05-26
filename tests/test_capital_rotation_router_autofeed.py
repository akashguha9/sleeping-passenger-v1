"""Tests — /capital-rotation/* endpoints expose autofeed status."""
from __future__ import annotations

import pytest

from scripts.api.routers import capital_rotation_router as router_mod


def test_snapshot_exposes_position_context_status():
    payload = router_mod.get_capital_rotation()
    if "error" in payload:
        pytest.skip("summary unavailable in this environment")
    assert "position_context_status" in payload
    pcs = payload["position_context_status"]
    assert isinstance(pcs, dict)
    assert "open_positions_loaded" in pcs
    assert "quality_counts" in pcs
    assert "source_counts" in pcs


def test_snapshot_exposes_candidate_feed_status():
    payload = router_mod.get_capital_rotation()
    if "error" in payload:
        pytest.skip("summary unavailable in this environment")
    assert "candidate_feed_status" in payload
    cfs = payload["candidate_feed_status"]
    assert isinstance(cfs, dict)
    assert "status" in cfs
    assert "candidate_count" in cfs
    assert "source_files" in cfs
    assert cfs["status"] in {
        "CANDIDATES_LOADED",
        "NO_CANDIDATE_FILE",
        "CANDIDATE_FILE_STALE",
        "CANDIDATE_FILE_INVALID",
        "CANDIDATES_INJECTED",
    }


def test_admission_endpoint_exposes_candidate_feed_status():
    payload = router_mod.get_buy_admission()
    assert payload["report"] == "buy_admission_board"
    assert "candidate_feed_status" in payload
    assert "rows" in payload


def test_exit_review_endpoint_exposes_position_context_status():
    payload = router_mod.get_exit_review()
    assert payload["report"] == "exit_review_board"
    assert "position_context_status" in payload


def test_router_paths_have_no_bare_portfolio_segment():
    """Repo-wide safety: no bare ``portfolio`` segment may appear in
    any registered route path.  Compound forms like
    ``portfolio-truth`` are allowed."""
    router = router_mod.build_router()
    routes = getattr(router, "_routes", None) or getattr(router, "routes", [])
    paths: list[str] = []
    for entry in routes:
        if isinstance(entry, tuple):
            paths.append(entry[1])
        else:
            paths.append(getattr(entry, "path", "") or "")
    for path in paths:
        segments = [seg.lower() for seg in path.split("/") if seg]
        assert "portfolio" not in segments, f"bare portfolio segment in {path}"


def test_all_handlers_carry_safety_stamps():
    for handler in (
        router_mod.get_capital_rotation,
        router_mod.get_exit_review,
        router_mod.get_theme_slots,
        router_mod.get_buy_admission,
    ):
        payload = handler()
        assert payload["advisory_only"] is True
        assert payload["broker_api_called"] is False
        assert payload["ai_execution_count"] == 0
        assert payload["execution_permission"] == "LOCKED"
        assert payload["advisory_status"] == "ADVISORY_ONLY"


def test_no_handler_payload_implies_execution():
    """Forbidden execution tokens must not leak into any handler
    payload — defence in depth on top of the route-segment guard."""
    import json

    for handler in (
        router_mod.get_capital_rotation,
        router_mod.get_exit_review,
        router_mod.get_theme_slots,
        router_mod.get_buy_admission,
    ):
        text = json.dumps(handler(), default=str).lower()
        for forbidden in (
            "place_order",
            "submit_order",
            "execute_trade",
            "broker_execute",
            "auto_execute",
            "auto-trading",
        ):
            assert forbidden not in text, f"{forbidden} in {handler.__name__}"
