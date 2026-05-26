"""Tests for the Kalshi semantic-freshness classifier + persistence upsert.

Covers the new truth model that splits "Kalshi API health" from
"canonical signal_events freshness".  All tests are deterministic; no
network; no real Kalshi config required.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from scripts.kalshi_semantic_freshness import (
    API_HEALTH_AUTH_FAILED,
    API_HEALTH_LIVE_VERIFIED,
    API_HEALTH_MISSING,
    API_HEALTH_STALE,
    CANONICAL_DUPLICATE_REFRESHED,
    CANONICAL_FILTERED,
    CANONICAL_HEALTH_ONLY,
    CANONICAL_LIVE,
    CANONICAL_MISSING,
    CANONICAL_STALE,
    CANONICAL_ZERO_FRESH_ROWS,
    RESULT_DEGRADED_FILTERED,
    RESULT_DEGRADED_HEALTH_ONLY,
    RESULT_DEGRADED_ZERO_CANONICAL,
    RESULT_ERROR,
    RESULT_OK_INSERTED,
    RESULT_OK_REFRESHED,
    build_kalshi_truth,
    classify_api_health,
    classify_canonical_signal,
    classify_provider_result,
    load_health_artifact,
)
from scripts.persistence import (
    count_fresh_signal_events_by_source,
    upsert_signal_event_observation,
)


def _now() -> dt.datetime:
    return dt.datetime(2026, 5, 26, 20, 30, 0, tzinfo=dt.timezone.utc)


def _write_health(tmp_path: Path, **overrides) -> Path:
    payload = {
        "source_name": "kalshi",
        "artifact_kind": "kalshi_source_health",
        "completed_at_utc": _now().isoformat(),
        "status": "OK",
        "source_freshness_status": "LIVE_VERIFIED",
        "records_seen_total": 20,
        "records_allowed": 1,
        "records_quarantined": 19,
    }
    payload.update(overrides)
    p = tmp_path / "kalshi_source_health.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Classifier — DEGRADED_FILTERED
# ---------------------------------------------------------------------------


def test_kalshi_ok_filtered_zero_rows_is_degraded(tmp_path):
    """records_seen>0, records_allowed=0, rows_added=0 -> DEGRADED_FILTERED."""
    health = _write_health(
        tmp_path,
        records_seen_total=20,
        records_allowed=0,
        records_quarantined=20,
    )
    truth = build_kalshi_truth(
        health_path=health,
        canonical_stats={"fresh_count": 0, "latest_fetched_at": None, "latest_age_hours": None},
        rows_added=0,
        rows_refreshed=0,
        records_seen_total=20,
        records_allowed=0,
        records_quarantined=20,
        now=_now(),
    )
    assert truth["api_health_status"] == API_HEALTH_LIVE_VERIFIED
    assert truth["canonical_signal_status"] == CANONICAL_FILTERED
    assert truth["provider_result"] == RESULT_DEGRADED_FILTERED
    assert truth["degraded"] is True
    assert "filtered" in truth["operator_message"].lower() or "quarantined" in truth["operator_message"].lower()


# ---------------------------------------------------------------------------
# Classifier — DEGRADED_ZERO_CANONICAL
# ---------------------------------------------------------------------------


def test_kalshi_accepted_but_zero_canonical_write_is_degraded(tmp_path):
    health = _write_health(tmp_path)
    truth = build_kalshi_truth(
        health_path=health,
        canonical_stats={"fresh_count": 0, "latest_fetched_at": None, "latest_age_hours": None},
        rows_added=0,
        rows_refreshed=0,
        records_seen_total=20,
        records_allowed=1,
        records_quarantined=19,
        now=_now(),
    )
    assert truth["api_health_status"] == API_HEALTH_LIVE_VERIFIED
    assert truth["canonical_signal_status"] == CANONICAL_ZERO_FRESH_ROWS
    assert truth["provider_result"] == RESULT_DEGRADED_ZERO_CANONICAL
    assert truth["degraded"] is True


# ---------------------------------------------------------------------------
# Persistence — duplicate refresh updates fetched_at
# ---------------------------------------------------------------------------


def test_kalshi_duplicate_refresh_updates_fetched_at(tmp_path, monkeypatch):
    db = tmp_path / "duplicate_refresh.db"
    import scripts.persistence as persistence

    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)

    payload = {"event_id": "kalshi_ABC", "title": "Sample Kalshi Market"}
    old_ts = "2026-05-24T20:00:00+00:00"
    added, refreshed = upsert_signal_event_observation(
        event_id="kalshi_ABC",
        source_name="kalshi",
        raw_payload=payload,
        fetched_at=old_ts,
        db_path=db,
    )
    assert (added, refreshed) == (1, 0)

    new_ts = "2026-05-26T20:30:00+00:00"
    added2, refreshed2 = upsert_signal_event_observation(
        event_id="kalshi_ABC",
        source_name="kalshi",
        raw_payload=payload,
        fetched_at=new_ts,
        db_path=db,
    )
    assert (added2, refreshed2) == (0, 1)
    stats = count_fresh_signal_events_by_source(
        source_name="kalshi", ttl_hours=6.0, now_iso=new_ts, db_path=db
    )
    assert stats["fresh_count"] == 1
    assert stats["latest_fetched_at"] == new_ts


# ---------------------------------------------------------------------------
# Persistence — new accepted market inserts row with safety stamps
# ---------------------------------------------------------------------------


def test_kalshi_new_accepted_market_inserts_signal_event(tmp_path, monkeypatch):
    db = tmp_path / "new_insert.db"
    import scripts.persistence as persistence

    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)

    ts = "2026-05-26T20:30:00+00:00"
    payload = {
        "event_id": "kalshi_new1",
        "title": "Fresh Kalshi Market",
        "category": "Crypto",
    }
    added, refreshed = upsert_signal_event_observation(
        event_id="kalshi_new1",
        source_name="kalshi",
        raw_payload=payload,
        fetched_at=ts,
        db_path=db,
    )
    assert added == 1
    assert refreshed == 0

    # Read the row back and assert advisory invariants.
    rows = persistence.get_signal_events(source_name="kalshi", db_path=db)
    assert len(rows) == 1
    row = rows[0]
    assert row["source_name"] == "kalshi"
    assert row["advisory_status"] == "ADVISORY_ONLY"
    assert bool(row["human_review_required"]) is True
    assert row["execution_gate"] == "LOCKED"
    assert int(row["ai_execution_count"]) == 0
    # No secrets in the payload — sanity check the payload is the dict
    # we passed in, not auth headers.
    assert row["raw_payload"]["event_id"] == "kalshi_new1"


# ---------------------------------------------------------------------------
# Semantic freshness with only source-health live (no canonical rows)
# ---------------------------------------------------------------------------


def test_kalshi_semantic_freshness_accepts_source_health_when_canonical_absent(tmp_path):
    health = _write_health(tmp_path)
    truth = build_kalshi_truth(
        health_path=health,
        canonical_stats={"fresh_count": 0, "latest_fetched_at": None, "latest_age_hours": None},
        rows_added=0,
        rows_refreshed=0,
        records_seen_total=0,
        records_allowed=0,
        records_quarantined=0,
        expected_canonical_write=False,
        now=_now(),
    )
    assert truth["api_health_status"] == API_HEALTH_LIVE_VERIFIED
    assert truth["canonical_signal_status"] in {
        CANONICAL_HEALTH_ONLY,
        CANONICAL_MISSING,
        CANONICAL_STALE,
        CANONICAL_ZERO_FRESH_ROWS,
    }
    assert truth["semantic_fresh"] is True


def test_kalshi_semantic_freshness_stale_when_both_stale(tmp_path):
    # Old artifact (>>TTL).
    old_ts = (_now() - dt.timedelta(hours=48)).isoformat()
    health = _write_health(
        tmp_path,
        completed_at_utc=old_ts,
        source_freshness_status="LIVE_VERIFIED",
    )
    truth = build_kalshi_truth(
        health_path=health,
        canonical_stats={
            "fresh_count": 0,
            "latest_fetched_at": old_ts,
            "latest_age_hours": 48.0,
        },
        rows_added=0,
        rows_refreshed=0,
        records_seen_total=0,
        records_allowed=0,
        records_quarantined=0,
        now=_now(),
    )
    assert truth["api_health_status"] in {API_HEALTH_STALE, API_HEALTH_MISSING}
    assert truth["canonical_signal_status"] in {CANONICAL_STALE, CANONICAL_MISSING}
    assert truth["semantic_fresh"] is False


# ---------------------------------------------------------------------------
# Direct enum coverage
# ---------------------------------------------------------------------------


def test_classify_canonical_signal_live(tmp_path):
    result = classify_canonical_signal(
        canonical_live_count=3,
        latest_canonical_fetched_at=_now().isoformat(),
        latest_canonical_age_hours=0.1,
        rows_added=0,
        rows_refreshed=2,
        records_seen_total=10,
        records_allowed=2,
        records_quarantined=8,
        source_health_live=True,
    )
    assert result == CANONICAL_DUPLICATE_REFRESHED


def test_classify_provider_result_inserted():
    assert (
        classify_provider_result(
            rows_added=1,
            rows_refreshed=0,
            records_seen_total=5,
            records_allowed=1,
            records_quarantined=4,
            canonical_signal_fresh=True,
            source_health_live=True,
        )
        == RESULT_OK_INSERTED
    )


def test_classify_provider_result_refreshed():
    assert (
        classify_provider_result(
            rows_added=0,
            rows_refreshed=2,
            records_seen_total=5,
            records_allowed=2,
            records_quarantined=3,
            canonical_signal_fresh=True,
            source_health_live=True,
        )
        == RESULT_OK_REFRESHED
    )


def test_classify_provider_result_health_only_only_when_no_write_expected():
    assert (
        classify_provider_result(
            rows_added=0,
            rows_refreshed=0,
            records_seen_total=0,
            records_allowed=0,
            records_quarantined=0,
            canonical_signal_fresh=False,
            source_health_live=True,
            expected_canonical_write=False,
        )
        == RESULT_DEGRADED_HEALTH_ONLY
    )


def test_classify_api_health_missing_when_file_absent(tmp_path):
    artifact = load_health_artifact(tmp_path / "nonexistent.json")
    status, age = classify_api_health(artifact, _now(), 6.0)
    assert status == API_HEALTH_MISSING
    assert age is None


def test_classify_api_health_auth_failed(tmp_path):
    p = tmp_path / "kalshi_source_health.json"
    p.write_text(
        json.dumps(
            {
                "source_freshness_status": "SOURCE_ERROR",
                "error_type": "KalshiAuthError",
                "completed_at_utc": _now().isoformat(),
            }
        ),
        encoding="utf-8",
    )
    artifact = load_health_artifact(p)
    status, _age = classify_api_health(artifact, _now(), 6.0)
    assert status == API_HEALTH_AUTH_FAILED
