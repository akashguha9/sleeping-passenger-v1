"""Tests for the provider verification helpers (Integrated Sprint Part 2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import live_payload_quality as lpq
from scripts import provider_verification as pv


def _now():
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_ago: float) -> str:
    return (_now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_fresh_verified_returns_healthy():
    row = pv.classify_provider(
        provider="yfinance",
        source_class="price",
        records=[{"ticker": "AAPL"}],
        latest_event_timestamp_utc=_ts(1.0),
        last_call_succeeded=True,
        now_utc=_now(),
    )
    assert row["status"] == lpq.STATUS_HEALTHY
    assert row["verification_status"] == lpq.VERIF_VERIFIED


def test_fallback_never_healthy():
    row = pv.classify_provider(
        provider="yfinance",
        source_class="price",
        records=[{"ticker": "AAPL"}],
        latest_event_timestamp_utc=_ts(1.0),
        last_call_succeeded=True,
        is_fallback=True,
        now_utc=_now(),
    )
    assert row["status"] == lpq.STATUS_FALLBACK
    assert row["verification_status"] == lpq.VERIF_FALLBACK


def test_mock_never_healthy():
    row = pv.classify_provider(
        provider="yfinance",
        source_class="price",
        records=[{"ticker": "AAPL"}],
        latest_event_timestamp_utc=_ts(1.0),
        last_call_succeeded=True,
        is_mock=True,
        now_utc=_now(),
    )
    assert row["status"] == lpq.STATUS_MOCK
    assert row["verification_status"] == lpq.VERIF_MOCK


def test_age_exceeds_sla_marks_stale():
    row = pv.classify_provider(
        provider="yfinance",
        source_class="price",
        records=[{"ticker": "AAPL"}],
        latest_event_timestamp_utc=_ts(48.0),  # > 24h SLA
        last_call_succeeded=True,
        now_utc=_now(),
    )
    assert row["status"] == lpq.STATUS_STALE
    assert row["verification_status"] == lpq.VERIF_STALE


def test_provider_call_failure_preserves_last_good_timestamp():
    previous_ts = _ts(2.0)
    row = pv.classify_provider(
        provider="yfinance",
        source_class="price",
        records=None,
        latest_event_timestamp_utc=None,
        last_call_succeeded=False,
        previous_status=lpq.STATUS_HEALTHY,
        previous_timestamp_utc=previous_ts,
        now_utc=_now(),
    )
    assert row["status"] == lpq.STATUS_DEGRADED
    assert row["latest_event_timestamp_utc"] == previous_ts


def test_failure_no_previous_data_returns_offline():
    row = pv.classify_provider(
        provider="yfinance",
        source_class="price",
        records=None,
        latest_event_timestamp_utc=None,
        last_call_succeeded=False,
        now_utc=_now(),
    )
    assert row["status"] == lpq.STATUS_OFFLINE


def test_schema_invalid_marks_degraded():
    row = pv.classify_provider(
        provider="yfinance",
        source_class="price",
        records=[{"bad": "rec"}],
        latest_event_timestamp_utc=_ts(0.1),
        last_call_succeeded=True,
        schema_valid=False,
        now_utc=_now(),
    )
    assert row["status"] == lpq.STATUS_DEGRADED
    assert row["verification_status"] == lpq.VERIF_UNVERIFIED


def test_timestamp_not_advanced_for_fallback():
    previous = _ts(5.0)
    row = pv.classify_provider(
        provider="x",
        source_class="news_event",
        records=[{"title": "fake"}],
        latest_event_timestamp_utc=_ts(0.1),
        last_call_succeeded=True,
        is_fallback=True,
        previous_timestamp_utc=previous,
        now_utc=_now(),
    )
    # Effective timestamp must be the previous good one, never the fallback one.
    assert row["latest_event_timestamp_utc"] == previous


def test_classify_provider_carries_advisory_stamps():
    row = pv.classify_provider(
        provider="g", source_class="news_event",
        records=[{}], latest_event_timestamp_utc=_ts(0.5),
        last_call_succeeded=True, now_utc=_now(),
    )
    assert row["advisory_status"] == "ADVISORY_ONLY"
    assert row["execution_gate"] == "LOCKED"
    assert row["broker_api_called"] is False


def test_normalize_signal_event_event_id_stable():
    record = {"ticker": "AAPL", "event_type": "filing",
              "timestamp_utc": "2026-05-24T01:00:00Z",
              "title": "Annual Report"}
    a = pv.normalize_signal_event(
        raw_record=record, provider="sec_edgar",
        source_class="filings",
        verification_status="VERIFIED", freshness_status="FRESH",
    )
    b = pv.normalize_signal_event(
        raw_record=record, provider="sec_edgar",
        source_class="filings",
        verification_status="VERIFIED", freshness_status="FRESH",
    )
    assert a["event_id"] == b["event_id"]
    assert a["execution_permission"] == "ADVISORY_ONLY"
