"""Score the Real Rows Sprint — Phase 6A tests for GET /evidence/scoring.

Exercise the pure read-only builder against a TEMP DB.  Prove it reports
scoring coverage, score-quality coverage, n_valid_p and the honest unavailable
reasons; keeps the predictive claim locked; never mutates the DB; preserves the
advisory-only stamps; contains no execution wording; degrades truthfully when
tables are missing; and never exposes secrets.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

import pytest

from scripts import persistence
from scripts.api.routers.evidence_router import build_scoring_payload
from scripts.run_daily_live_advisory_decisions import run_daily_decision_batch
from scripts.score_real_signal_events import score_real_signal_events


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recent_iso(hours_ago: float = 1.0) -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yf_payload():
    return {
        "source": "market_data_yahoo", "ticker": "AAPL",
        "latest_price": 190.0, "previous_close": 185.0, "price_change_pct": 2.7,
        "volume": 9e7, "average_volume": 6e7, "volume_change_ratio": 1.5,
        "timestamp": _recent_iso(1.0),
    }


@pytest.fixture()
def seeded_db(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    # Two scorable yfinance rows + one missing-price (unavailable) row.
    persistence.upsert_signal_event_observation(
        event_id="YF_AAPL", source_name="yfinance", raw_payload=_yf_payload(),
        fetched_at=_now(), db_path=db,
    )
    persistence.upsert_signal_event_observation(
        event_id="YF_MSFT", source_name="yfinance", raw_payload=_yf_payload(),
        fetched_at=_now(), db_path=db,
    )
    persistence.upsert_signal_event_observation(
        event_id="YF_NOPRICE", source_name="yfinance",
        raw_payload={"source": "yfinance", "ticker": "X", "timestamp": _recent_iso(1.0)},
        fetched_at=_now(), db_path=db,
    )
    score_real_signal_events(db_path=db, now_iso=_now(), write=True)
    # Record decisions so n_valid_p > 0.
    run_daily_decision_batch(
        db_path=db,
        events=[{"event_id": "YF_AAPL", "source_name": "yfinance", "raw_payload": {}},
                {"event_id": "YF_MSFT", "source_name": "yfinance", "raw_payload": {}}],
        write=True,
    )
    return db


# --- 1 + 2. coverage + quality coverage ----------------------------------- #
def test_evidence_scoring_route_reports_scoring_coverage(seeded_db):
    p = build_scoring_payload(db_path=seeded_db)
    assert p["mode"] == "LIVE"
    assert p["n_real_canonical_rows"] == 3
    assert p["n_scored_real_rows"] == 2
    assert p["scoring_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert "yfinance" in p["sources_scored"]


def test_evidence_scoring_route_reports_score_quality_coverage(seeded_db):
    p = build_scoring_payload(db_path=seeded_db)
    assert p["n_complete_score_vectors"] == 2
    assert p["score_quality_coverage"] == pytest.approx(2 / 3, abs=1e-6)


# --- 3. n_valid_p --------------------------------------------------------- #
def test_evidence_scoring_route_reports_n_valid_p(seeded_db):
    p = build_scoring_payload(db_path=seeded_db)
    assert p["n_valid_p"] == 2


# --- 4. unavailable reasons ----------------------------------------------- #
def test_evidence_scoring_route_reports_score_unavailable_reasons(seeded_db):
    p = build_scoring_payload(db_path=seeded_db)
    reasons = p["score_unavailable_reasons"]
    assert isinstance(reasons, dict)
    assert reasons.get("MISSING_PRICE") == 1


# --- 5. predictive claim locked ------------------------------------------- #
def test_evidence_scoring_route_predictive_claim_locked(seeded_db):
    p = build_scoring_payload(db_path=seeded_db)
    assert p["predictive_claim_allowed"] is False
    assert p["calibration_status"] == "INSUFFICIENT_EVIDENCE"
    assert p["predictive_claim_label"] == "PREDICTIVE_CLAIM_LOCKED"
    assert p["edge_claimed"] is False
    assert p["real_money_ready"] is False


# --- 6. read-only (no mutation) ------------------------------------------- #
def test_evidence_scoring_route_read_only(seeded_db):
    def _snapshot(db):
        conn = sqlite3.connect(str(db))
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            counts = {}
            for t in tables:
                counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            return counts
        finally:
            conn.close()

    before = _snapshot(seeded_db)
    for _ in range(3):
        build_scoring_payload(db_path=seeded_db)
    after = _snapshot(seeded_db)
    assert before == after


# --- 7. advisory stamps --------------------------------------------------- #
def test_evidence_scoring_route_preserves_advisory_stamps(seeded_db):
    p = build_scoring_payload(db_path=seeded_db)
    assert p["advisory_status"] == "ADVISORY_ONLY"
    assert p["human_execution_required"] is True
    assert p["execution_gate"] == "LOCKED"
    assert p["broker_api_called"] is False
    assert p["ai_execution_count"] == 0


# --- 8. no execution language --------------------------------------------- #
def test_evidence_scoring_route_has_no_execution_language(seeded_db):
    blob = json.dumps(build_scoring_payload(db_path=seeded_db)).lower()
    for word in ("place order", "broker_execute", "buy now", "sell now",
                 "execute trade", "order placed", "executable signal"):
        assert word not in blob


# --- 9. missing tables truthful ------------------------------------------- #
def test_evidence_scoring_route_handles_missing_tables_truthfully(tmp_path):
    db = tmp_path / "empty.db"  # never initialised
    p = build_scoring_payload(db_path=db)
    # The builder creates the side table on read (additive) but finds zero rows.
    assert p["mode"] in ("EMPTY", "DEGRADED")
    assert p["n_real_canonical_rows"] == 0
    assert p["n_scored_real_rows"] == 0
    assert p["n_valid_p"] == 0
    assert p["predictive_claim_allowed"] is False


# --- 10. no secrets ------------------------------------------------------- #
def test_evidence_scoring_route_does_not_expose_secrets(tmp_path):
    db = tmp_path / "mvp.db"
    persistence.init_schema(db)
    p = build_scoring_payload(db_path=db)
    keys = json.dumps(list(p.keys())).lower()
    for marker in ("api_key", "secret", "authorization", "password", "token", "bearer"):
        assert marker not in keys
