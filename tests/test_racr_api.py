"""API-layer tests for the RACR / Kanté Index routes.

Exercises the HTTP surface via TestClient: role contracts, ratings (POST+GET),
contribution events, observation bridge, reliability, and engine validation —
each advisory-only with the no-execution stamps intact.
"""
from __future__ import annotations

import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    os.environ["SIL_ENABLED"] = "1"
    import scripts.api_server as srv
    return TestClient(srv.app)


def _stamps_ok(j: dict) -> bool:
    return (j.get("execution_gate") == "LOCKED"
            and j.get("broker_api_called") in (False, 0)
            and j.get("ai_execution_count") == 0
            and j.get("advisory_status") == "ADVISORY_ONLY")


def test_role_contracts_route(client):
    r = client.get("/api/simulation/role-contracts")
    assert r.status_code == 200
    j = r.json()
    assert j["component_count"] == 18
    assert _stamps_ok(j)


def test_reliability_route(client):
    r = client.get("/api/simulation/reliability")
    assert r.status_code == 200
    j = r.json()
    assert j["all_faults_survived_safely"] is True
    assert _stamps_ok(j)


def test_engine_validation_route(client):
    r = client.get("/api/simulation/engine-validation")
    assert r.status_code == 200
    j = r.json()
    assert j["base_app_runs_without_engines"] is True
    assert j["all_never_real_execution"] is True


def test_observation_bridge_route_fails_closed(client):
    # No OHLCV in the test DB → fail-closed observation (200, ok False).
    r = client.get("/api/simulation/observation/RELIANCE.NS?session_date=2026-07-15")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert _stamps_ok(j)


def test_ratings_post_and_persist(client):
    body = {
        "ticker": "INFY.NS", "market": "IN", "seed": 7,
        "observation": {
            "ticker": "INFY.NS", "market": "IN", "data_cutoff": "2026-07-15",
            "returns": [0.01, -0.02, 0.03, -0.01, 0.02, -0.04, 0.01, 0.0, -0.01, 0.02],
            "volatility": 0.03, "spread_bps": 10, "adv_usd": 4e6, "source_count": 2,
            "narrative_sources": ["a", "b"], "freshness_status": "FRESH"},
    }
    r = client.post("/api/simulation/ratings", json=body)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    fs = j["five_scores"]
    # five distinct scores, empirical firewalled low
    assert fs["empirical_validation"] <= 2.0
    assert fs["role_adjusted_performance"] >= 0.0
    assert _stamps_ok(j)

    # persisted ratings + events are retrievable
    rr = client.get("/api/simulation/ratings").json()
    assert rr["count"] >= 1
    ee = client.get("/api/simulation/contribution-events").json()
    assert ee["count"] >= 1


def test_ratings_disabled_fails_closed(client, monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "0")
    body = {"ticker": "X", "observation": {"ticker": "X", "returns": [0.01, -0.01]}}
    r = client.post("/api/simulation/ratings", json=body)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert _stamps_ok(j)
