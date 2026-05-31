"""Score the Real Rows Sprint — Phase 5 tests for the scored-row decision batch.

These prove the daily advisory decision batch now consumes persisted score
vectors: a real row with a CompleteScore vector records a model_probability and
grows ``n_valid_p``; a row with no vector or an incomplete vector records NULL
with an explicit reason (never a fabricated probability); the probability uses
all six axes, stays in [0, 1], and the predictive claim stays locked.  All
deterministic and offline against a TEMP DB.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

import pytest

from scripts import persistence
from scripts.decision_probability_snapshot import TABLE as SNAPSHOT_TABLE
from scripts.decision_probability_snapshot import count_valid_p
from scripts.run_daily_live_advisory_decisions import (
    SCORE_VECTOR_INCOMPLETE,
    SCORE_VECTOR_MISSING,
    run_daily_decision_batch,
)
from scripts.score_real_signal_events import (
    count_score_vectors,
    score_real_signal_events,
)

_AXES = ("EMS", "EQS", "DS", "LS", "EFS", "APS")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recent_iso(hours_ago: float = 1.0) -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def temp_db(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    return db


def _yfinance_payload():
    return {
        "source": "market_data_yahoo",
        "ticker": "AAPL",
        "latest_price": 190.0,
        "previous_close": 185.0,
        "price_change_pct": 2.7027,
        "volume": 90_000_000.0,
        "average_volume": 60_000_000.0,
        "volume_change_ratio": 1.5,
        "timestamp": _recent_iso(1.0),
    }


def _seed_and_score(db, event_id="YF_AAPL", source="yfinance", payload=None):
    persistence.upsert_signal_event_observation(
        event_id=event_id, source_name=source,
        raw_payload=payload or _yfinance_payload(), fetched_at=_now(), db_path=db,
    )
    score_real_signal_events(db_path=db, now_iso=_now(), write=True)


def _event(event_id, source="yfinance", payload=None):
    return {"event_id": event_id, "source_name": source,
            "raw_payload": payload if payload is not None else {"headline": "x"}}


def _assert_locked(summary):
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert summary["human_execution_required"] is True
    assert summary["predictive_claim_allowed"] is False


# --------------------------------------------------------------------------- #
# 1. scored real row records a model_probability
# --------------------------------------------------------------------------- #
def test_scored_real_row_records_model_probability(temp_db):
    _seed_and_score(temp_db, "YF_AAPL")
    summary = run_daily_decision_batch(
        db_path=temp_db, events=[_event("YF_AAPL")], write=True,
    )
    assert summary["decisions_recorded"] == 1
    assert summary["decisions_with_score_vector"] == 1
    assert count_valid_p(temp_db) >= 1


# --------------------------------------------------------------------------- #
# 2. batch grows n_valid_p from scored rows
# --------------------------------------------------------------------------- #
def test_daily_batch_increments_n_valid_p_from_scored_rows(temp_db):
    _seed_and_score(temp_db, "YF_AAPL")
    _seed_and_score(temp_db, "YF_MSFT")
    summary = run_daily_decision_batch(
        db_path=temp_db, events=[_event("YF_AAPL"), _event("YF_MSFT")], write=True,
    )
    assert summary["n_valid_p_before"] == 0
    assert summary["n_valid_p_after"] == 2
    assert summary["delta_n_valid_p"] == 2
    assert summary["decisions_with_score_vector"] == 2


# --------------------------------------------------------------------------- #
# 3. unscored real row -> NULL with reason
# --------------------------------------------------------------------------- #
def test_unscored_real_row_records_probability_null_with_reason(temp_db):
    summary = run_daily_decision_batch(
        db_path=temp_db, events=[_event("NO_VECTOR")], write=True,
    )
    assert summary["decisions_recorded"] == 1
    assert summary["delta_n_valid_p"] == 0
    assert summary["decisions_missing_score_vector"] == 1
    assert summary["probability_unavailable_reasons"].get(SCORE_VECTOR_MISSING) == 1
    assert count_valid_p(temp_db) == 0


# --------------------------------------------------------------------------- #
# 4. incomplete score vector -> NULL with reason
# --------------------------------------------------------------------------- #
def test_incomplete_score_vector_records_probability_null_with_reason(temp_db):
    # A yfinance row with no price persists a SCORE_UNAVAILABLE (incomplete) row.
    persistence.upsert_signal_event_observation(
        event_id="YF_NOPRICE", source_name="yfinance",
        raw_payload={"source": "yfinance", "ticker": "AAPL", "timestamp": _recent_iso(1.0)},
        fetched_at=_now(), db_path=temp_db,
    )
    score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    # Even if we pass payload axes, the persisted incomplete vector wins -> NULL.
    summary = run_daily_decision_batch(
        db_path=temp_db,
        events=[_event("YF_NOPRICE", payload={"axes": {a: 0.5 for a in _AXES}})],
        write=True,
    )
    assert summary["decisions_incomplete_score_vector"] == 1
    assert summary["probability_unavailable_reasons"].get(SCORE_VECTOR_INCOMPLETE) == 1
    assert summary["delta_n_valid_p"] == 0
    assert count_valid_p(temp_db) == 0


# --------------------------------------------------------------------------- #
# 5. probability in [0, 1]
# --------------------------------------------------------------------------- #
def test_probability_between_zero_and_one(temp_db):
    _seed_and_score(temp_db, "YF_AAPL")
    run_daily_decision_batch(db_path=temp_db, events=[_event("YF_AAPL")], write=True)
    conn = sqlite3.connect(str(temp_db))
    try:
        mps = [r[0] for r in conn.execute(
            f"SELECT model_probability FROM {SNAPSHOT_TABLE} WHERE model_probability IS NOT NULL"
        ).fetchall()]
    finally:
        conn.close()
    assert mps
    for p in mps:
        assert 0.0 <= float(p) <= 1.0


# --------------------------------------------------------------------------- #
# 6. probability uses all six axes
# --------------------------------------------------------------------------- #
def test_probability_uses_all_six_axes(temp_db):
    base = {a: 0.5 for a in _AXES}

    def _p_for(signal_id, axes):
        # Use the payload-axes fallback path so we can vary one axis at a time.
        # A unique signal_id per call avoids snapshot_id collisions.
        run_daily_decision_batch(
            db_path=temp_db, events=[_event(signal_id, payload={"axes": axes})], write=True,
        )
        conn = sqlite3.connect(str(temp_db))
        try:
            row = conn.execute(
                f"SELECT model_probability FROM {SNAPSHOT_TABLE} WHERE signal_id=?"
                " ORDER BY timestamp_utc DESC LIMIT 1",
                (signal_id,),
            ).fetchone()
        finally:
            conn.close()
        return float(row[0])

    p_base = _p_for("AX_BASE", dict(base))
    for axis in _AXES:
        bumped = dict(base)
        bumped[axis] = 0.9
        assert _p_for(f"AX_{axis}", bumped) != pytest.approx(p_base, abs=1e-9), axis


# --------------------------------------------------------------------------- #
# 7. predictive claim stays locked below N=200
# --------------------------------------------------------------------------- #
def test_predictive_claim_stays_locked_below_200(temp_db):
    _seed_and_score(temp_db, "YF_AAPL")
    summary = run_daily_decision_batch(
        db_path=temp_db, events=[_event("YF_AAPL")], write=True,
    )
    assert summary["predictive_claim_allowed"] is False
    assert summary["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert count_valid_p(temp_db) < 200


# --------------------------------------------------------------------------- #
# 8. decision snapshot includes the score vector
# --------------------------------------------------------------------------- #
def test_decision_snapshot_includes_score_vector(temp_db):
    _seed_and_score(temp_db, "YF_AAPL")
    run_daily_decision_batch(db_path=temp_db, events=[_event("YF_AAPL")], write=True)
    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            f"SELECT score_vector_json, model_probability FROM {SNAPSHOT_TABLE}"
            " WHERE signal_id='YF_AAPL' ORDER BY timestamp_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    score_vector = json.loads(row[0] or "{}")
    for axis in _AXES:
        assert axis in score_vector
    assert row[1] is not None  # model_probability persisted


# --------------------------------------------------------------------------- #
# 9. no execution fields unlocked
# --------------------------------------------------------------------------- #
def test_no_execution_fields_unlocked(temp_db):
    _seed_and_score(temp_db, "YF_AAPL")
    summary = run_daily_decision_batch(
        db_path=temp_db, events=[_event("YF_AAPL")], write=True,
    )
    _assert_locked(summary)
    blob = json.dumps(summary).lower()
    for word in ("place order", "broker_execute", "buy now", "sell now", "execute trade"):
        assert word not in blob


# --------------------------------------------------------------------------- #
# 10. summary reports the score-vector counts
# --------------------------------------------------------------------------- #
def test_batch_summary_reports_score_vector_counts(temp_db):
    _seed_and_score(temp_db, "YF_AAPL")  # one complete vector
    summary = run_daily_decision_batch(
        db_path=temp_db,
        events=[_event("YF_AAPL"), _event("NO_VECTOR")],
        write=True,
    )
    assert summary["scored_rows_available"] == count_score_vectors(temp_db, complete_only=True)
    assert summary["decisions_with_score_vector"] == 1
    assert summary["decisions_missing_score_vector"] == 1
    assert summary["decisions_incomplete_score_vector"] == 0
    assert "score_vector_missing" in {k.lower() for k in summary["probability_unavailable_reasons"]}


# --------------------------------------------------------------------------- #
# 11. empty score table handled truthfully
# --------------------------------------------------------------------------- #
def test_batch_handles_empty_score_table_truthfully(temp_db):
    summary = run_daily_decision_batch(db_path=temp_db, events=[], write=True)
    assert summary["reason"] == "NO_FRESH_CANONICAL_ROWS"
    assert summary["scored_rows_available"] == 0
    assert summary["decisions_with_score_vector"] == 0
    assert summary["decisions_missing_score_vector"] == 0
    assert summary["delta_n_valid_p"] == 0
    _assert_locked(summary)
