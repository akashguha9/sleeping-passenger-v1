"""Real-Forward Outcome Maturation Sprint — Phase 1 scanner tests.

The scanner is read-only: it classifies forward-eligible snapshots by maturity
state, reports when the next horizon becomes due, and never mutates or claims
calibration.
"""
from __future__ import annotations

import json

import pytest

from scripts.forward_outcome_maturity_scanner import (
    STATE_ATTACHED,
    STATE_DUE_FORWARD,
    STATE_INELIGIBLE,
    STATE_PENDING_HORIZON,
    classify_snapshot,
    scan_forward_outcome_maturity,
)
from scripts import persistence
from scripts.decision_probability_snapshot import (
    persist_decision_snapshot,
    stamp_forward_contract,
    TABLE,
)
from datetime import datetime, timezone

_NOW = "2026-05-31T12:00:00Z"


def _row(
    sid: str,
    *,
    decision_ts: str = "2026-05-28T00:00:00Z",
    horizon_days: float = 5.0,
    p: float | None = 0.6,
    eligible: int = 1,
    reason: str | None = None,
    horizon_close: str | None = None,
    outcome_label=None,
    is_real_outcome=None,
    outcome_kind=None,
) -> dict:
    return {
        "snapshot_id": sid,
        "timestamp_utc": decision_ts,
        "prediction_horizon_days": horizon_days,
        "model_probability": p,
        "horizon_close_utc": horizon_close,
        "forward_outcome_eligible": eligible,
        "forward_outcome_unavailable_reason": reason,
        "outcome_label": outcome_label,
        "is_real_outcome": is_real_outcome,
        "outcome_kind": outcome_kind,
    }


def test_scanner_counts_pending_horizon():
    # Eligible, horizon 5d from 05-28 closes 06-02 — still open at 05-31.
    rows = [_row("s1"), _row("s2")]
    out = scan_forward_outcome_maturity(rows=rows, now_utc=_NOW)
    assert out["n_pending_horizon"] == 2
    assert out["n_due_forward"] == 0
    assert out["n_forward_eligible"] == 2
    assert out["pending_by_date"].get("2026-06-02") == 2


def test_scanner_counts_due_forward():
    # Decision 05-20 + 5d = 05-25 close, elapsed by 05-31 -> DUE_FORWARD.
    rows = [_row("due1", decision_ts="2026-05-20T00:00:00Z")]
    out = scan_forward_outcome_maturity(rows=rows, now_utc=_NOW)
    assert out["n_due_forward"] == 1
    assert out["due_snapshot_ids"] == ["due1"]
    assert out["next_due_in_hours"] == 0.0
    assert out["can_attach_today"] is True


def test_scanner_counts_attached_real_forward():
    rows = [
        _row("a1", outcome_label=1, is_real_outcome=1, outcome_kind="real_forward"),
        _row("a2", outcome_label=0, is_real_outcome=1, outcome_kind="real_forward"),
        _row("p1"),
    ]
    out = scan_forward_outcome_maturity(rows=rows, now_utc=_NOW)
    assert out["n_attached_real_forward"] == 2
    assert out["n_real_forward_pairs"] == 2
    assert out["n_needed_to_200"] == 198
    assert out["n_pending_horizon"] == 1


def test_scanner_reports_earliest_horizon_close():
    rows = [
        _row("s1", decision_ts="2026-05-28T00:00:00Z"),  # closes 06-02
        _row("s2", decision_ts="2026-05-29T00:00:00Z"),  # closes 06-03
    ]
    out = scan_forward_outcome_maturity(rows=rows, now_utc=_NOW)
    assert out["earliest_horizon_close_utc"] == "2026-06-02T00:00:00Z"


def test_scanner_reports_next_due_in_hours():
    # Closes 06-02 00:00; now 05-31 12:00 -> 36 hours.
    rows = [_row("s1", decision_ts="2026-05-28T00:00:00Z")]
    out = scan_forward_outcome_maturity(rows=rows, now_utc=_NOW)
    assert out["next_due_in_hours"] == pytest.approx(36.0, abs=0.01)
    assert out["n_due_forward"] == 0


def test_scanner_ineligible_reasons_grouped():
    rows = [
        _row("i1", eligible=0, reason="MISSING_TICKER"),
        _row("i2", eligible=0, reason="MISSING_TICKER"),
        _row("i3", eligible=0, reason="MISSING_ENTRY_PRICE"),
    ]
    out = scan_forward_outcome_maturity(rows=rows, now_utc=_NOW)
    assert out["n_ineligible"] == 3
    assert out["ineligible_reasons"] == {"MISSING_TICKER": 2, "MISSING_ENTRY_PRICE": 1}


def test_scanner_does_not_backdate(tmp_path):
    # Seed a real DB snapshot, stamp it forward-eligible, scan, and confirm the
    # decision timestamp is untouched and no outcome was fabricated.
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    snap = {
        "snapshot_id": "DPS_x", "signal_id": "sig1",
        "timestamp_utc": "2026-05-28T00:00:00Z", "ticker": "AAPL",
        "prediction_horizon_days": 5.0,
        "target_event_definition": "forward_return_ge_threshold",
        "model_probability": 0.6, "model_probability_reason": "OK",
        "score_vector": {}, "model_version": "m", "scoring_version": "s",
    }
    persist_decision_snapshot(snap, db)
    stamp_forward_contract(
        db, "DPS_x", entry_price=190.0,
        entry_price_timestamp_utc="2026-05-27T00:00:00Z",
        target_event_definition="forward_return_ge_threshold",
    )
    import sqlite3

    def read_ts():
        conn = sqlite3.connect(str(db))
        try:
            r = conn.execute(
                f"SELECT timestamp_utc, outcome_label FROM {TABLE} WHERE snapshot_id='DPS_x'"
            ).fetchone()
            return r
        finally:
            conn.close()

    before = read_ts()
    out = scan_forward_outcome_maturity(db_path=db, now_utc=_NOW)
    after = read_ts()
    assert before == after  # no mutation, no backdating
    assert after[0] == "2026-05-28T00:00:00Z"
    assert after[1] is None  # never fabricated an outcome
    assert out["n_forward_eligible"] == 1


def test_scanner_preserves_advisory_only_stamps():
    out = scan_forward_outcome_maturity(rows=[_row("s1")], now_utc=_NOW)
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["human_execution_required"] is True
    assert out["predictive_claim_allowed"] is False


def test_scanner_has_no_execution_language():
    out = scan_forward_outcome_maturity(
        rows=[_row("s1"), _row("d1", decision_ts="2026-05-20T00:00:00Z")],
        now_utc=_NOW,
    )
    blob = json.dumps(out).lower()
    for forbidden in (
        "place order", "execute trade", "auto-trade", "buy now", "sell now",
        "broker api called\": true", "real_money_ready\": true",
    ):
        assert forbidden not in blob


def test_classify_snapshot_states():
    now = datetime(2026, 5, 31, 12, tzinfo=timezone.utc)
    assert classify_snapshot(_row("a", outcome_label=1, is_real_outcome=1,
                                  outcome_kind="real_forward"), now) == STATE_ATTACHED
    assert classify_snapshot(_row("d", decision_ts="2026-05-20T00:00:00Z"), now) == STATE_DUE_FORWARD
    assert classify_snapshot(_row("p"), now) == STATE_PENDING_HORIZON
    assert classify_snapshot(_row("i", eligible=0), now) == STATE_INELIGIBLE
