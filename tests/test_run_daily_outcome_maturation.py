"""Real-Forward Outcome Maturation Sprint — Phase 2 daily-runner tests.

The runner scans maturity, attaches outcomes only when a horizon has truly
elapsed, recomputes calibration, refreshes the bundle, and reports honestly.
It is dry-run by default and never unlocks a predictive claim below N=200.
"""
from __future__ import annotations

import json

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    read_snapshot,
    seed_market_bar,
    seed_score_vector,
)
from scripts.run_daily_outcome_maturation import (
    NO_DUE_REASON,
    run_daily_outcome_maturation,
)
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch

_DECISION = "2026-05-10T00:00:00Z"
_AFTER_HORIZON = "2026-05-20T00:00:00Z"   # past the 5-day horizon close (05-15)
_BEFORE_HORIZON = "2026-05-12T00:00:00Z"  # horizon not yet closed


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _seed_eligible(db, *, exit_close=200.0, event_id="ev1", ticker="AAPL"):
    seed_score_vector(db, event_id=event_id, ticker=ticker)
    seed_market_bar(db, symbol=ticker, timestamp="2026-05-09T00:00:00Z", close=190.0)
    seed_market_bar(db, symbol=ticker, timestamp="2026-05-15T00:00:00Z", close=exit_close)
    run_daily_decision_batch(
        db_path=db, events=[event_row(event_id, payload={})], now_iso=_DECISION, write=True
    )


def test_daily_runner_dry_run_does_not_write(db):
    _seed_eligible(db)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_AFTER_HORIZON, write=False)
    assert out["write_mode"] is False
    # Dry run: the outcome is never persisted to the snapshot row.
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["outcome_label"] is None
    assert out["evidence_bundle_path"] is None


def test_daily_runner_reports_no_due_snapshots_truthfully(db):
    _seed_eligible(db)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_BEFORE_HORIZON, write=True)
    assert out["n_due_forward"] == 0
    assert out["outcomes_attached"] == 0
    assert out["attach_reason"] == NO_DUE_REASON
    assert out["n_pending_horizon"] == 1
    assert out["next_due_in_hours"] is not None and out["next_due_in_hours"] > 0


def test_daily_runner_attaches_due_outcomes_when_due(db):
    _seed_eligible(db, exit_close=200.0)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_AFTER_HORIZON, write=True)
    assert out["n_due_forward"] == 1
    assert out["outcomes_attached"] == 1
    snap = read_snapshot(db, signal_id="ev1")
    assert snap["outcome_label"] == 1
    assert snap["outcome_kind"] == "real_forward"


def test_daily_runner_increments_n_real_forward(db):
    _seed_eligible(db, exit_close=200.0)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_AFTER_HORIZON, write=True)
    assert out["n_real_forward_before"] == 0
    assert out["n_real_forward_after"] == 1
    assert out["delta_n_real_forward"] == 1


def test_daily_runner_recomputes_calibration_after_attach(db):
    _seed_eligible(db, exit_close=200.0)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_AFTER_HORIZON, write=True)
    # With one pair the metric is computed (not None) but stays below the gate:
    # the status is a warning tier (never MEASURED) and the claim stays locked.
    assert out["brier_real_forward"] is not None
    assert out["calibration_status"] != "MEASURED"
    assert out["predictive_claim_allowed"] is False


def test_daily_runner_refreshes_bundle(db, tmp_path):
    _seed_eligible(db, exit_close=200.0)
    jpath = tmp_path / "bundle.json"
    mpath = tmp_path / "bundle.md"
    out = run_daily_outcome_maturation(
        db_path=db, now_utc=_AFTER_HORIZON, write=True,
        bundle_json_path=jpath, bundle_md_path=mpath,
    )
    assert out["evidence_bundle_path"] == str(jpath)
    assert jpath.exists()
    assert mpath.exists()


def test_daily_runner_keeps_predictive_claim_locked_below_200(db):
    _seed_eligible(db, exit_close=200.0)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_AFTER_HORIZON, write=True)
    assert out["predictive_claim_allowed"] is False
    assert out["n_real_forward_after"] < 200
    assert out["n_needed_to_200"] == 200 - out["n_real_forward_after"]


def test_daily_runner_preserves_advisory_only_stamps(db):
    _seed_eligible(db)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_AFTER_HORIZON, write=True)
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["human_execution_required"] is True
    assert out["real_money_ready"] is False


def test_daily_runner_has_no_execution_language(db):
    _seed_eligible(db)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_AFTER_HORIZON, write=True)
    blob = json.dumps(out).lower()
    for forbidden in (
        "place order", "execute trade", "auto-trade", "buy now", "sell now",
        "broker_api_called\": true",
    ):
        assert forbidden not in blob


def test_daily_runner_reports_next_due_time(db):
    _seed_eligible(db)
    out = run_daily_outcome_maturation(db_path=db, now_utc=_BEFORE_HORIZON, write=False)
    # 05-12 -> horizon close 05-15 00:00 == 72 hours.
    assert out["next_due_in_hours"] == pytest.approx(72.0, abs=0.01)
    assert out["earliest_horizon_close_utc"] == "2026-05-15T00:00:00Z"
