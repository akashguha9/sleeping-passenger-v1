"""API: score calibration is exposed and attached to the signals response."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from scripts import api_server  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    import scripts.persistence as persistence

    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "calib_api.db", raising=False)
    return TestClient(api_server.app)


def test_score_calibration_endpoint_uncalibrated_on_empty_db(client):
    r = client.get("/api/score-calibration")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["calibration_status"] == "UNCALIBRATED"
    assert data["score_should_drive_sizing"] is False
    assert data["advisory_status"] == "ADVISORY_ONLY"
    assert data["broker_api_called"] is False
    assert "not" in data["message"].lower()


def test_signals_response_carries_calibration_block(client):
    r = client.get("/signals")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "score_calibration" in data, "scores must travel with a calibration status"
    cal = data["score_calibration"]
    assert cal["calibration_status"] in {
        "UNCALIBRATED", "LOW_SAMPLE", "CALIBRATING", "CALIBRATED"
    }
    assert "score_should_drive_sizing" in cal
