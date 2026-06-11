"""Simulator API contract tests: advisory stamps, breakdown, no execution.

Covers both the pure logic layer (scripts/simulator_api.py) and the HTTP
routes (/simulator/doctrine, /simulator/evaluate).
"""

from __future__ import annotations

import json

import pytest

from scripts.simulator_api import (
    MAX_RISK_FACTORS,
    MAX_SIGNALS,
    evaluate_simulator_candidate,
    simulator_doctrine,
)

REQUIRED_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _assert_stamped(payload: dict) -> None:
    for key, expected in REQUIRED_STAMPS.items():
        assert payload.get(key) == expected, f"{key} != {expected!r}"


def test_evaluate_returns_full_breakdown_with_stamps() -> None:
    result = evaluate_simulator_candidate(
        {
            "ticker": "TEST",
            "opportunity_quality": 0.5,
            "meal_box": {
                "thesis": "a structural thesis here",
                "evidence": "filings support the thesis",
                "catalyst": "earnings within 30 days",
                "invalidation": "exit if growth stalls below 5%",
            },
        }
    )
    _assert_stamped(result)
    assert result["decision"]["ticker"] == "TEST"
    assert "breakdown" in result
    assert "telemetry" in result
    assert "generated_at" in result
    # Never a naked score.
    assert result["decision"]["decision_reason"]
    assert result["decision"]["score_components"]
    json.dumps(result)  # must be serializable


def test_evaluate_handles_none_and_garbage_payloads() -> None:
    for garbage in (None, [], "nope", 42):
        result = evaluate_simulator_candidate(garbage)  # type: ignore[arg-type]
        _assert_stamped(result)
        assert result["decision"]["final_state"] == "reject"


def test_hostile_payload_lists_are_bounded() -> None:
    result = evaluate_simulator_candidate(
        {
            "signals": [
                {"signal_type": "social_spike", "raw_strength": 50, "signal_age_hours": 1}
            ]
            * (MAX_SIGNALS + 40),
            "risk_factors": {f"risk_{i}": 0.5 for i in range(MAX_RISK_FACTORS + 40)},
        }
    )
    assert len(result["breakdown"]["tyres"]) == MAX_SIGNALS
    # Crash simulator additionally caps to its strongest-10 working set.
    assert len(result["breakdown"]["crash"]["individual_risks"]) <= MAX_RISK_FACTORS


def test_doctrine_surface_is_stamped_and_complete() -> None:
    doctrine = simulator_doctrine()
    _assert_stamped(doctrine)
    assert "No signal is immortal." in doctrine["doctrine"]
    assert "No fire extinguisher, no trade." in doctrine["doctrine"]
    assert doctrine["signal_compound_half_lives_hours"]["soft"] < (
        doctrine["signal_compound_half_lives_hours"]["hard"]
    )
    assert "micro_cap" in doctrine["circuits"]
    json.dumps(doctrine)


def test_evaluate_never_emits_execution_permission() -> None:
    result = evaluate_simulator_candidate({"ticker": "TEST"})
    assert result.get("execution_permission") is False
    assert result.get("can_execute") is False
    serialized = json.dumps(result).lower()
    assert "broker_order_id" not in serialized or '"none"' in serialized


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ModuleNotFoundError:  # pragma: no cover
        pytest.skip("fastapi not installed")
    from scripts import api_server

    if not getattr(api_server, "_FASTAPI_AVAILABLE", False):
        pytest.skip("fastapi not available in this environment")
    return TestClient(api_server.app)


def test_http_get_simulator_doctrine(client) -> None:
    response = client.get("/simulator/doctrine")
    assert response.status_code == 200
    payload = response.json()
    _assert_stamped(payload)
    assert "doctrine" in payload


def test_http_post_simulator_evaluate(client) -> None:
    response = client.post(
        "/simulator/evaluate",
        json={"ticker": "GRIDCO", "opportunity_quality": 0.8},
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_stamped(payload)
    assert payload["decision"]["ticker"] == "GRIDCO"
    assert payload["decision"]["final_state"] in (
        "reject", "archive", "watchlist", "active_watch",
        "buy_candidate", "high_conviction_candidate", "pit_stop", "black_flag",
    )


def test_http_simulator_routes_are_not_execution_routes(client) -> None:
    # The simulator namespace must never look like an order path.
    for forbidden in ("/simulator/execute", "/simulator/order", "/simulator/buy"):
        response = client.post(forbidden, json={})
        assert response.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Committed example snapshot
# ---------------------------------------------------------------------------


def test_committed_example_output_is_valid_and_stamped() -> None:
    from pathlib import Path

    example_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "examples"
        / "simulator_example_output.json"
    )
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    _assert_stamped(payload)
    assert payload["decision"]["ticker"] == "GRIDCO"
    assert payload["decision"]["final_state"] in (
        "reject", "archive", "watchlist", "active_watch",
        "buy_candidate", "high_conviction_candidate",
    )
    assert payload["telemetry"]["calibration_status"] == "pending"
    assert "breakdown" in payload
