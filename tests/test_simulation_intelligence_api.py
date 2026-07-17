"""SIL persistence + FastAPI route integration + no-execution invariants.

Uses a temp DB (persistence.DB_PATH monkeypatch, the repo's standard pattern)
and TestClient.  Verifies the schema migration is additive/backward-compatible,
the run round-trips, replay is deterministic, and every route keeps the
advisory / no-execution stamps.
"""
from __future__ import annotations

import sqlite3

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from scripts import persistence  # noqa: E402


_DEMO_OBS = {
    "ticker": "TCS.NS", "market": "IN", "data_cutoff": "2026-07-15", "price": 3900.0,
    "returns": [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.0, -0.02, 0.03, -0.04, 0.02],
    "volatility": 0.03, "spread_bps": 9, "adv_usd": 7e6, "sector": "IT",
    "narrative_sources": ["sec"], "source_count": 1, "freshness_status": "FRESH",
    "catalysts": [{"id": "earn", "magnitude": 0.2}],
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "sim.db"
    monkeypatch.setattr(persistence, "DB_PATH", p, raising=False)
    persistence.init_schema(p)
    return p


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)  # loopback-open reads
    from scripts import api_server
    return TestClient(api_server.app)


# ---------------------------------------------------------------------------
# schema / migration
# ---------------------------------------------------------------------------
def test_simulation_runs_table_created(db):
    conn = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(simulation_runs)").fetchall()}
    finally:
        conn.close()
    for required in ("run_id", "ticker", "seed", "aggregate_vote", "evidence_label",
                     "result_json", "request_json", "advisory_status", "broker_api_called"):
        assert required in cols


def test_schema_init_is_idempotent(db):
    # Running init_schema twice must not error (additive CREATE IF NOT EXISTS).
    persistence.init_schema(db)
    persistence.init_schema(db)
    status = persistence.get_db_status(db_path=db)
    assert "simulation_runs" in status["table_row_counts"]


def test_db_status_includes_simulation_runs(db):
    assert "simulation_runs" in persistence.get_db_status(db_path=db)["table_row_counts"]


# ---------------------------------------------------------------------------
# persistence round-trip
# ---------------------------------------------------------------------------
def test_run_round_trip_and_leakage_isolation(db):
    from scripts.simulation_intelligence import api_surface as api, engine_manifest as em
    payload = {"ticker": "TCS.NS", "market": "IN", "seed": 5, "observation": _DEMO_OBS}
    result = api.run_simulation(payload)
    rid = persistence.insert_simulation_run(
        result, request_payload=payload, engine_manifest_version=em.MANIFEST_VERSION, db_path=db)
    got = persistence.get_simulation_run(rid, db_path=db)
    assert got["run_id"] == rid
    assert got["simulation_only"] in (True, False)
    assert got["broker_api_called"] is False
    assert "lens_results" in got["result"]
    # Leakage prevention: a simulated run must NOT create manual_trades /
    # imported_outcomes rows (those feed calibration).
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM manual_trades").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM imported_outcomes").fetchone()[0] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
def test_health_engines_scenarios_routes(client):
    assert client.get("/api/simulation/health").status_code == 200
    engines = client.get("/api/simulation/engines").json()
    assert engines["summary"]["engine_count"] == 18
    assert client.get("/api/simulation/scenarios").json()["count"] >= 30


def test_post_run_persists_and_stamps(client):
    body = {"ticker": "TCS.NS", "market": "IN", "seed": 5, "observation": _DEMO_OBS}
    r = client.post("/api/simulation/run", json=body)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["persisted"] is True
    assert j["execution_gate"] == "LOCKED"
    assert j["ai_execution_count"] == 0
    assert j["broker_api_called"] is False
    assert j["evidence_label"] != "MEASURED"
    rid = j["run_id"]
    assert client.get(f"/api/simulation/runs/{rid}").status_code == 200


def test_replay_is_deterministic_via_route(client):
    body = {"ticker": "TCS.NS", "market": "IN", "seed": 5, "observation": _DEMO_OBS}
    rid = client.post("/api/simulation/run", json=body).json()["run_id"]
    replay = client.get(f"/api/simulation/runs/{rid}/replay").json()
    assert replay["deterministic_match"] is True
    assert replay["telemetry_timeline"]


def test_unknown_run_is_404(client):
    assert client.get("/api/simulation/runs/SIM_nonexistent").status_code == 404


def test_council_route_reports_not_found_before_any_run(client):
    j = client.get("/api/simulation/council/NOPE.NS").json()
    assert j["found"] is False
    assert j["execution_gate"] == "LOCKED"


def test_stress_summary_route(client):
    body = {"ticker": "TCS.NS", "market": "IN", "seed": 5, "observation": _DEMO_OBS}
    client.post("/api/simulation/run", json=body)
    j = client.get("/api/simulation/stress-summary").json()
    assert j["report"] == "simulation_stress_summary"
    assert "SIMULATED_ONLY" in j["evidence_note"]


def test_post_run_requires_token_when_set(db, monkeypatch):
    monkeypatch.setenv("MVP_API_TOKEN", "secret-token")
    from scripts import api_server
    c = TestClient(api_server.app)
    body = {"ticker": "TCS.NS", "seed": 1, "observation": _DEMO_OBS}
    # Missing token → 401/403 (mutating route is token-gated).
    r = c.post("/api/simulation/run", json=body)
    assert r.status_code in (401, 403)
    # With token → allowed.
    ok = c.post("/api/simulation/run", json=body,
                headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200


def test_post_run_rejects_oversized_ticker(client):
    r = client.post("/api/simulation/run", json={"ticker": "X" * 500, "observation": _DEMO_OBS})
    # pydantic max_length=32 → 422 validation error.
    assert r.status_code == 422
