"""Tests — attach due outcomes after horizons close (Phase 5).

Deterministic, offline.  Proves outcomes are attached ONLY when real and the
horizon has elapsed, open trades are never labelled, missing price evidence is
excluded with a reason, unelapsed horizons stay pending, and only eligible
real-forward pairs grow N_real_forward.  Advisory context is preserved throughout.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.decision_probability_snapshot import record_decision_probability
from scripts.attach_due_outcomes import (
    REASON_NO_PRICE_EVIDENCE,
    REASON_OPEN_TRADE,
    attach_due_outcomes,
    compute_outcome_label,
    horizon_elapsed,
)
from scripts.real_calibration_evidence import extract_datasets


_AXES = {"EMS": 0.6, "EQS": 0.55, "DS": 0.45, "LS": 0.5, "EFS": 0.5, "APS": 0.5}
_PAST = "2026-01-01T00:00:00Z"        # decision time, well in the past
_NOW = "2026-05-31T00:00:00Z"          # "now" — months after a 1-day horizon


def _seed_decision(db: Path, did: str, *, ts: str = _PAST, horizon: float = 1.0) -> str:
    snap = record_decision_probability(
        db_path=db,
        signal_id=did,
        axes=dict(_AXES),
        prediction_horizon_days=horizon,
        timestamp_utc=ts,
    )
    return snap["snapshot_id"]


def _assert_locked(summary: dict) -> None:
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["predictive_claim_allowed"] is False


# --- 1. real price path attaches y=1 -------------------------------------- #

def test_due_decision_with_real_price_path_attaches_y_one(tmp_path):
    db = tmp_path / "mvp.db"
    sid = _seed_decision(db, "WIN")
    evidence = {sid: {"entry_price": 100.0, "exit_price": 110.0,
                      "target_return_threshold": 0.05, "is_real_outcome": True}}
    summary = attach_due_outcomes(db_path=db, evidence_by_id=evidence, now_utc=_NOW, write=True)
    assert summary["due_decisions"] == 1
    assert summary["outcomes_attached"] == 1
    assert summary["n_real_forward_after"] == 1
    rf = extract_datasets(db)["real_forward"]
    assert rf and rf[0]["y"] == 1
    _assert_locked(summary)


# --- 2. stop before target attaches y=0 ----------------------------------- #

def test_due_decision_stop_first_attaches_y_zero(tmp_path):
    db = tmp_path / "mvp.db"
    sid = _seed_decision(db, "LOSS")
    evidence = {sid: {"stop_loss_hit": True, "target_hit": False, "is_real_outcome": True}}
    summary = attach_due_outcomes(db_path=db, evidence_by_id=evidence, now_utc=_NOW, write=True)
    assert summary["outcomes_attached"] == 1
    rf = extract_datasets(db)["real_forward"]
    assert rf and rf[0]["y"] == 0


# --- 3. unelapsed horizon remains pending --------------------------------- #

def test_unelapsed_horizon_remains_pending(tmp_path):
    db = tmp_path / "mvp.db"
    # Decision "now", horizon 30 days -> not elapsed at _NOW.
    sid = _seed_decision(db, "EARLY", ts=_NOW, horizon=30.0)
    evidence = {sid: {"entry_price": 100.0, "exit_price": 110.0}}
    summary = attach_due_outcomes(db_path=db, evidence_by_id=evidence, now_utc=_NOW, write=True)
    assert summary["due_decisions"] == 0
    assert summary["pending"] == 1
    assert summary["outcomes_attached"] == 0
    assert summary["n_real_forward_after"] == 0


# --- 4. missing price evidence excluded with reason ----------------------- #

def test_missing_price_evidence_excluded_with_reason(tmp_path):
    db = tmp_path / "mvp.db"
    _seed_decision(db, "NOEV")
    # No evidence supplied for the due decision.
    summary = attach_due_outcomes(db_path=db, evidence_by_id={}, now_utc=_NOW, write=True)
    assert summary["due_decisions"] == 1
    assert summary["excluded"] == 1
    assert summary["outcomes_attached"] == 0
    reasons = [d.get("reason") for d in summary["details"]]
    assert REASON_NO_PRICE_EVIDENCE in reasons


# --- 5. open trade not labelled ------------------------------------------- #

def test_open_trade_not_labelled(tmp_path):
    db = tmp_path / "mvp.db"
    sid = _seed_decision(db, "OPEN")
    evidence = {sid: {"entry_price": 100.0, "exit_price": 120.0, "trade_open": True}}
    summary = attach_due_outcomes(db_path=db, evidence_by_id=evidence, now_utc=_NOW, write=True)
    assert summary["outcomes_attached"] == 0
    assert summary["pending"] == 1
    reasons = [d.get("reason") for d in summary["details"]]
    assert REASON_OPEN_TRADE in reasons
    assert extract_datasets(db)["real_forward"] == []


# --- 6. N_real_forward increments only for eligible pairs ----------------- #

def test_n_real_forward_increments_only_for_eligible_pairs(tmp_path):
    db = tmp_path / "mvp.db"
    win = _seed_decision(db, "W")
    openish = _seed_decision(db, "O")
    noev = _seed_decision(db, "N")
    evidence = {
        win: {"entry_price": 100.0, "exit_price": 110.0, "target_return_threshold": 0.05},
        openish: {"entry_price": 100.0, "exit_price": 110.0, "trade_open": True},
        # noev: no evidence -> excluded
    }
    summary = attach_due_outcomes(db_path=db, evidence_by_id=evidence, now_utc=_NOW, write=True)
    assert summary["n_real_forward_before"] == 0
    assert summary["n_real_forward_after"] == 1  # only the resolved WIN
    assert summary["outcomes_attached"] == 1
    assert summary["pending"] == 1
    assert summary["excluded"] == 1


# --- 7. advisory-only context preserved ----------------------------------- #

def test_outcome_attachment_preserves_advisory_only_context(tmp_path):
    db = tmp_path / "mvp.db"
    sid = _seed_decision(db, "A")
    summary = attach_due_outcomes(
        db_path=db,
        evidence_by_id={sid: {"entry_price": 100.0, "exit_price": 110.0}},
        now_utc=_NOW,
        write=True,
    )
    _assert_locked(summary)


# --- helper units --------------------------------------------------------- #

def test_horizon_elapsed_helper():
    import datetime as dt

    now = dt.datetime(2026, 5, 31, tzinfo=dt.timezone.utc)
    assert horizon_elapsed(decision_ts=_PAST, horizon_days=1.0, now_utc=now) is True
    assert horizon_elapsed(decision_ts=_NOW, horizon_days=30.0, now_utc=now) is False
    assert horizon_elapsed(decision_ts=None, horizon_days=1.0, now_utc=now) is False
    assert horizon_elapsed(decision_ts=_PAST, horizon_days=0, now_utc=now) is False


def test_compute_outcome_label_modes():
    # return mode
    y, reason = compute_outcome_label({"entry_price": 100, "exit_price": 110},
                                      target_return_threshold=0.05)
    assert y == 1 and reason is None
    # alpha mode (asset +10%, benchmark +20% -> alpha negative -> y=0)
    y, _ = compute_outcome_label({"entry_price": 100, "exit_price": 110,
                                  "benchmark_entry": 100, "benchmark_exit": 120},
                                 alpha_threshold=0.0)
    assert y == 0
    # ambiguous stop/target with no price -> None
    y, reason = compute_outcome_label({"stop_loss_hit": True, "target_hit": True})
    assert y is None and reason is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
