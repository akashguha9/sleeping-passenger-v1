"""Real-Forward Outcome Maturation Sprint — Phase 6 evidence-bundle tests.

The bundle now carries a ``real_forward_maturation`` section and a
``DailyMaturationLoopScore`` component.  The score must NOT inflate when
N_real_forward = 0, and the markdown must keep saying calibration is locked
below 200 and that the system is not real-money ready.
"""
from __future__ import annotations

import sqlite3

import pytest

from _forward_snapshot_helpers import (  # type: ignore[import-not-found]
    event_row,
    init_db,
    seed_market_bar,
    seed_score_vector,
)
from scripts import persistence
from scripts.real_evidence_bundle import (
    build_evidence_bundle,
    daily_maturation_loop_score,
    render_markdown,
)
from scripts.decision_probability_snapshot import persist_decision_snapshot, TABLE
from scripts.outcome_labeling_flow import _ensure_outcome_columns
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch


def _canary():
    return {"per_source": [], "C_global": 0.0, "live_canonical_count": 0}


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "mvp.db"
    init_db(p)
    return p


def _seed_attached_pair(db, sid, p, y):
    snap = {
        "snapshot_id": sid, "signal_id": sid, "timestamp_utc": "2026-05-10T00:00:00Z",
        "ticker": "AAPL", "prediction_horizon_days": 5.0,
        "target_event_definition": "forward_return_ge_threshold",
        "model_probability": p, "model_probability_reason": "OK",
        "score_vector": {}, "model_version": "m", "scoring_version": "s",
    }
    persist_decision_snapshot(snap, db)
    conn = sqlite3.connect(str(db))
    try:
        _ensure_outcome_columns(conn)
        conn.execute(
            f"UPDATE {TABLE} SET outcome_label=?, is_real_outcome=1,"
            f" outcome_kind='real_forward', horizon_elapsed=1 WHERE snapshot_id=?",
            (y, sid),
        )
        conn.commit()
    finally:
        conn.close()


def test_bundle_contains_maturation_section(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    assert "real_forward_maturation" in b
    mat = b["real_forward_maturation"]
    for key in (
        "n_forward_eligible", "n_pending_horizon", "n_due_forward",
        "n_real_forward_pairs", "outcomes_attached_last_run", "n_needed_to_200",
        "brier_real_forward", "ece_real_forward", "logloss_real_forward",
        "calibration_status", "predictive_claim_allowed", "next_due_in_hours",
        "limitations",
    ):
        assert key in mat


def test_bundle_reports_n_real_forward_pairs(db):
    _seed_attached_pair(db, "rf1", 0.6, 1)
    _seed_attached_pair(db, "rf2", 0.4, 0)
    b = build_evidence_bundle(db, canary_report=_canary())
    assert b["real_forward_maturation"]["n_real_forward_pairs"] == 2
    assert b["real_forward_maturation"]["n_needed_to_200"] == 198


def test_bundle_reports_next_due_in_hours(db):
    # A fresh live snapshot has an open horizon -> a positive next-due figure.
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    seed_score_vector(db, event_id="ev1", ticker="AAPL")
    seed_market_bar(db, symbol="AAPL", timestamp=iso(now - timedelta(days=1)), close=190.0)
    run_daily_decision_batch(
        db_path=db, events=[event_row("ev1", payload={})], now_iso=iso(now), write=True
    )
    b = build_evidence_bundle(db, canary_report=_canary())
    assert b["real_forward_maturation"]["next_due_in_hours"] is not None
    assert b["real_forward_maturation"]["next_due_in_hours"] > 0


def test_bundle_score_does_not_inflate_when_n_zero(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    # Outcome coverage and calibration gate are zero with no real pairs.
    comps = b["s_evidence"]["components"]
    assert comps["outcome_coverage"] == 0.0
    assert comps["calibration_gate_score"] == 0.0
    assert b["real_forward_maturation"]["n_real_forward_pairs"] == 0
    # The score cannot exceed the sum of the non-outcome, non-calibration weights.
    assert b["s_evidence"]["score"] <= 1.0 - 0.20 - 0.18 + 1e-9


def test_bundle_score_increases_when_real_pairs_exist(db):
    base = build_evidence_bundle(db, canary_report=_canary())["s_evidence"]["score"]
    for i in range(4):
        _seed_attached_pair(db, f"rf{i}", 0.6 if i % 2 else 0.4, i % 2)
    after = build_evidence_bundle(db, canary_report=_canary())["s_evidence"]["score"]
    # OutcomeCoverage = 4/200 > 0 raises the score (calibration gate still 0).
    assert after > base


def test_daily_maturation_loop_score_locked_invariant():
    # Below 200 with an honest locked claim -> full loop score.
    assert daily_maturation_loop_score(
        n_real_forward=3, predictive_claim_allowed=False
    ) == 1.0
    # A sub-200 corpus that (wrongly) reports a claim breaks the invariant -> 0.
    assert daily_maturation_loop_score(
        n_real_forward=3, predictive_claim_allowed=True
    ) == 0.0


def test_markdown_says_calibration_locked_below_200(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    md = render_markdown(b).lower()
    assert "locked" in md
    assert "below n=200" in md or "n=200" in md


def test_markdown_says_no_real_money_ready(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    md = render_markdown(b).lower()
    assert "not real-money ready" in md


def test_bundle_preserves_advisory_only_stamps(db):
    b = build_evidence_bundle(db, canary_report=_canary())
    assert b["advisory_status"] == "ADVISORY_ONLY"
    assert b["execution_gate"] == "LOCKED"
    assert b["broker_api_called"] is False
    assert b["ai_execution_count"] == 0
    assert b["real_money_ready"] is False
    assert b["predictive_claim_allowed"] is False
