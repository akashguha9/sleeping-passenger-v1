"""API-layer tests for the Eureka closed-loop intelligence routes."""
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


_CANDS = [
    {"ticker": "RELIANCE.NS", "market": "IN", "data_cutoff": "2026-06-01", "price": 100,
     "prev_close": 99, "returns": [0.01, -0.02, 0.015, -0.01, 0.02, -0.03, 0.01, 0.0, -0.012, 0.02],
     "volatility": 0.025, "adv_usd": 5e7, "spread_bps": 8, "source_count": 3,
     "narrative_sources": ["a", "b", "c"], "freshness_status": "FRESH"},
    {"ticker": "JUNK", "data_cutoff": "2026-06-01", "source_count": 0, "freshness_status": "UNKNOWN"},
]


def test_daily_shadow_run_and_persistence(client):
    r = client.post("/api/intelligence/daily-shadow-run",
                    json={"session_date": "2026-06-01", "seed": 1, "candidates": _CANDS})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["rejected_cheaply"] >= 1
    assert j["twins_created"] >= 1
    assert j["predictions_frozen"] >= 1
    assert j["human_action_required"] is False
    assert _stamps_ok(j)

    twins = client.get("/api/intelligence/twins").json()
    assert twins["count"] >= 1
    tid = twins["twins"][0]["twin_id"]
    detail = client.get(f"/api/intelligence/twins/{tid}")
    assert detail.status_code == 200
    assert detail.json()["immutability_hash"]

    tl = client.get(f"/api/intelligence/twins/{tid}/timeline")
    assert tl.status_code == 200


def test_outcome_queue_and_eureka_health(client):
    # Register some twins first.
    client.post("/api/intelligence/daily-shadow-run",
                json={"session_date": "2026-06-01", "seed": 2, "candidates": _CANDS})
    oq = client.get("/api/intelligence/outcome-queue?session_date=2026-07-15").json()
    assert oq["due_count"] >= 1
    assert _stamps_ok(oq)

    eh = client.get("/api/intelligence/eureka-health").json()
    # The key honest distinction: readiness is high, score stays low, reported separately.
    assert eh["empirical_readiness_score"] >= 7.0
    assert eh["empirical_score"] <= 3.0
    assert "empirical_readiness_score" in eh and "empirical_score" in eh
    assert eh["loop_closed"] is True
    assert _stamps_ok(eh)


def test_daily_shadow_run_disabled(client, monkeypatch):
    monkeypatch.setenv("SIL_ENABLED", "0")
    r = client.post("/api/intelligence/daily-shadow-run",
                    json={"session_date": "2026-06-01", "candidates": _CANDS})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_unknown_twin_404(client):
    r = client.get("/api/intelligence/twins/TWIN_does_not_exist")
    assert r.status_code == 404
