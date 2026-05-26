"""Router extraction Phase 2 — wiring + compatibility tests.

Calibration Corpus + Hosted Canary sprint, Phase 3.

What this verifies
------------------
* The new router modules import cleanly.
* Each new router exposes ``build_router`` and the route handlers
  needed by ``scripts.api_server``.
* ``scripts.api_server`` re-exports the helpers that legacy tests
  import or patch:
    - ``_build_live_sources_status``
    - ``_get_live_signals``
    - ``_get_source_health_summary``
    - ``_get_source_run_log``
    - ``_build_watchdog_summary_response``
* The FastAPI app exposes the same URL paths after extraction.
* No forbidden execution/broker route segments appear.
* ``api_server.py`` is materially smaller than the prior sprint
  baseline (2643 lines) and meets this sprint's ≤2100-line target.
* Router coverage (R_router / R_all) is ≥ 0.50.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_SERVER_PATH = _REPO_ROOT / "scripts" / "api_server.py"


# ---------------------------------------------------------------------------
# Router modules exist and import cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.api.routers.live_sources_router",
        "scripts.api.routers.live_signals_router",
        "scripts.api.routers.source_health_router",
        # Already extracted in prior sprints — re-checked here so this
        # test guards the full router surface.
        "scripts.api.routers.readiness_router",
        "scripts.api.routers.chart_structure_router",
        "scripts.api.routers.exports_router",
        "scripts.api.routers.securities_router",
    ],
)
def test_router_module_imports(module_name: str):
    module = importlib.import_module(module_name)
    assert hasattr(module, "build_router"), f"{module_name} missing build_router"


def test_live_sources_router_builds_with_status_route():
    from scripts.api.routers import live_sources_router as mod

    router = mod.build_router()
    paths = {route.path for route in getattr(router, "routes", [])}
    assert "/live-sources/status" in paths


def test_live_signals_router_builds_with_live_signals_route():
    from scripts.api.routers import live_signals_router as mod

    router = mod.build_router()
    paths = {route.path for route in getattr(router, "routes", [])}
    assert "/live-signals" in paths


def test_source_health_router_builds_with_all_routes():
    from scripts.api.routers import source_health_router as mod

    router = mod.build_router()
    paths = {route.path for route in getattr(router, "routes", [])}
    for expected in ("/source-health", "/source-health/summary", "/source-health/watchdog"):
        assert expected in paths, f"missing {expected}"


# ---------------------------------------------------------------------------
# api_server re-exports preserve the patch surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol",
    [
        "_build_live_sources_status",
        "_get_live_signals",
        "_get_source_health_summary",
        "_get_source_run_log",
        "_build_watchdog_summary_response",
        "_watchdog_summary_path",
        "_watchdog_safety_payload",
        "_log_source_health",
        # Route handler functions — legacy tests grep for them.
        "get_live_sources_status",
        "get_live_signals",
        "get_source_health",
        "get_source_health_summary",
        "get_source_health_watchdog",
    ],
)
def test_api_server_re_exports_symbol(symbol: str):
    import scripts.api_server as srv

    assert hasattr(srv, symbol), f"scripts.api_server missing re-exported symbol: {symbol}"


def test_legacy_path_patched_symbol_is_used_at_request_time(monkeypatch):
    """Patching ``scripts.api_server._build_live_sources_status`` MUST
    bite when the HTTP route fires, because the route handler resolves
    the helper via ``scripts.api_server`` at request time.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    sentinel = {
        "operation": "get_live_sources_status",
        "sources": {},
        "source_count": 0,
        "sentinel": True,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }

    def _fake_builder(**_kwargs):
        return sentinel

    monkeypatch.setattr(srv, "_build_live_sources_status", _fake_builder)

    tc = TestClient(srv.app, raise_server_exceptions=False)
    resp = tc.get("/live-sources/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("sentinel") is True


# ---------------------------------------------------------------------------
# FastAPI app — full route surface after extraction
# ---------------------------------------------------------------------------


def _app_routes() -> set[str]:
    import scripts.api_server as srv

    paths: set[str] = set()
    for route in srv.app.routes:
        p = getattr(route, "path", None)
        if p:
            paths.add(p)
    return paths


@pytest.mark.parametrize(
    "path",
    [
        "/live-sources/status",
        "/live-signals",
        "/source-health",
        "/source-health/summary",
        "/source-health/watchdog",
    ],
)
def test_extracted_routes_still_registered(path: str):
    assert path in _app_routes(), f"route disappeared after extraction: {path}"


def test_no_forbidden_route_segments():
    """Forbidden execution / broker segments must not be added by router
    extraction.  Compared on PATH SEGMENTS (split on '/') so benign
    advisory paths like ``/api/portfolio-truth`` (segment
    ``portfolio-truth``) are not falsely flagged.
    """
    forbidden = {
        "orders", "order", "buy", "sell", "execute",
        "portfolio", "fills", "positions", "deposit",
        "withdrawal", "balance", "api_keys", "broker",
    }
    paths = _app_routes()
    for path in paths:
        segments = {seg.lower() for seg in path.split("/") if seg}
        bad = segments & forbidden
        assert not bad, f"forbidden route segment(s) {bad} in {path}"


# ---------------------------------------------------------------------------
# Mathematical sprint metrics
# ---------------------------------------------------------------------------


def test_api_server_line_count_within_sprint_target():
    """The Calibration Corpus sprint target is L_api_final ≤ 2100.

    The prior sprint reported 2643 lines after the Identity Collapse
    extraction.  This test pins the reduction.
    """
    line_count = sum(1 for _ in _API_SERVER_PATH.read_text(encoding="utf-8").splitlines())
    assert line_count <= 2100, (
        f"api_server.py is {line_count} lines; sprint target ≤2100"
    )


def test_router_coverage_meets_threshold():
    """RouterCoverage = R_router / R_all ≥ 0.50."""
    pytest.importorskip("fastapi")
    from fastapi.routing import APIRoute

    import scripts.api_server as srv

    r_all = 0
    r_router = 0
    inline_endpoint_names = set()
    inline_route_names: set[str] = set()
    api_server_text = _API_SERVER_PATH.read_text(encoding="utf-8")
    # Find all functions still decorated with @app.get / @app.post / etc.
    import re

    for match in re.finditer(
        r"^@app\.(?:get|post|put|delete|patch)\([^)]*\)\s*\n(?:def|async def)\s+(\w+)",
        api_server_text,
        re.MULTILINE,
    ):
        inline_endpoint_names.add(match.group(1))

    for route in srv.app.routes:
        if not isinstance(route, APIRoute):
            continue
        # Ignore FastAPI's docs/openapi internal routes.
        if route.path.startswith(("/openapi", "/docs", "/redoc")):
            continue
        r_all += 1
        endpoint_name = getattr(route.endpoint, "__name__", "")
        if endpoint_name in inline_endpoint_names:
            inline_route_names.add(route.path)
        else:
            r_router += 1

    assert r_all > 0
    coverage = r_router / r_all
    assert coverage >= 0.50, (
        f"router coverage {coverage:.2f} < 0.50; inline routes still: "
        f"{sorted(inline_route_names)}"
    )
