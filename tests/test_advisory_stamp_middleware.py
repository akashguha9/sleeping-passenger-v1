"""H2 regression: stamps are a structural guarantee, not handler convention.

Two mechanisms under test:
1. ``AdvisoryStampMiddleware`` — injects any MISSING advisory stamp into
   every outgoing JSON object response; never overwrites handler values;
   never touches non-JSON (CSV exports) responses.
2. ``broker_import_guard`` — raises at startup if a broker SDK is loaded.

The score-moving proof: with the per-handler exception stamps DISABLED
(handlers replaced by vanilla unstamped ones), the full status-code matrix
still carries the stamp block — the middleware alone is the guarantor.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts.advisory_stamp_middleware import (
    ADVISORY_STAMPS,
    inject_missing_stamps,
)
from scripts.broker_import_guard import (
    assert_no_broker_modules,
    detect_broker_modules,
)


def _stamped(body: dict) -> bool:
    return (
        body.get("execution_gate") == "LOCKED"
        and body.get("broker_api_called") is False
        and body.get("ai_execution_count") == 0
        and body.get("advisory_status") == "ADVISORY_ONLY"
    )


# ---------------------------------------------------------------------------
# Pure injection semantics
# ---------------------------------------------------------------------------


def test_inject_adds_missing_stamps():
    out = inject_missing_stamps({"hello": 1})
    assert _stamped(out)
    assert out["hello"] == 1


def test_inject_never_overwrites_handler_values():
    # Handlers are authoritative — even a (hypothetical) conflicting value
    # is preserved, proving the middleware cannot mask a handler's output.
    out = inject_missing_stamps({"execution_gate": "HANDLER_SAYS"})
    assert out["execution_gate"] == "HANDLER_SAYS"
    # ...while the other stamps are still added.
    assert out["broker_api_called"] is False


def test_stamp_constants_are_the_locked_values():
    assert ADVISORY_STAMPS["execution_gate"] == "LOCKED"
    assert ADVISORY_STAMPS["broker_api_called"] is False
    assert ADVISORY_STAMPS["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# On the real app
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    return TestClient(srv.app, raise_server_exceptions=False)


def test_unstamped_route_is_backstopped(client):
    """A route that forgets every stamp still emits the full block."""
    import scripts.api_server as srv

    @srv.app.get("/__test_unstamped__")
    def _unstamped() -> dict:  # pragma: no cover - exercised via client
        return {"hello": "world"}

    try:
        r = client.get("/__test_unstamped__")
        assert r.status_code == 200
        body = r.json()
        assert body["hello"] == "world"
        assert _stamped(body)
    finally:
        srv.app.router.routes[:] = [
            rt
            for rt in srv.app.router.routes
            if getattr(rt, "path", "") != "/__test_unstamped__"
        ]


def test_csv_export_passes_through_untouched(client):
    r = client.get("/exports/manual-trades.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    # CSV is not JSON — middleware must not have mangled it.
    assert not r.text.startswith("{")


def test_matrix_passes_with_handler_stamps_disabled(client, monkeypatch):
    """THE H2 proof: vanilla (unstamped) exception handlers, matrix green."""
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    import scripts.api_server as srv

    async def vanilla_http(request, exc):  # no stamps at all
        detail = exc.detail
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail if isinstance(detail, (str, dict)) else str(detail)},
        )

    async def vanilla_422(request, exc):  # no stamps at all
        return JSONResponse(status_code=422, content={"detail": "invalid"})

    saved = dict(srv.app.exception_handlers)
    saved_stack = srv.app.middleware_stack
    try:
        for key in list(srv.app.exception_handlers):
            if key in (StarletteHTTPException, RequestValidationError):
                srv.app.exception_handlers[key] = (
                    vanilla_http
                    if key is StarletteHTTPException
                    else vanilla_422
                )
        # Force Starlette to rebuild the stack with the vanilla handlers.
        srv.app.middleware_stack = srv.app.build_middleware_stack()

        checks = [
            ("404", client.get("/no-such-route")),
            ("405", client.delete("/manual-trades")),
            (
                "422",
                client.post(
                    "/manual-trades",
                    json={
                        "event_id": "E",
                        "ticker": "X",
                        "side": "BUY",
                        "quantity": "junk",
                        "price": "junk",
                        "thesis": "t",
                    },
                ),
            ),
        ]
        for name, r in checks:
            assert _stamped(r.json()), f"{name} not backstopped by middleware"
    finally:
        srv.app.exception_handlers.clear()
        srv.app.exception_handlers.update(saved)
        srv.app.middleware_stack = saved_stack


def test_500_db_failure_still_stamped_with_middleware(client, monkeypatch):
    import scripts.signal_inbox_api as sia

    def boom(*a, **k):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(sia._persistence, "insert_manual_trade", boom)
    r = client.post(
        "/manual-trades",
        json={
            "event_id": "EVT_H2",
            "ticker": "BTC",
            "side": "BUY",
            "quantity": "1",
            "price": "1",
            "thesis": "t",
        },
    )
    assert r.status_code == 500
    assert _stamped(r.json())


# ---------------------------------------------------------------------------
# Broker import guard
# ---------------------------------------------------------------------------


def test_clean_process_passes_guard():
    assert detect_broker_modules() == []
    assert_no_broker_modules()  # must not raise


def test_fake_ccxt_injection_trips_guard(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "ccxt", types.ModuleType("ccxt"))
    with pytest.raises(RuntimeError) as exc:
        assert_no_broker_modules()
    assert "ccxt" in str(exc.value)
    assert "LOCKED" in str(exc.value)


def test_submodule_of_broker_sdk_trips_guard():
    hits = detect_broker_modules(["ccxt.binance", "json", "os"])
    assert hits == ["ccxt.binance"]


def test_lookalike_names_do_not_trip_guard():
    # 'ccxt_utils' is not the ccxt package; 'scripts.broker_import_guard'
    # contains the word broker but is not an SDK.
    assert detect_broker_modules(
        ["ccxt_utils", "scripts.broker_import_guard", "alpacafarm"]
    ) == []


def test_startup_recheck_trips_on_late_import(monkeypatch):
    """The startup hook re-asserts; simulate via direct call with injection."""
    import sys
    import types

    monkeypatch.setitem(sys.modules, "ib_insync", types.ModuleType("ib_insync"))
    with pytest.raises(RuntimeError):
        assert_no_broker_modules()
