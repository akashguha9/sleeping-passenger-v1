"""
Kalshi source-freshness vs market-activity decomposition tests.

The screenshot regression collapsed both axes into a single STALE_ACTIVE
chip.  These helpers compute them independently and recombine them into
an explicit ui_badge_status so the operator can never confuse "source
last fetched 30h ago" with "market itself is closed".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.kalshi_normalizer import (
    DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
    MARKET_CLOSED,
    MARKET_EXPIRED,
    MARKET_OPEN,
    MARKET_UNKNOWN,
    SOURCE_ERROR,
    SOURCE_LIVE_VERIFIED,
    SOURCE_STALE,
    SOURCE_UNVERIFIED,
    UI_BADGE_ERROR_OPEN,
    UI_BADGE_LIVE_OPEN,
    UI_BADGE_MARKET_EXPIRED,
    UI_BADGE_STALE_OPEN,
    UI_BADGE_UNKNOWN,
    UI_BADGE_UNVERIFIED_OPEN,
    compute_kalshi_ui_badge,
    compute_market_activity,
    compute_source_freshness,
    normalize_kalshi_market,
)


NOW = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_future_close_plus_fresh_fetch_is_live_open():
    fresh = compute_source_freshness(_iso(NOW - timedelta(minutes=10)), _iso(NOW))
    activity = compute_market_activity(_iso(NOW + timedelta(days=5)), _iso(NOW))
    assert fresh == SOURCE_LIVE_VERIFIED
    assert activity == MARKET_OPEN
    assert compute_kalshi_ui_badge(fresh, activity) == UI_BADGE_LIVE_OPEN


def test_future_close_plus_old_fetch_is_source_stale_market_open():
    fresh = compute_source_freshness(_iso(NOW - timedelta(hours=30)), _iso(NOW))
    activity = compute_market_activity(_iso(NOW + timedelta(days=5)), _iso(NOW))
    assert fresh == SOURCE_STALE
    assert activity == MARKET_OPEN
    assert compute_kalshi_ui_badge(fresh, activity) == UI_BADGE_STALE_OPEN


def test_past_close_recent_is_market_closed():
    activity = compute_market_activity(_iso(NOW - timedelta(hours=2)), _iso(NOW))
    assert activity == MARKET_CLOSED


def test_past_close_long_ago_is_market_expired():
    activity = compute_market_activity(_iso(NOW - timedelta(days=30)), _iso(NOW))
    assert activity == MARKET_EXPIRED
    # ui_badge collapses to MARKET_EXPIRED regardless of source freshness.
    assert compute_kalshi_ui_badge(SOURCE_LIVE_VERIFIED, activity) == UI_BADGE_MARKET_EXPIRED


def test_missing_close_time_is_market_unknown():
    assert compute_market_activity(None, _iso(NOW)) == MARKET_UNKNOWN
    assert compute_market_activity("", _iso(NOW)) == MARKET_UNKNOWN


def test_source_error_overrides_age_calculation():
    fresh = compute_source_freshness(_iso(NOW - timedelta(minutes=1)), _iso(NOW), error_state=True)
    assert fresh == SOURCE_ERROR


def test_unverified_when_no_fetch_record():
    fresh = compute_source_freshness(None, _iso(NOW))
    assert fresh == SOURCE_UNVERIFIED
    activity = compute_market_activity(_iso(NOW + timedelta(days=1)), _iso(NOW))
    assert compute_kalshi_ui_badge(fresh, activity) == UI_BADGE_UNVERIFIED_OPEN


def test_unknown_badge_for_unknown_activity():
    assert compute_kalshi_ui_badge(SOURCE_LIVE_VERIFIED, MARKET_UNKNOWN) == UI_BADGE_UNKNOWN


def test_normalize_market_carries_freshness_and_activity_status():
    rec = normalize_kalshi_market(
        {
            "source": "Kalshi",
            "source_market_id": "BTCMAY-2026",
            "ticker": "BTCMAY-2026",
            "title": "How high will Bitcoin get in May?",
            "category": "Crypto",
            "close_time_utc": _iso(NOW + timedelta(days=5)),
        },
        fetched_at_utc=_iso(NOW),
        last_successful_fetch_at_utc=_iso(NOW - timedelta(hours=30)),
        now_utc=_iso(NOW),
        source_freshness_ttl_seconds=DEFAULT_SOURCE_FRESHNESS_TTL_SECONDS,
    )
    assert rec is not None
    assert rec["source_freshness_status"] == SOURCE_STALE
    assert rec["market_activity_status"] == MARKET_OPEN
    assert rec["ui_badge_status"] == UI_BADGE_STALE_OPEN
    assert rec["advisory_only"] is True
    assert rec["broker_api_called"] is False
    assert rec["ai_execution_count"] == 0


def test_source_error_open_badge_for_error_state():
    badge = compute_kalshi_ui_badge(SOURCE_ERROR, MARKET_OPEN)
    assert badge == UI_BADGE_ERROR_OPEN
