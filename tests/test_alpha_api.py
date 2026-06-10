"""Alpha framework API routes — advisory-only contract tests.

Routes under test (all read-only computations, no DB writes):
  GET  /alpha/case-studies/plumbing
  POST /alpha/score
  POST /alpha/value-chain/map
  POST /alpha/signal/decay
"""

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
    assert payload["execution_mode"] == "HUMAN_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["ai_execution_count"] == 0
    assert payload["broker_api_called"] is False
    assert payload["human_review_required"] is True


def test_plumbing_case_study_endpoint(client) -> None:
    response = client.get("/alpha/case-studies/plumbing")
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["case_study"] == "The Plumbing Alpha Case Study"
    assert len(payload["value_chain"]["nodes"]) >= 13
    assert "disclaimer" in payload


def test_alpha_score_endpoint_with_partial_components(client) -> None:
    response = client.post(
        "/alpha/score",
        json={"components": {"narrative_velocity": 80.0, "embedded_proof": 70.0}},
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert 0.0 <= payload["opportunity_score"] <= 100.0
    assert "food_chain" in payload["missing_inputs"]
    assert payload["disclaimer"] == (
        "Advisory-only. Not financial advice. No trade execution."
    )


def test_alpha_score_endpoint_ignores_unknown_components(client) -> None:
    response = client.post(
        "/alpha/score",
        json={"components": {"narrative_velocity": 80.0, "buy_signal": 100.0}},
    )
    assert response.status_code == 200
    assert "buy_signal" not in response.json()["score_components"]


def test_value_chain_map_endpoint(client) -> None:
    response = client.post(
        "/alpha/value-chain/map",
        json={
            "theme": "water",
            "nodes": [
                {"name": "valves", "urgency_score": 85.0, "bottleneck_strength": 80.0},
                {"name": "pipes", "commoditization_risk": 90.0},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["node_count"] == 2
    assert payload["top_node"] == "valves"


def test_value_chain_map_rejects_nameless_node(client) -> None:
    response = client.post(
        "/alpha/value-chain/map",
        json={"theme": "water", "nodes": [{"urgency_score": 85.0}]},
    )
    assert response.status_code == 422


def test_signal_decay_endpoint_explicit_half_life(client) -> None:
    response = client.post(
        "/alpha/signal/decay",
        json={"initial_strength": 1.0, "elapsed_days": 30.0, "half_life_days": 30.0},
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["current_strength"] == pytest.approx(0.5, rel=1e-6)


def test_signal_decay_endpoint_estimates_half_life_from_type(client) -> None:
    response = client.post(
        "/alpha/signal/decay",
        json={
            "initial_strength": 1.0,
            "elapsed_days": 2.0,
            "signal_type": "viral_social_post",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["half_life_estimate"]["signal_type"] == "viral_social_post"
    assert payload["current_strength"] < 1.0


def test_signal_decay_endpoint_rejects_negative_elapsed(client) -> None:
    response = client.post(
        "/alpha/signal/decay",
        json={"initial_strength": 1.0, "elapsed_days": -1.0, "half_life_days": 30.0},
    )
    assert response.status_code == 422


def test_alpha_routes_are_token_gated_when_token_set(client, monkeypatch) -> None:
    monkeypatch.setenv("MVP_API_TOKEN", "alpha-test-token")
    denied = client.get("/alpha/case-studies/plumbing")
    assert denied.status_code == 401
    allowed = client.get(
        "/alpha/case-studies/plumbing",
        headers={"Authorization": "Bearer alpha-test-token"},
    )
    assert allowed.status_code == 200


def test_no_execution_route_added_under_alpha_prefix(client) -> None:
    import scripts.api_server as srv

    alpha_paths = [
        route.path for route in srv.app.routes if route.path.startswith("/alpha")
    ]
    assert sorted(alpha_paths) == [
        "/alpha/case-studies/plumbing",
        "/alpha/filing/parse",
        "/alpha/prediction-market/normalize",
        "/alpha/replay/evaluate",
        "/alpha/score",
        "/alpha/signal/decay",
        "/alpha/value-chain/map",
    ]
    for forbidden in ("buy", "sell", "execute", "order", "broker", "trade"):
        for path in alpha_paths:
            assert forbidden not in path
