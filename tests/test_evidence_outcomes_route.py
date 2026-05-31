"""Close the Outcome Loop Sprint — Phase 5 backend route tests.

The read-only ``GET /evidence/outcomes`` surface reports the real-forward
outcome corpus honestly: pending-horizon, excluded, Brier/ECE/LogLoss, the gap
to the N=200 gate, and a locked predictive claim — never green, never executable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import persistence
from scripts.decision_probability_snapshot import (
    build_decision_snapshot,
    persist_decision_snapshot,
)
from scripts.outcome_labeling_flow import REAL_FORWARD, attach_outcome
from scripts.api.routers.evidence_router import (
    build_outcomes_payload,
    get_evidence_outcomes,
)

_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.45, "LS": 0.5, "EFS": 0.5, "APS": 0.5}


def _seed(db: Path, sid: str, *, ts: str, horizon: float, y=None) -> str:
    snap = build_decision_snapshot(signal_id=sid, axes=_AXES, ticker="SPY",
                                   prediction_horizon_days=horizon, timestamp_utc=ts)
    persist_decision_snapshot(snap, db)
    if y is not None:
        attach_outcome(db, snap["snapshot_id"], int(y), outcome_kind=REAL_FORWARD,
                       is_real_outcome=True, horizon_elapsed=True)
    return snap["snapshot_id"]


def test_outcomes_payload_reports_real_forward_and_pending(tmp_path, monkeypatch):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    # One resolved real-forward pair, one still pending its horizon.
    _seed(db, "DONE", ts="2026-01-05T00:00:00Z", horizon=5.0, y=1)
    _seed(db, "PEND", ts="2026-05-30T00:00:00Z", horizon=90.0)

    payload = build_outcomes_payload(db_path=db)
    assert payload["status"] == "OK"
    assert payload["n_real_forward_pairs"] == 1
    assert payload["n_pending_horizon"] == 1
    assert payload["needed_for_gate"] == 199
    assert payload["predictive_claim_allowed"] is False
    assert payload["predictive_claim_label"] == "PREDICTIVE_CLAIM_LOCKED"


def test_outcomes_payload_advisory_safety(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    _seed(db, "X", ts="2026-01-05T00:00:00Z", horizon=5.0, y=0)
    payload = build_outcomes_payload(db_path=db)
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["real_money_ready"] is False
    assert payload["edge_claimed"] is False


def test_outcomes_payload_no_execution_language(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    payload = build_outcomes_payload(db_path=db)
    blob = str(payload).lower()
    # No actionable execution wording.  (broker_order_id=NONE is a safety stamp,
    # i.e. the opposite of an execution instruction, so it is allowed.)
    for banned in ("place order", "execute trade", "auto-trade", "buy now", "sell now"):
        assert banned not in blob


def test_get_evidence_outcomes_handler_runs():
    # The handler resolves the builder via api_server and must not raise.
    payload = get_evidence_outcomes()
    assert "n_real_forward_pairs" in payload
    assert payload["execution_gate"] == "LOCKED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
