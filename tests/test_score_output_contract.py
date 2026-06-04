"""Tests for the shared score-output contract + its presence on score APIs."""
from __future__ import annotations

import pytest

from scripts import score_output_contract as soc
from scripts.score_calibration import compute_score_calibration


def test_contract_has_all_required_keys():
    c = soc.build_score_contract(0.91, compute_score_calibration([]), label="priority_score")
    for k in soc.REQUIRED_KEYS:
        assert k in c
    soc.assert_score_contract(c)


def test_uncalibrated_score_is_not_sizing_grade():
    c = soc.build_score_contract(0.99, compute_score_calibration([]))
    assert c["calibration_status"] == "UNCALIBRATED"
    assert c["should_drive_sizing"] is False
    assert c["calibrated_score"] is None
    assert "not" in c["warning"].lower()


def test_calibrated_but_no_human_approval_still_not_sizing():
    rows = [{"outcome_status": "WIN", "pnl_estimate": 1.0}] * 30
    rows += [{"outcome_status": "LOSS", "pnl_estimate": -1.0}] * 25
    summary = compute_score_calibration(rows)  # CALIBRATED
    c = soc.build_score_contract(0.8, summary, human_sizing_approved=False)
    assert c["calibration_status"] == "CALIBRATED"
    assert c["should_drive_sizing"] is False  # human approval withheld
    assert c["calibrated_score"] is None


def test_calibrated_with_human_approval_is_sizing_grade():
    rows = [{"outcome_status": "WIN", "pnl_estimate": 1.0}] * 30
    rows += [{"outcome_status": "LOSS", "pnl_estimate": -1.0}] * 25
    summary = compute_score_calibration(rows)
    c = soc.build_score_contract(0.8, summary, human_sizing_approved=True)
    assert c["should_drive_sizing"] is True
    assert c["calibrated_score"] == 0.8


def test_has_score_contract_detects_missing():
    assert soc.has_score_contract(soc.build_score_contract(0.5)) is True
    assert soc.has_score_contract({"raw_score": 0.5}) is False
    assert soc.has_score_contract(None) is False


def test_assert_raises_on_incomplete_contract():
    with pytest.raises(AssertionError):
        soc.assert_score_contract({"raw_score": 0.5})


def test_contract_never_grants_execution():
    c = soc.build_score_contract(0.91, compute_score_calibration([]))
    assert c["advisory_only"] is True
    assert c["broker_api_called"] is False
    assert c["human_review_required"] is True


# --- /signals carries the contract ------------------------------------------

def test_signals_response_carries_score_contract(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from scripts import api_server
    import scripts.persistence as persistence

    monkeypatch.setattr(persistence, "DB_PATH", tmp_path / "contract_api.db", raising=False)
    client = TestClient(api_server.app)
    r = client.get("/signals")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "score_contract" in data, "score response must carry the contract"
    soc.assert_score_contract(data["score_contract"])
    # On an empty DB the scores are uncalibrated -> not sizing-grade.
    assert data["score_contract"]["should_drive_sizing"] is False
