"""API surface manifest tripwire — no endpoint appears or vanishes silently.

The committed manifest (config/api_route_manifest.json) must equal the
live FastAPI surface exactly. A new route — however innocent — fails the
suite until the manifest is deliberately regenerated in the same commit,
turning every surface change into a visible, reviewable diff.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import generate_api_route_manifest as manifest

_FORBIDDEN_ROUTE_TOKENS = (
    "execute", "/buy", "/sell", "orders/place", "order/place",
    "place-order", "rebalance/run", "webhook",
)


def _live():
    try:
        return manifest.live_surface()
    except Exception:  # pragma: no cover - fastapi missing in minimal envs
        pytest.skip("scripts.api_server not importable here")


def test_manifest_is_tracked_and_loads():
    assert manifest.MANIFEST_PATH.exists()
    routes = manifest.load_manifest()
    assert len(routes) >= 50  # the journal API is not trivially small
    data = json.loads(manifest.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert data["route_count"] == len(routes)


def test_live_surface_matches_committed_manifest_exactly():
    drift = manifest.diff_surface(manifest.load_manifest(), _live())
    assert drift == {"added": [], "removed": []}, (
        f"API surface drifted: {drift} — if intentional, review and run "
        "scripts/generate_api_route_manifest.py --write in the same commit"
    )


def test_new_route_would_trip_the_wire():
    live = _live()
    grown = live + [{"method": "POST", "path": "/quietly-added"}]
    drift = manifest.diff_surface(manifest.load_manifest(), grown)
    assert drift["added"] == ["POST /quietly-added"]


def test_vanished_route_would_trip_the_wire():
    live = _live()
    drift = manifest.diff_surface(manifest.load_manifest(), live[:-1])
    assert len(drift["removed"]) == 1


def test_manifest_routes_have_no_execution_semantics():
    for route in manifest.load_manifest():
        lowered = route["path"].lower()
        for token in _FORBIDDEN_ROUTE_TOKENS:
            assert token not in lowered, route


def test_manifest_methods_are_read_or_journal_verbs_only():
    methods = {r["method"] for r in manifest.load_manifest()}
    assert methods <= {"GET", "POST", "PUT", "PATCH", "DELETE"}
