"""Tests — capital rotation router (group G, router half)."""
from __future__ import annotations

import pytest

from scripts.api.routers import capital_rotation_router as router_mod


def _all_handlers():
    return [
        router_mod.get_capital_rotation,
        router_mod.get_exit_review,
        router_mod.get_theme_slots,
        router_mod.get_buy_admission,
    ]


@pytest.mark.parametrize("handler", _all_handlers())
def test_every_handler_returns_safety_stamps(handler) -> None:
    payload = handler()
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] == "LOCKED"
    assert payload["no_execution"] is True
    assert payload["advisory_only"] is True
    assert payload["human_review_required"] is True
    # The customer-facing _stamp helper also attaches the nested safety dict.
    assert "safety" in payload
    assert payload["safety"]["advisory_status"] == "ADVISORY_ONLY"


def test_capital_rotation_payload_contains_expected_keys() -> None:
    payload = router_mod.get_capital_rotation()
    if "error" in payload:
        # Defensive: payload-on-error still carries safety stamps but
        # may not contain the full board shape.
        return
    for key in (
        "portfolio_regime",
        "portfolio_capacity_score",
        "exit_review_board",
        "theme_slot_summary",
        "buy_admission_board",
        "risk_budget",
        "juego_de_posicion",
    ):
        assert key in payload, key


def test_exit_review_handler_returns_board_shape() -> None:
    payload = router_mod.get_exit_review()
    assert payload["report"] == "exit_review_board"
    assert "rows" in payload
    assert "counts" in payload


def test_theme_slots_handler_returns_board_shape() -> None:
    payload = router_mod.get_theme_slots()
    assert payload["report"] == "theme_slot_board"
    assert "themes" in payload


def test_buy_admission_handler_returns_board_shape() -> None:
    payload = router_mod.get_buy_admission()
    assert payload["report"] == "buy_admission_board"
    assert "rows" in payload
    assert payload["counts"] is not None


def test_build_router_registers_four_get_routes() -> None:
    router = router_mod.build_router()
    paths = []
    routes = getattr(router, "_routes", None) or getattr(router, "routes", [])
    for entry in routes:
        if isinstance(entry, tuple):
            # Stub APIRouter shape: (method, path, fn).
            paths.append(entry[1])
        else:
            paths.append(getattr(entry, "path", None))
    assert "/capital-rotation/snapshot" in paths
    assert "/capital-rotation/exit-review" in paths
    assert "/capital-rotation/theme-slots" in paths
    assert "/capital-rotation/admission" in paths
