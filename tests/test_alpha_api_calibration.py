"""Calibration-pass API routes: evidence bundle + calibrated journal replay."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    if not srv._FASTAPI_AVAILABLE:
        pytest.skip("FastAPI unavailable")
    return TestClient(srv.app, raise_server_exceptions=True)


def _assert_advisory_stamp(payload: dict) -> None:
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["ai_execution_count"] == 0
    assert payload["broker_api_called"] is False


def test_evidence_bundle_endpoint(client) -> None:
    response = client.post(
        "/alpha/evidence-bundle",
        json={
            "signal_name": "plumbing distributor signal",
            "components": {"residual_utility": 80.0, "food_chain": 75.0},
            "filing_text": "Order backlog increased to $500m.",
            "filing_source_type": "10-K",
            "narrative_claims": ["plumbing demand"],
            "value_chain_node": "distributors_hardware_stores",
            "created_at": "2026-06-10T00:00:00Z",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["bundle_id"].startswith("EB_")
    assert payload["calibration_summary"]["method"] == "insufficient_data"
    assert payload["autopsy"]["signal_name"] == "plumbing distributor signal"
    assert any(
        "order_backlog" in str(item.get("category", "")) for item in payload["filing_lineage"]
    )
    assert payload["disclaimer"] == (
        "Advisory-only. Not financial advice. No trade execution."
    )


def test_evidence_bundle_deterministic_with_fixed_created_at(client) -> None:
    body = {
        "signal_name": "deterministic signal",
        "components": {"residual_utility": 70.0},
        "created_at": "fixed",
    }
    first = client.post("/alpha/evidence-bundle", json=body).json()
    second = client.post("/alpha/evidence-bundle", json=body).json()
    assert first["bundle_id"] == second["bundle_id"]


def test_replay_from_journal_supports_fit_flag(client) -> None:
    response = client.post(
        "/alpha/replay/from-journal", json={"fit_calibration": True}
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    # Isolated test journal is empty: fit must refuse honestly.
    assert payload["calibration"]["method"] == "insufficient_data"
    assert payload["calibration"]["calibration_available"] is False
    assert "reliability" in payload


def test_calibration_routes_token_gated(client, monkeypatch) -> None:
    monkeypatch.setenv("MVP_API_TOKEN", "calibration-token")
    for path, body in (
        ("/alpha/evidence-bundle", {"signal_name": "x", "components": {}}),
        ("/alpha/replay/from-journal", {"fit_calibration": True}),
    ):
        assert client.post(path, json=body).status_code == 401, path
        assert (
            client.post(
                path, json=body, headers={"Authorization": "Bearer calibration-token"}
            ).status_code
            == 200
        ), path


def test_no_secrets_or_execution_language_in_bundle(client, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_BUNDLE_SECRET", "leak-canary-value")
    payload = client.post(
        "/alpha/evidence-bundle",
        json={"signal_name": "x", "components": {}, "created_at": "t0"},
    ).json()
    text = json.dumps(payload).lower()
    assert "leak-canary-value" not in text
    for forbidden in ("buy now", "guaranteed", "execute trade", "place order"):
        assert forbidden not in text
