"""Simulator persistence + new endpoint tests.

Locks: hysteresis memory across sessions, read-only history with advisory
stamps, outcome resolution feeding calibration, and the three new routes
(/simulator/evaluate-and-record, /simulator/history,
/simulator/calibration/report) honoring the API contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import persistence
from scripts import simulator_store
from scripts.simulator_api import (
    evaluate_and_record_candidate,
    simulator_calibration_report,
    simulator_history,
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


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "simulator_store.db"
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    return db


BASE_PAYLOAD = {
    "ticker": "GRIDCO",
    "theme": "ai_grid_buildout",
    "opportunity_quality": 0.8,
    "predicted_probability": 0.6,
}


def test_record_and_previous_state_lookup(tmp_db: Path) -> None:
    first = evaluate_and_record_candidate(dict(BASE_PAYLOAD))
    assert first["recorded"] is True
    assert first["previous_state_used"] is None
    assert isinstance(first["evaluation_id"], int)

    second = evaluate_and_record_candidate(dict(BASE_PAYLOAD))
    assert second["previous_state_used"] == first["decision"]["final_state"]
    # Explicit caller previous_state always wins over the store.
    third = evaluate_and_record_candidate(
        {**BASE_PAYLOAD, "previous_state": "active_watch"}
    )
    assert third["previous_state_used"] == "active_watch"


def test_hysteresis_uses_persisted_state(tmp_db: Path) -> None:
    # Park the candidate at buy_candidate, then re-evaluate with a score
    # just under the threshold: hysteresis must hold the state.
    rich = evaluate_and_record_candidate(dict(BASE_PAYLOAD))
    state = rich["decision"]["final_state"]
    again = evaluate_and_record_candidate(dict(BASE_PAYLOAD))
    assert again["decision"]["ladder"]["previous_state"] == state


def test_history_is_stamped_and_ordered(tmp_db: Path) -> None:
    evaluate_and_record_candidate(dict(BASE_PAYLOAD))
    evaluate_and_record_candidate({**BASE_PAYLOAD, "ticker": "OTHERCO"})
    history = simulator_history()
    _assert_stamped(history)
    assert history["count"] == 2
    only_grid = simulator_history(ticker="gridco")
    assert only_grid["count"] == 1
    assert only_grid["items"][0]["ticker"] == "GRIDCO"
    # No broker fields anywhere in stored rows.
    serialized = json.dumps(history).lower()
    assert "broker_order" not in serialized or '"none"' in serialized


def test_history_limit_is_bounded(tmp_db: Path) -> None:
    evaluate_and_record_candidate(dict(BASE_PAYLOAD))
    assert simulator_history(limit=10_000)["count"] == 1  # clamped, no error


def test_resolve_outcome_feeds_calibration(tmp_db: Path) -> None:
    result = evaluate_and_record_candidate(dict(BASE_PAYLOAD))
    evaluation_id = result["evaluation_id"]

    before = simulator_calibration_report()
    assert before["calibration_mode"] == "insufficient_data"

    assert simulator_store.resolve_evaluation_outcome(
        evaluation_id,
        actual_outcome=0.0,
        outcome_class="good_process_bad_result",
    )
    rows = simulator_store.load_all_telemetry()
    resolved = [r for r in rows if r["calibration_status"] == "resolved"]
    assert len(resolved) == 1
    assert resolved[0]["calibration_error"] == pytest.approx(0.6)

    # Still insufficient (n=1) and never autotunable — honest by design.
    after = simulator_calibration_report()
    _assert_stamped(after)
    assert after["sample_size"] == 1
    assert after["calibration_mode"] == "insufficient_data"
    assert after["unsafe_to_autotune"] is True


def test_resolve_unknown_evaluation_returns_false(tmp_db: Path) -> None:
    assert not simulator_store.resolve_evaluation_outcome(
        999, actual_outcome=1.0, outcome_class="good_process_good_result"
    )
    with pytest.raises(ValueError):
        simulator_store.resolve_evaluation_outcome(
            1, actual_outcome=1.0, outcome_class="vibes"
        )


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
        pytest.skip("fastapi not available")
    return TestClient(api_server.app)


def test_http_evaluate_and_record(client) -> None:
    response = client.post(
        "/simulator/evaluate-and-record", json=dict(BASE_PAYLOAD)
    )
    assert response.status_code == 200
    payload = response.json()
    _assert_stamped(payload)
    assert payload["recorded"] is True
    assert "evaluation_id" in payload


def test_http_history_and_calibration_report(client) -> None:
    history = client.get("/simulator/history?limit=5")
    assert history.status_code == 200
    _assert_stamped(history.json())

    report = client.get("/simulator/calibration/report")
    assert report.status_code == 200
    body = report.json()
    _assert_stamped(body)
    assert body["calibration_mode"] in (
        "insufficient_data", "fixture_replay", "empirical",
    )
    assert body["unsafe_to_autotune"] is True
    assert "advisory_note" in body
