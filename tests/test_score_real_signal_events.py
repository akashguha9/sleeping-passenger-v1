"""Score the Real Rows Sprint — Phase 4 tests for the scoring runner.

These exercise the side-table scoring runner against a TEMP SQLite DB only — the
real runtime DB is never touched.  They assert real rows score, mock/backfill
rows are ignored, the run is idempotent, coverage math is correct, the safety
stamps survive, and no calibration / edge claim leaks in.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from scripts import persistence
from scripts.real_signal_score_vector import SCORED, SCORE_UNAVAILABLE
from scripts.score_real_signal_events import (
    SCORE_VECTOR_TABLE,
    count_score_vectors,
    fetch_score_vectors,
    score_real_signal_events,
)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recent_iso(hours_ago: float = 1.0) -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def temp_db(tmp_path):
    db = tmp_path / "score_runner.db"
    persistence.init_schema(db)
    return db


def _insert(db, event_id, source_name, payload, fetched_at=None):
    persistence.upsert_signal_event_observation(
        event_id=event_id,
        source_name=source_name,
        raw_payload=payload,
        fetched_at=fetched_at or _now(),
        db_path=db,
    )


def _yfinance_payload():
    return {
        "source": "market_data_yahoo",
        "ticker": "AAPL",
        "symbol": "AAPL",
        "latest_price": 190.0,
        "previous_close": 185.0,
        "price_change_pct": 2.7027,
        "volume": 90_000_000.0,
        "average_volume": 60_000_000.0,
        "volume_change_ratio": 1.5,
        "timestamp": _recent_iso(1.0),
    }


def _polymarket_payload():
    return {
        "source": "polymarket",
        "market_id": "0xabc",
        "question": "Will X happen?",
        "implied_probability": 0.72,
        "liquidity": 50_000.0,
        "timestamp": _recent_iso(2.0),
    }


def _sec_payload():
    return {
        "source": "sec_edgar",
        "cik": "0000320193",
        "entity_name": "Apple Inc.",
        "form_type": "8-K",
        "filing_date": _dt.date.today().isoformat(),
        "accession_number": "0000320193-26-000001",
    }


def _seed_three_real(db):
    _insert(db, "YF_AAPL", "yfinance", _yfinance_payload())
    _insert(db, "PM_0xabc", "polymarket", _polymarket_payload())
    _insert(db, "SEC_8K", "sec_edgar", _sec_payload())


# --------------------------------------------------------------------------- #
# 1. scores three real source rows
# --------------------------------------------------------------------------- #
def test_scores_real_yfinance_polymarket_sec_fixture_rows(temp_db):
    _seed_three_real(temp_db)
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["rows_seen"] == 3
    assert summary["rows_scored"] == 3
    assert summary["n_scored_real_rows"] == 3
    assert summary["n_complete_score_vectors"] == 3
    assert set(summary["sources_scored"]) == {"yfinance", "polymarket", "sec_edgar"}


# --------------------------------------------------------------------------- #
# 2. mock / backfill rows are not scored
# --------------------------------------------------------------------------- #
def test_does_not_score_mock_or_backfill_rows(temp_db):
    _insert(temp_db, "YF_REAL", "yfinance", _yfinance_payload())
    mock_payload = dict(_yfinance_payload())
    mock_payload["mock_flag"] = True
    _insert(temp_db, "YF_MOCK", "yfinance", mock_payload)
    backfill_payload = dict(_yfinance_payload())
    backfill_payload["backfill_flag"] = True
    _insert(temp_db, "YF_BACKFILL", "yfinance", backfill_payload)

    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["rows_seen"] == 3
    assert summary["mock_rows"] == 1
    assert summary["backfill_rows"] == 1
    assert summary["rows_scored"] == 1
    assert summary["n_real_canonical_rows"] == 1
    # Mock / backfill never reach the side table.
    persisted_events = {r["event_id"] for r in fetch_score_vectors(temp_db)}
    assert "YF_MOCK" not in persisted_events
    assert "YF_BACKFILL" not in persisted_events
    assert "YF_REAL" in persisted_events


# --------------------------------------------------------------------------- #
# 3. idempotent second run
# --------------------------------------------------------------------------- #
def test_idempotent_second_run_does_not_duplicate_scores(temp_db):
    _seed_three_real(temp_db)
    first = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    count_after_first = count_score_vectors(temp_db)
    second = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    count_after_second = count_score_vectors(temp_db)

    assert count_after_first == 3
    assert count_after_second == 3
    assert first["n_scored_real_rows"] == second["n_scored_real_rows"] == 3
    assert second["newly_persisted"] == 0  # nothing new on the second pass

    # Invariant: at most one row per score_key.
    rows = fetch_score_vectors(temp_db)
    keys = [r["score_key"] for r in rows]
    assert len(keys) == len(set(keys))


# --------------------------------------------------------------------------- #
# 4. unavailable reasons reported
# --------------------------------------------------------------------------- #
def test_scoring_summary_reports_unavailable_reasons(temp_db):
    # A yfinance row with no price at all => MISSING_PRICE.
    _insert(temp_db, "YF_NOPRICE", "yfinance", {
        "source": "yfinance", "ticker": "AAPL", "timestamp": _recent_iso(1.0),
    })
    # A polymarket row with no probability => MISSING_PROBABILITY.
    _insert(temp_db, "PM_NOPROB", "polymarket", {
        "source": "polymarket", "market_id": "x", "timestamp": _recent_iso(1.0),
    })
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["rows_scored"] == 0
    reasons = summary["score_unavailable_reasons"]
    assert reasons.get("MISSING_PRICE") == 1
    assert reasons.get("MISSING_PROBABILITY") == 1
    # The unavailable rows are still persisted as an honest audit trail.
    statuses = {r["event_id"]: r["score_status"] for r in fetch_score_vectors(temp_db)}
    assert statuses["YF_NOPRICE"] == SCORE_UNAVAILABLE
    assert statuses["PM_NOPROB"] == SCORE_UNAVAILABLE


# --------------------------------------------------------------------------- #
# 5. scoring coverage
# --------------------------------------------------------------------------- #
def test_scoring_coverage_computed_correctly(temp_db):
    # 2 real scorable + 1 missing-field real => coverage = 2/3.
    _insert(temp_db, "YF_AAPL", "yfinance", _yfinance_payload())
    _insert(temp_db, "PM_0xabc", "polymarket", _polymarket_payload())
    _insert(temp_db, "YF_NOPRICE", "yfinance", {
        "source": "yfinance", "ticker": "MSFT", "timestamp": _recent_iso(1.0),
    })
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["n_real_canonical_rows"] == 3
    assert summary["n_scored_real_rows"] == 2
    assert summary["scoring_coverage"] == pytest.approx(2 / 3, abs=1e-6)


# --------------------------------------------------------------------------- #
# 6. score quality coverage
# --------------------------------------------------------------------------- #
def test_score_quality_coverage_computed_correctly(temp_db):
    # 1 complete (SCORED) + 1 partial (no prev price, has confirmation proxy).
    _insert(temp_db, "YF_AAPL", "yfinance", _yfinance_payload())
    partial = {
        "source": "yfinance", "ticker": "MSFT", "latest_price": 400.0,
        "timestamp": _recent_iso(1.0), "market_confirmation_score": 0.5,
    }
    _insert(temp_db, "YF_PARTIAL", "yfinance", partial)
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["n_real_canonical_rows"] == 2
    # Both produce a usable vector (scored), but only one is CompleteScore.
    assert summary["rows_scored"] == 2
    assert summary["n_complete_score_vectors"] == 1
    assert summary["score_quality_coverage"] == pytest.approx(0.5, abs=1e-6)


# --------------------------------------------------------------------------- #
# 7. safety stamps preserved
# --------------------------------------------------------------------------- #
def test_scoring_preserves_safety_stamps(temp_db):
    _seed_three_real(temp_db)
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["advisory_status"] == "ADVISORY_ONLY"
    assert summary["human_execution_required"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0

    # Every persisted row carries the stamps too.
    for r in fetch_score_vectors(temp_db):
        assert r["advisory_status"] == "ADVISORY_ONLY"
        assert r["human_execution_required"] == 1
        assert r["execution_gate"] == "LOCKED"
        assert r["broker_api_called"] == 0
        assert r["ai_execution_count"] == 0


# --------------------------------------------------------------------------- #
# 8. no calibration / edge claim
# --------------------------------------------------------------------------- #
def test_scoring_runner_does_not_claim_calibration_or_edge(temp_db):
    _seed_three_real(temp_db)
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["predictive_claim_allowed"] is False
    assert summary["edge_claimed"] is False


# --------------------------------------------------------------------------- #
# 9. empty DB reports zero truthfully
# --------------------------------------------------------------------------- #
def test_empty_db_reports_zero_rows_truthfully(temp_db):
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)
    assert summary["rows_seen"] == 0
    assert summary["rows_scored"] == 0
    assert summary["rows_unscored"] == 0
    assert summary["n_real_canonical_rows"] == 0
    assert summary["scoring_coverage"] == 0.0
    assert summary["score_quality_coverage"] == 0.0
    assert summary["sources_scored"] == []


# --------------------------------------------------------------------------- #
# 10. vectors persist to the side table
# --------------------------------------------------------------------------- #
def test_score_vectors_persist_to_side_table(temp_db):
    _seed_three_real(temp_db)
    score_real_signal_events(db_path=temp_db, now_iso=_now(), write=True)

    rows = fetch_score_vectors(temp_db, event_id="YF_AAPL")
    assert len(rows) == 1
    row = rows[0]
    assert row["score_status"] == SCORED
    assert row["source_name"] == "yfinance"
    assert row["scoring_version"] == "real-row-score-v1"
    for axis in ("EMS", "EQS", "DS", "LS", "EFS", "APS"):
        assert row[axis] is not None
        assert 0.0 <= float(row[axis]) <= 1.0
    # The side table is separate from canonical signal_events.
    assert SCORE_VECTOR_TABLE == "signal_event_score_vectors"


def test_dry_run_does_not_persist(temp_db):
    _seed_three_real(temp_db)
    summary = score_real_signal_events(db_path=temp_db, now_iso=_now(), write=False)
    assert summary["rows_scored"] == 3
    assert summary["wrote_artifacts"] is False
    assert count_score_vectors(temp_db) == 0
