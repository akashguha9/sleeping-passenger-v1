"""Phase 2 alpha API routes — advisory-only contract tests.

Routes:
  POST /alpha/filing/parse
  POST /alpha/prediction-market/normalize
  POST /alpha/replay/evaluate
  POST /alpha/score (v2: prediction-market + filing integration)
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


_FILING_TEXT = (
    "Segment revenue from leak-detection hardware grew 18%.\n"
    "We entered into a contract with a national homebuilder.\n"
    "Our largest customer represented 22% of revenue."
)


def test_filing_parse_endpoint(client) -> None:
    response = client.post(
        "/alpha/filing/parse",
        json={
            "text": _FILING_TEXT,
            "source_type": "10-K",
            "narrative_claims": ["smart water growth"],
            "company": "Example Co",
            "ticker": "EXMPL",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["evidence"]
    assert payload["risk_disclosures"]
    assert payload["filing_signal"]["ticker"] == "EXMPL"
    assert 0.0 <= payload["embedded_proof_score"] <= 100.0
    assert "disclaimer" in payload


def test_filing_parse_empty_text_is_safe(client) -> None:
    response = client.post("/alpha/filing/parse", json={"text": ""})
    assert response.status_code == 200
    payload = response.json()
    assert payload["classification"] == "insufficient_evidence"
    assert "filing_text" in payload["missing_inputs"]


def test_filing_parse_rejects_oversized_text(client) -> None:
    response = client.post("/alpha/filing/parse", json={"text": "x" * 100_001})
    assert response.status_code == 422


def test_prediction_market_normalize_endpoint(client) -> None:
    response = client.post(
        "/alpha/prediction-market/normalize",
        json={
            "markets": [
                {
                    "event_name": "bill passes",
                    "yes_bid": 0.30,
                    "yes_ask": 0.34,
                    "source": "kalshi",
                },
                {"event_name": "no data event"},
            ],
            "model_probability": 0.41,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["signal_count"] == 2
    quoted, empty = payload["signals"]
    assert quoted["market_probability"] == pytest.approx(0.32)
    assert quoted["probability_edge"] == pytest.approx(0.09)
    assert empty["market_probability"] == 0.5
    assert empty["confidence"] == 0.0
    assert "market_probability" in empty["missing_inputs"]


def test_replay_evaluate_endpoint_with_demo_fixture(client) -> None:
    response = client.post(
        "/alpha/replay/evaluate", json={"use_demo_fixture": True, "k": 2}
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_advisory_stamp(payload)
    assert payload["record_count"] == 3
    assert "not performance results" in payload["disclaimer"]


def test_replay_evaluate_empty_records_safe(client) -> None:
    response = client.post("/alpha/replay/evaluate", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["record_count"] == 0
    assert payload["precision_at_k"] is None


def test_score_endpoint_derives_probability_confirmation(client) -> None:
    base = client.post("/alpha/score", json={"components": {}}).json()
    assert "probability_confirmation" in base["missing_inputs"]
    with_market = client.post(
        "/alpha/score",
        json={
            "components": {},
            "prediction_market": {
                "event_name": "catalyst event",
                "yes_bid": 0.30,
                "yes_ask": 0.34,
                "source": "kalshi",
            },
            "model_probability": 0.55,
        },
    ).json()
    assert "probability_confirmation" not in with_market["missing_inputs"]
    assert with_market["prediction_market_signal"]["probability_edge"] == pytest.approx(
        0.23
    )
    assert with_market["score_components"]["probability_confirmation"] > 50.0


def test_score_endpoint_derives_proof_and_risk_from_filing(client) -> None:
    payload = client.post(
        "/alpha/score",
        json={
            "components": {},
            "filing_text": _FILING_TEXT,
            "filing_source_type": "10-K",
            "narrative_claims": ["smart water growth"],
        },
    ).json()
    assert "embedded_proof" not in payload["missing_inputs"]
    assert payload["filing_parse"]["evidence_count"] >= 2
    assert payload["filing_risk_disclosure_score"] > 0.0
    assert "filing_risk_disclosure_score" not in payload["missing_inputs"]


def test_score_endpoint_explicit_components_beat_derived(client) -> None:
    payload = client.post(
        "/alpha/score",
        json={
            "components": {"probability_confirmation": 99.0},
            "prediction_market": {"yes_bid": 0.30, "yes_ask": 0.34, "source": "kalshi"},
            "model_probability": 0.10,
        },
    ).json()
    assert payload["score_components"]["probability_confirmation"] == 99.0


def test_score_endpoint_returns_v2_fields(client) -> None:
    payload = client.post("/alpha/score", json={"components": {}}).json()
    for key in (
        "confidence",
        "evidence_quality_score",
        "evidence_gap_risk",
        "trap_flags",
        "why_not_higher",
        "why_not_lower",
    ):
        assert key in payload


def test_phase2_post_routes_require_token_when_set(client, monkeypatch) -> None:
    monkeypatch.setenv("MVP_API_TOKEN", "phase2-test-token")
    for path, body in (
        ("/alpha/filing/parse", {"text": "x"}),
        ("/alpha/prediction-market/normalize", {"markets": []}),
        ("/alpha/replay/evaluate", {}),
    ):
        denied = client.post(path, json=body)
        assert denied.status_code == 401, path
        allowed = client.post(
            path, json=body, headers={"Authorization": "Bearer phase2-test-token"}
        )
        assert allowed.status_code == 200, path


def test_invalid_inputs_return_validation_errors(client) -> None:
    assert (
        client.post(
            "/alpha/score", json={"components": {}, "model_probability": 2.0}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/alpha/replay/evaluate", json={"records": [], "k": 0}
        ).status_code
        == 422
    )


def test_no_execution_verbs_in_phase2_responses(client) -> None:
    import json as json_module

    responses = [
        client.post("/alpha/replay/evaluate", json={"use_demo_fixture": True}).json(),
        client.post(
            "/alpha/prediction-market/normalize",
            json={"markets": [{"yes_bid": 0.4, "yes_ask": 0.42}]},
        ).json(),
    ]
    for payload in responses:
        text = json_module.dumps(payload).lower()
        for forbidden in ("place order", "broker api call", "execute trade", "guaranteed"):
            assert forbidden not in text
