"""Real-Forward Outcome Maturation Sprint — Phase 5 evidence-route tests.

/evidence/outcomes now carries a ``maturation`` block (and a top-level
``next_due_in_hours``) reporting how many snapshots are eligible/pending/due,
the live real-forward metrics, and how many pairs are still needed for the gate.
The predictive claim stays locked below N=200.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    seed_market_bar,
    seed_score_vector,
)
from scripts.api.routers.evidence_router import build_outcomes_payload
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _seed_pending(db):
    """Seed a fresh live snapshot whose horizon is still open."""
    now = datetime.now(timezone.utc)
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp=_iso(now - timedelta(days=1)), close=190.0)
    run_daily_decision_batch(
        db_path=db, events=[event_row("ev1", payload={})], now_iso=_iso(now), write=True
    )


def test_route_reports_maturation_fields(db):
    _seed_pending(db)
    payload = build_outcomes_payload(db_path=db)
    mat = payload["maturation"]
    for key in (
        "n_forward_eligible", "n_pending_horizon", "n_due_forward",
        "n_real_forward_pairs", "delta_n_real_forward_last_run",
        "next_due_in_hours", "earliest_horizon_close_utc",
        "brier_real_forward", "ece_real_forward", "logloss_real_forward",
        "n_needed_to_200", "calibration_status", "status_detail",
        "predictive_claim_allowed",
    ):
        assert key in mat
    assert mat["n_forward_eligible"] >= 1
    assert mat["n_pending_horizon"] >= 1
    assert mat["n_due_forward"] == 0


def test_route_reports_next_due_in_hours(db):
    _seed_pending(db)
    payload = build_outcomes_payload(db_path=db)
    # The horizon is open, so next-due is a positive number of hours.
    assert payload["next_due_in_hours"] is not None
    assert payload["next_due_in_hours"] > 0
    assert payload["maturation"]["next_due_in_hours"] == payload["next_due_in_hours"]


def test_route_reports_first_pairs_status_detail(db):
    _seed_pending(db)
    payload = build_outcomes_payload(db_path=db)
    # No pairs attached yet -> the honest "no pairs" detail.
    assert payload["maturation"]["status_detail"] == "NO_REAL_FORWARD_PAIRS"


def test_route_predictive_claim_locked_below_200(db):
    _seed_pending(db)
    payload = build_outcomes_payload(db_path=db)
    mat = payload["maturation"]
    assert mat["predictive_claim_allowed"] is False
    assert mat["n_real_forward_pairs"] < 200
    assert mat["n_needed_to_200"] == 200 - mat["n_real_forward_pairs"]


def test_route_has_no_execution_language(db):
    _seed_pending(db)
    payload = build_outcomes_payload(db_path=db)
    blob = repr(payload).lower()
    for banned in ("place order", "execute trade", "auto-trade", "buy now", "sell now"):
        assert banned not in blob
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
