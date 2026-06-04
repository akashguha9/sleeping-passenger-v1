"""End-to-end: the manual-trade-log API surfaces leverage-governance breaches.

The journal still RECORDS a breaching trade (it is a record, not an execution
blocker) but the response must carry leverage_breach=True with the severity
and reason so the operator sees it.  Advisory stamps must remain intact.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from scripts import api_server  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Route persistence to a throwaway DB so the test never touches runtime.
    import scripts.persistence as persistence

    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "lev_api.db", raising=False)
    return TestClient(api_server.app)


def _post(client, **overrides):
    body = {
        "event_id": "EV_LEVTEST_REAL_REVIEW",
        "ticker": "RELIANCE.NS",
        "side": "BUY",
        "quantity": 10,
        "price": 100.0,
        "thesis": "India equity within the 4x ceiling, genuine review note.",
        "leverage": 3.0,
    }
    body.update(overrides)
    return client.post("/manual-trades", json=body)


def test_india_within_ceiling_no_breach(client):
    r = _post(client, ticker="RELIANCE.NS", leverage=4.0,
              thesis="India 4x is exactly the ceiling, genuine note.")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["leverage_breach"] is False
    assert data["jurisdiction_group"] == "INDIA"
    assert data["leverage_ceiling"] == 4.0
    assert data["leverage_policy_severity"] == "NONE"


def test_india_over_ceiling_records_breach(client):
    r = _post(client, ticker="RELIANCE.NS", leverage=8.0,
              thesis="India 8x exceeds the 4x ceiling — should be flagged.")
    assert r.status_code == 200, r.text
    data = r.json()
    # Still recorded (journal), but flagged.
    assert data["status"] == "logged"
    assert data["leverage_breach"] is True
    assert data["leverage_policy_severity"] == "POLICY_BREACH"
    assert data["jurisdiction_group"] == "INDIA"
    assert "4" in data["leverage_policy_reason"]
    # Advisory invariants intact.
    assert data["broker_api_called"] is False
    assert data["ai_execution_count"] == 0
    assert data["execution_permission"] is False


def test_row_over_spot_records_breach(client):
    r = _post(client, ticker="AAPL", exchange="NASDAQ", leverage=2.0,
              thesis="US equity at 2x breaches the spot-only rule.")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["leverage_breach"] is True
    assert data["jurisdiction_group"] == "REST_OF_WORLD"
    assert data["leverage_ceiling"] == 1.0


def test_row_spot_no_breach(client):
    r = _post(client, ticker="AAPL", exchange="NASDAQ", leverage=1.0,
              thesis="US equity spot-only, genuine review note.")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["leverage_breach"] is False
    assert data["leverage_policy_severity"] == "NONE"


def test_unknown_jurisdiction_over_spot_records_breach(client):
    r = _post(client, ticker="ZZZQQ", leverage=3.0,
              thesis="Unknown venue at 3x must not silently pass.")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["jurisdiction_group"] == "UNKNOWN"
    assert data["leverage_breach"] is True
    assert data["leverage_policy_severity"] == "POLICY_BREACH"
