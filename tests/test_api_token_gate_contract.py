"""Contract test for the MVP_API_TOKEN gate.

This complements ``tests/test_api_token_gate.py`` (behaviour) with a
*structural* guarantee: every mutating route on the FastAPI app must
declare ``require_api_token`` as a dependency.  Without this, a new POST
endpoint can slip through with no guard and only manual review will
catch it.

The check is intentionally simple: walk ``app.routes`` and assert that
each non-GET / non-HEAD / non-OPTIONS route depends on
``require_api_token``.  Read-only routes are not checked.
"""
from __future__ import annotations

import pytest

# Skip the whole module if FastAPI is unavailable so the rest of the suite
# is unaffected.
fastapi = pytest.importorskip("fastapi")


_READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})


def _route_depends_on_token(route) -> bool:
    """Walk a FastAPI route's dependant graph looking for require_api_token."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    seen: set[int] = set()
    queue = [dependant]
    while queue:
        node = queue.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        call = getattr(node, "call", None)
        if call is not None and getattr(call, "__name__", "") == "require_api_token":
            return True
        for child in getattr(node, "dependencies", []) or []:
            queue.append(child)
    return False


def test_every_mutating_route_depends_on_token_gate(monkeypatch):
    """Every non-read route on the API must require_api_token."""
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    import scripts.api_server as srv

    offenders: list[str] = []
    for route in srv.app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        mutating = [m for m in methods if m.upper() not in _READ_METHODS]
        if not mutating:
            continue
        if not _route_depends_on_token(route):
            offenders.append(f"{','.join(sorted(mutating))} {route.path}")

    assert offenders == [], (
        "Mutating routes without require_api_token dependency: "
        + ", ".join(offenders)
    )


def test_health_route_is_read_only_and_open():
    """Sanity check that /health is unguarded (it must be discoverable
    without a token so operators can see api_token_required=True before
    they have a token to send)."""
    import scripts.api_server as srv

    for route in srv.app.routes:
        if getattr(route, "path", None) == "/health":
            methods = {m.upper() for m in getattr(route, "methods", set())}
            assert methods <= _READ_METHODS, "/health must remain read-only"
            assert not _route_depends_on_token(route), (
                "/health must remain open even when MVP_API_TOKEN is set, "
                "so operators can discover api_token_required=True."
            )
            return
    pytest.fail("/health route not found")


def test_no_dangerous_broker_routes_exist():
    """Defence in depth: assert no broker / order / trade-now route exists."""
    import scripts.api_server as srv

    forbidden_fragments = (
        "broker-order",
        "place-order",
        "execute-order",
        "broker_order",
        "place_order",
        "trade-now",
        "auto-trade",
        "live-execute",
    )
    paths = [str(getattr(r, "path", "")) for r in srv.app.routes]
    for path in paths:
        low = path.lower()
        for fragment in forbidden_fragments:
            assert fragment not in low, f"forbidden route present: {path}"
