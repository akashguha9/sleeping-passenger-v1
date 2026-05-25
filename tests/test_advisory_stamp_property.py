"""Property test — every safe FastAPI GET route carries the advisory stamps.

Identity Collapse + First-Day Operator sprint, Phase 5.

Goal
----
Walk every route registered on ``scripts.api_server.app``, call the safe GET
routes with no parameters (or with the minimum required path parameters),
and assert the canonical advisory stamps are present in the JSON response.
The expected stamp set is sourced from ``scripts.advisory_contract`` — the
single source of truth.

Hard rules
~~~~~~~~~~
* No external API calls — every backend dependency is patched.
* No broker / execution route is touched (the AST + router-table tests in
  ``tests/test_api_server.py`` already guarantee none exists).
* CSV export routes are skipped: their bodies are CSV, not JSON, and they
  intentionally do not carry the stamps in the body.
* POST routes are skipped — they need bodies and side-effects are out of
  scope for a property test.  ``tests/test_api_server.py`` already asserts
  the stamps on the main mutating routes.

Coverage requirement
~~~~~~~~~~~~~~~~~~~~
``SafetyStampCoverage`` = (routes checked) / (safe routes) — must be ≥ 0.90.
``R_failed`` (routes violating the stamp invariant) must be 0.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.advisory_contract import (
    ADVISORY_STATUS,
    AI_EXECUTION_COUNT,
    EXECUTION_GATE_LOCKED,
)


# Canonical fields we assert when present.  ``advisory_status`` and
# ``execution_gate`` are the primary stamps; ``broker_api_called`` and
# ``ai_execution_count`` are checked when present.  Each safe-GET response
# must carry at minimum ``advisory_status``.
_REQUIRED_KEYS = ("advisory_status",)
_OPTIONAL_BUT_PINNED = (
    "execution_gate",
    "broker_api_called",
    "ai_execution_count",
)


# Routes that intentionally do NOT carry JSON-level stamps.
# Reasons are documented inline.
_SKIPPED_ROUTES: dict[str, str] = {
    # CSV body responses — stamps live in the audit log row, not the CSV body.
    "/exports/signal-inbox.csv": "csv-body",
    "/exports/reflections.csv": "csv-body",
    "/exports/manual-trades.csv": "csv-body",
    "/exports/reconciliation.csv": "csv-body",
    "/exports/moltbook.csv": "csv-body",
    "/exports/source-health.csv": "csv-body",
}


# Path-parameter placeholders for routes that require a path arg.
# Values are deliberately simple so the route handler can resolve and the
# patched persistence layer returns the canned response.
_PATH_PARAM_VALUES: dict[str, str] = {
    "event_id": "TEST_EVT_001",
    "trade_id": "TRADE_TEST_001",
    "symbol": "AAPL",
}


def _resolve_path(path_template: str) -> str | None:
    """Substitute known path parameters; return None for unsupported ones."""
    resolved = path_template
    while "{" in resolved and "}" in resolved:
        start = resolved.index("{")
        end = resolved.index("}", start)
        name = resolved[start + 1 : end]
        if name not in _PATH_PARAM_VALUES:
            return None
        resolved = resolved[:start] + _PATH_PARAM_VALUES[name] + resolved[end + 1 :]
    return resolved


def _advisory_block() -> dict[str, Any]:
    """Canonical advisory block used by every patched stub."""
    return {
        "advisory_status": ADVISORY_STATUS,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": AI_EXECUTION_COUNT,
        "execution_permission": False,
        "can_execute": False,
        "human_review_required": True,
        "broker_order_id": "NONE",
        "execution_mode": "HUMAN_ONLY",
    }


def _canned_inbox() -> dict[str, Any]:
    return {
        **_advisory_block(),
        "operation": "list_inbox_items",
        "item_count": 0,
        "items": [],
        "fabric_bull_state": "UNKNOWN",
        "fabric_stats": {},
        "generated_at": "2026-05-25T00:00:00Z",
    }


def _canned_detail() -> dict[str, Any]:
    return {
        **_advisory_block(),
        "operation": "get_signal_detail",
        "event_id": "TEST_EVT_001",
        "signal": {},
        "ticker_summary": {},
        "reflections": [],
        "ai_summaries": [],
        "manual_trades": [],
        "generated_at": "2026-05-25T00:00:00Z",
    }


def _canned_diag() -> dict[str, Any]:
    return {**_advisory_block(), "diagnostics": {}, "advisory_note": "ok"}


def _canned_moltbook_list() -> dict[str, Any]:
    return {
        **_advisory_block(),
        "operation": "list_moltbook_entries",
        "entry_count": 0,
        "entries": [],
        "generated_at": "2026-05-25T00:00:00Z",
    }


@pytest.fixture(scope="module")
def client_and_routes():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover — env detail
        pytest.skip("fastapi[testclient] not installed")

    # Patches: every backend dependency the GET routes might touch.  We use
    # broad-shape stubs that always include the advisory block.  This is the
    # whole point of the property test — to prove the *route handlers* keep
    # the stamps in the wire response.
    canned = _advisory_block()
    canned_full = {
        **canned,
        "status": "ok",
        "version": "test",
        "items": [],
        "entries": [],
        "summary": {},
        "data": {},
        "rows": [],
    }

    patches = [
        # signal_inbox_api
        patch("scripts.api_server.list_inbox_items", return_value=_canned_inbox()),
        patch("scripts.api_server.get_signal_detail", return_value=_canned_detail()),
        patch("scripts.api_server.get_inbox_diagnostics", return_value=_canned_diag()),
        patch("scripts.api_server.list_manual_trades", return_value={**canned, "manual_trades": [], "trade_count": 0}),
        # moltbook
        patch("scripts.api_server.list_moltbook_entries", return_value=_canned_moltbook_list()),
        # source-health
        patch("scripts.api_server._get_source_health_summary", return_value=canned_full),
        patch("scripts.api_server._get_source_run_log", return_value=[]),
        patch("scripts.api_server._get_live_signals", return_value={**canned, "events": []}),
    ]
    started = []
    for p in patches:
        try:
            p.start()
            started.append(p)
        except (AttributeError, ModuleNotFoundError):
            # If the symbol does not exist, skip; the route either does not
            # depend on it or is in _SKIPPED_ROUTES.
            continue

    import scripts.api_server as srv

    tc = TestClient(srv.app, raise_server_exceptions=False)
    safe_get_routes: list[str] = []
    all_route_paths: list[str] = []
    for r in srv.app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path:
            continue
        all_route_paths.append(path)
        if "GET" not in methods:
            continue
        if path in _SKIPPED_ROUTES:
            continue
        if path.startswith("/openapi") or path.startswith("/docs") or path.startswith("/redoc"):
            continue
        safe_get_routes.append(path)

    yield tc, safe_get_routes, all_route_paths

    for p in started:
        try:
            p.stop()
        except Exception:  # pragma: no cover
            pass


def _is_json(response) -> bool:
    ct = response.headers.get("content-type", "")
    return "application/json" in ct.lower()


def test_safety_stamp_coverage_at_least_90_percent(client_and_routes):
    client, safe_routes, _ = client_and_routes
    if not safe_routes:
        pytest.skip("no safe GET routes registered")

    checked: list[str] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []

    for path in safe_routes:
        resolved = _resolve_path(path)
        if resolved is None:
            skipped.append((path, "unsupported-path-parameter"))
            continue
        try:
            response = client.get(resolved)
        except Exception as exc:  # pragma: no cover — defensive
            skipped.append((path, f"client-error:{type(exc).__name__}"))
            continue

        if response.status_code in (404, 401, 403, 422, 500):
            # 401/403 = token-gated; 404 = no fixture data; 422 = validation
            # against the patched stub returning a non-matching shape; 500 =
            # downstream returned an error.  None of these prove a stamp
            # violation — they only mean we cannot inspect a stamp.  Skip,
            # do not fail.
            skipped.append((path, f"status-{response.status_code}"))
            continue

        if not _is_json(response):
            skipped.append((path, "non-json-body"))
            continue

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            skipped.append((path, "json-decode-error"))
            continue

        # Accept nested payloads — many endpoints carry the stamps inside
        # ``safety`` or the top-level keys.  Flatten one level.
        flat_keys = set(payload.keys()) if isinstance(payload, dict) else set()
        safety_keys = (
            set(payload.get("safety", {}).keys())
            if isinstance(payload, dict) and isinstance(payload.get("safety"), dict)
            else set()
        )
        all_keys = flat_keys | safety_keys

        if not _REQUIRED_KEYS[0] in all_keys:
            failed.append((path, "missing-advisory_status"))
            continue

        # Pull advisory_status from wherever it lives.
        adv = payload.get("advisory_status")
        if adv is None and isinstance(payload.get("safety"), dict):
            adv = payload["safety"].get("advisory_status")
        if adv != ADVISORY_STATUS:
            failed.append((path, f"advisory_status={adv!r}"))
            continue

        # When optional pinned fields are present, they must carry the
        # canonical value.  Absent = OK; wrong value = FAIL.
        wrong: list[str] = []
        if "execution_gate" in flat_keys and payload.get("execution_gate") not in (EXECUTION_GATE_LOCKED, None):
            wrong.append(f"execution_gate={payload.get('execution_gate')!r}")
        if "broker_api_called" in flat_keys and payload.get("broker_api_called") not in (False, None):
            wrong.append(f"broker_api_called={payload.get('broker_api_called')!r}")
        if "ai_execution_count" in flat_keys and payload.get("ai_execution_count") not in (AI_EXECUTION_COUNT, None):
            wrong.append(f"ai_execution_count={payload.get('ai_execution_count')!r}")

        if wrong:
            failed.append((path, ",".join(wrong)))
            continue

        checked.append(path)

    coverage = len(checked) / max(1, len(safe_routes))
    msg = (
        f"checked={len(checked)} skipped={len(skipped)} failed={len(failed)}"
        f" total_safe={len(safe_routes)} coverage={coverage:.3f}\n"
        f"failed_routes={failed}\nskipped_routes={skipped}"
    )
    assert not failed, msg
    assert coverage >= 0.90, msg


def test_zero_forbidden_route_segments_property():
    """Independent guard: walk the live app and confirm no forbidden path
    segment is registered.  Complementary to the AST proof in
    ``tests/test_api_server.py``.
    """
    import scripts.api_server as srv

    forbidden = (
        "/buy",
        "/sell",
        "/order",
        "/execute",
        "/place-order",
        "/submit-order",
        "/broker",
        "/broker-execute",
        "/live-trade",
        "/auto-trade",
    )
    for r in srv.app.routes:
        path = getattr(r, "path", "") or ""
        for seg in forbidden:
            assert seg not in path.lower(), f"forbidden segment in route: {path}"


def test_advisory_contract_constants_are_immutable_truth():
    """Pin the canonical constants — any drift here cascades into every
    safety stamp emitted by the API."""
    from scripts.advisory_contract import (
        ADVISORY_STATUS as A,
        EXECUTION_GATE_LOCKED as E,
        AI_EXECUTION_COUNT as AI,
        BROKER_ORDER_NONE as B,
    )

    assert A == "ADVISORY_ONLY"
    assert E == "LOCKED"
    assert AI == 0
    assert B == "NONE"
