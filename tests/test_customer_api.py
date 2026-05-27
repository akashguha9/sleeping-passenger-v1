"""Tests for the customer-facing /api/customer/* router.

These exercise the handler functions directly so the suite works in
environments where FastAPI/uvicorn is not installed.  An optional
``TestClient`` block exercises the actual HTTP layer when fastapi is
available.

The customer-facing layer is gated by
``scripts.customer_facing_gate``; this module enables the local-dev
override (``MVP_ENABLE_CUSTOMER_FACING=1``) for the whole test module
so the handlers serve their data.  When the env override is set but
``N_real < 20``, responses carry the ``DEMO_ONLY / UNCALIBRATED`` label
— that label is *not* a forbidden phrase, and is exactly what these
tests are supposed to see when the proof loop has not closed yet.
"""
from __future__ import annotations

import pytest

from scripts.api.routers import customer_router as router_mod
from scripts.customer_facing_gate import ENV_FLAG_NAME
from scripts.customer_language import KNOWN_CUSTOMER_LABELS


@pytest.fixture(autouse=True)
def _enable_customer_facing(monkeypatch):
    """Force the customer-facing env override on for this module."""
    monkeypatch.setenv(ENV_FLAG_NAME, "1")
    yield

FORBIDDEN_API_PHRASES = (
    "buy now",
    "sell now",
    "guaranteed returns",
    "guaranteed return",
    "copy trade",
    "auto trade",
    "auto execute",
    "ai executes",
    "ai decides",
    "profit guaranteed",
    "risk-free",
    "risk free",
    "sure shot",
    "blame the ai",
    "place order",
    "execute order",
    "automatic trade",
)

REQUIRED_SAFETY_KEYS = (
    "advisory_only",
    "human_execution_required",
    "execution_permission",
    "no_execution",
    "disclaimer",
)


def _assert_safety(payload):
    assert payload["advisory_only"] is True
    assert payload["human_execution_required"] is True
    assert payload["execution_permission"] == "LOCKED"
    assert payload["no_execution"] is True
    assert "decision support" in payload["disclaimer"].lower()


def _assert_no_forbidden_phrases(payload):
    import json

    haystack = json.dumps(payload, ensure_ascii=False, default=str).lower()
    for phrase in FORBIDDEN_API_PHRASES:
        assert phrase not in haystack, (
            f"forbidden phrase {phrase!r} found in payload"
        )


def test_baskets_endpoint_returns_safety_stamps_and_seven_baskets():
    payload = router_mod.get_customer_baskets()
    _assert_safety(payload)
    assert "baskets" in payload
    assert len(payload["baskets"]) == 7
    _assert_no_forbidden_phrases(payload)


def test_basket_by_id_returns_one_basket():
    payload = router_mod.get_customer_basket_by_id("defense_sovereignty")
    _assert_safety(payload)
    assert payload["basket"]["basket_id"] == "defense_sovereignty"
    _assert_no_forbidden_phrases(payload)


def test_basket_by_id_404_on_unknown():
    with pytest.raises(Exception) as exc:
        router_mod.get_customer_basket_by_id("not_a_basket")
    # HTTPException either from fastapi or our stand-in.
    assert getattr(exc.value, "status_code", None) == 404


def test_model_portfolio_endpoint_returns_full_payload():
    payload = router_mod.get_customer_model_portfolio()
    _assert_safety(payload)
    mp = payload["model_portfolio"]
    assert mp["total_target_weight"] == 100
    assert mp["execution_permission"] == "LOCKED"
    assert mp["no_execution"] is True
    assert payload["summary"]["basket_count"] == 7
    table = payload["translation_table"]
    assert len(table) == 7
    _assert_no_forbidden_phrases(payload)


@pytest.mark.parametrize(
    "state, expected_label",
    [
        ("MIURA", "Watch"),
        ("aventador", "Enter/Add"),
        ("DIABLO", "Avoid/Exit Risk"),
        ("UNKNOWN", "Review"),
        ("", "Review"),
    ],
)
def test_translate_state_endpoint(state, expected_label):
    payload = router_mod.get_customer_translate_state(state)
    _assert_safety(payload)
    assert payload["translation"]["customer_label"] == expected_label
    assert payload["translation"]["customer_label"] in KNOWN_CUSTOMER_LABELS
    _assert_no_forbidden_phrases(payload)


@pytest.mark.parametrize(
    "ticker, expected_basket_id",
    [
        ("RHM.DE", "defense_sovereignty"),
        ("VALE", "commodity_repricing"),
        ("ZIM", "shipping_dislocation"),
        ("NVDA", "ai_infrastructure"),
        ("XOM", "energy_shock"),
        ("NSE:BHARTIARTL", "india_domestic_compounding"),
        ("CASH", "cash_risk_off"),
    ],
)
def test_ticker_basket_endpoint_known(ticker, expected_basket_id):
    payload = router_mod.get_customer_ticker_basket(ticker)
    _assert_safety(payload)
    assert payload["basket_id"] == expected_basket_id
    assert payload["ticker"] == ticker.upper()
    _assert_no_forbidden_phrases(payload)


def test_ticker_basket_endpoint_unknown_is_graceful():
    payload = router_mod.get_customer_ticker_basket("XYZNOMAP")
    _assert_safety(payload)
    assert payload["basket_id"] == "unclassified_research_required"
    _assert_no_forbidden_phrases(payload)


def test_router_does_not_define_broker_routes():
    """No /api/customer route may match a broker/order/execute pattern."""
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    router = router_mod.build_router()
    forbidden = ("broker", "order", "execute", "buy", "sell", "place")
    for route in router.routes:
        path = getattr(route, "path", "")
        for token in forbidden:
            assert token not in path.lower(), (
                f"customer router exposes forbidden route token {token!r}: {path}"
            )


def test_router_routes_are_all_GET():
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    router = router_mod.build_router()
    for route in router.routes:
        methods = getattr(route, "methods", set()) or set()
        assert methods <= {"GET", "HEAD"}, (
            f"customer route {route.path} declares non-GET methods: {methods}"
        )


def test_http_layer_returns_safety_stamps_via_testclient():
    """Optional smoke test using the real FastAPI TestClient."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router_mod.build_router())
    client = TestClient(app)

    for path in (
        "/api/customer/baskets",
        "/api/customer/model-portfolio",
        "/api/customer/translate-state/MIURA",
        "/api/customer/ticker/RHM.DE/basket",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        body = resp.json()
        _assert_safety(body)
        _assert_no_forbidden_phrases(body)
