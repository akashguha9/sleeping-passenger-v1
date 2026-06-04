"""E2E: the manual-trade-log API resolves jurisdiction from the securities
master when present, and reports the resolution source.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from scripts import api_server  # noqa: E402
import scripts.persistence as persistence  # noqa: E402


@pytest.fixture
def seeded_client(tmp_path, monkeypatch):
    db = tmp_path / "lev_master_api.db"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    # Seed a bare US ticker with no India/ROW suffix so ONLY the master can
    # classify it.
    persistence.upsert_global_security(
        canonical_symbol="AAPL", name="Apple", exchange_code="NASDAQ",
        country="US", db_path=db,
    )
    persistence.upsert_global_security(
        canonical_symbol="RELIANCE", name="Reliance", exchange_code="NSE",
        country="IN", db_path=db,
    )
    return TestClient(api_server.app), db


def _post(client, **overrides):
    body = {
        "event_id": "EV_MASTER_REAL_REVIEW",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 5,
        "price": 200.0,
        "thesis": "Bare US ticker resolved through the securities master.",
        "leverage": 1.0,
    }
    body.update(overrides)
    return client.post("/manual-trades", json=body)


def test_bare_us_ticker_resolved_by_master_no_breach(seeded_client):
    client, _ = seeded_client
    r = _post(client, ticker="AAPL", leverage=1.0)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["jurisdiction_group"] == "REST_OF_WORLD"
    assert data["jurisdiction_resolution_source"] == "SECURITIES_MASTER"
    assert data["leverage_breach"] is False


def test_bare_us_ticker_master_flags_leverage_breach(seeded_client):
    client, _ = seeded_client
    r = _post(client, ticker="AAPL", leverage=3.0,
              thesis="US equity at 3x — master resolves ROW, must breach.")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["jurisdiction_resolution_source"] == "SECURITIES_MASTER"
    assert data["jurisdiction_group"] == "REST_OF_WORLD"
    assert data["leverage_breach"] is True
    assert data["broker_api_called"] is False


def test_bare_india_ticker_master_allows_up_to_4x(seeded_client):
    client, _ = seeded_client
    r = _post(client, ticker="RELIANCE", leverage=4.0,
              thesis="India equity at 4x is the ceiling, resolved by master.")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["jurisdiction_group"] == "INDIA"
    assert data["jurisdiction_resolution_source"] == "SECURITIES_MASTER"
    assert data["leverage_breach"] is False


def test_unseeded_ticker_falls_back_and_fails_closed(seeded_client):
    client, _ = seeded_client
    r = _post(client, ticker="MYSTERYCO", leverage=2.0,
              thesis="Unknown ticker not in master and no suffix; fail closed.")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["jurisdiction_group"] == "UNKNOWN"
    assert data["jurisdiction_resolution_source"] == "UNKNOWN_FAIL_CLOSED"
    assert data["leverage_breach"] is True
