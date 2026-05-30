"""Objective 9 — source freshness / canonical-truth contract tests."""
from __future__ import annotations

from scripts.source_freshness_contract import (
    BACKFILL_NON_FRESH,
    LIVE_CANONICAL,
    MOCK_NON_CANONICAL,
    OK_FILTERED,
    STALE,
    ZERO_FRESH_ROWS,
    classify_canonical_status,
    freshness_score,
)


def test_api_ok_zero_rows_is_degraded():
    res = classify_canonical_status(
        api_health_status="OK", rows_added=0, age_hours=1.0,
    )
    assert res["api_health_ok"] is True
    assert res["live_canonical"] is False
    assert res["canonical_signal_status"] == ZERO_FRESH_ROWS


def test_backfill_rows_do_not_count_as_live_fresh():
    res = classify_canonical_status(
        api_health_status="OK", rows_added=13_000, age_hours=1.0,
        backfill_only=True,
    )
    assert res["live_canonical"] is False
    assert res["canonical_signal_status"] == BACKFILL_NON_FRESH
    assert res["C_s"] == 0.0


def test_mock_rows_do_not_count_as_canonical():
    res = classify_canonical_status(
        api_health_status="OK", rows_added=5, age_hours=0.5, mock_flag=True,
    )
    assert res["live_canonical"] is False
    assert res["canonical_signal_status"] == MOCK_NON_CANONICAL


def test_filtered_rows_are_not_live_canonical():
    res = classify_canonical_status(
        api_health_status="OK", rows_added=3, age_hours=0.5, filtered=True,
    )
    assert res["live_canonical"] is False
    assert res["canonical_signal_status"] == OK_FILTERED


def test_latest_canonical_timestamp_drives_freshness():
    # Same source, different ages -> fresh vs stale is a pure function of age.
    fresh = classify_canonical_status(
        api_health_status="OK", rows_added=2, age_hours=1.0, ttl_hours=24.0,
    )
    stale = classify_canonical_status(
        api_health_status="OK", rows_added=2, age_hours=48.0, ttl_hours=24.0,
    )
    assert fresh["canonical_signal_status"] == LIVE_CANONICAL
    assert stale["canonical_signal_status"] == STALE
    # Monotone decay.
    assert freshness_score(1.0, 24.0) > freshness_score(48.0, 24.0)


def test_genuinely_live_source_is_live_canonical():
    res = classify_canonical_status(
        api_health_status="LIVE_VERIFIED", rows_added=7, age_hours=2.0,
    )
    assert res["live_canonical"] is True
    assert res["canonical_signal_status"] == LIVE_CANONICAL
    assert res["C_s"] > 0.0


def test_ui_status_distinguishes_api_health_from_canonical_rows():
    # The contract surfaces BOTH axes so a UI cannot show a green "API OK"
    # as if it were "LIVE canonical rows".
    res = classify_canonical_status(
        api_health_status="OK", rows_added=0, age_hours=1.0,
    )
    assert res["api_health_ok"] is True            # API axis: healthy
    assert res["live_canonical"] is False          # Canonical axis: not live
    assert res["api_health_status"] == "OK"
    assert res["canonical_signal_status"] == ZERO_FRESH_ROWS
