"""Final-boss alpha API routes: journal replay bridge + autopsy."""

from __future__ import annotations

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


def test_replay_from_journal_endpoint_safe_on_empty_journal(client) -> None:
    response = client.post("/alpha/replay/from-journal", json={"k": 3})
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    # Test environment isolates the journal DB: empty is the honest answer.
    assert payload["calibration_support"] == 0.0
    assert payload["bridge"]["discovered_records"] == 0
    assert "not performance results" in payload["disclaimer"]


def test_autopsy_endpoint_full_flow(client) -> None:
    response = client.post(
        "/alpha/autopsy",
        json={
            "signal_name": "plumbing distributor signal",
            "components": {
                "narrative_velocity": 30.0,
                "node_strength": 70.0,
                "residual_utility": 85.0,
                "food_chain": 80.0,
            },
            "filing_text": (
                "Order backlog increased to $500m.\n"
                "We do not generate segment revenue from AI."
            ),
            "filing_source_type": "10-K",
            "narrative_claims": ["AI growth", "plumbing demand"],
            "value_chain_node": "distributors_hardware_stores",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["value_chain_node"] == "distributors_hardware_stores"
    assert any("order_backlog" in item for item in payload["embedded_proof"])
    assert any("explicitly negated" in item for item in payload["missing_proof"])
    assert payload["next_evidence_to_collect"]
    assert "uncalibrated" in payload["calibration_state"]


def test_autopsy_rejects_oversized_inputs(client) -> None:
    assert (
        client.post(
            "/alpha/autopsy",
            json={"signal_name": "x" * 301, "components": {}},
        ).status_code
        == 422
    )


def test_case_study_endpoint_serves_v4(client) -> None:
    payload = client.get("/alpha/case-studies/plumbing").json()
    assert payload["version"] == "v4"
    assert "node_profiles" in payload
    assert "autopsy" in payload
    assert "calibration_state" in payload
    assert "calibration_summary" in payload
    assert "operator_checklist" in payload
    assert "readiness_statement" in payload


def test_final_routes_require_token_when_set(client, monkeypatch) -> None:
    monkeypatch.setenv("MVP_API_TOKEN", "final-boss-token")
    for path, body in (
        ("/alpha/replay/from-journal", {}),
        ("/alpha/autopsy", {"signal_name": "x", "components": {}}),
    ):
        assert client.post(path, json=body).status_code == 401, path
        assert (
            client.post(
                path, json=body, headers={"Authorization": "Bearer final-boss-token"}
            ).status_code
            == 200
        ), path


def test_no_execution_language_in_final_routes(client) -> None:
    import json as json_module

    payloads = [
        client.post("/alpha/replay/from-journal", json={}).json(),
        client.post(
            "/alpha/autopsy", json={"signal_name": "x", "components": {}}
        ).json(),
    ]
    for payload in payloads:
        text = json_module.dumps(payload).lower()
        for forbidden in ("buy now", "guaranteed", "execute trade", "place order"):
            assert forbidden not in text
