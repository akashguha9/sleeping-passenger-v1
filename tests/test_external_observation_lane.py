"""Tests for the external observation lane.

Deliberately provider-free — every test injects a fake provider callable.
No test touches the internet.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.external_observation_lane import (
    DEFAULT_STALENESS_LIMIT_SECONDS,
    ExternalObservation,
    VALID_DATA_QUALITY,
    apply_observation_summary_to_runtime_state,
    fetch_external_observation,
    fetch_external_observations,
    observations_to_signal_context,
    observations_to_scm_candidates,
    safe_write_external_observation_report,
    summarize_external_observations,
)


NOW_UTC = "2026-04-24T12:00:05+00:00"
OBSERVED_AT = "2026-04-24T12:00:00+00:00"


def _fake_ok(symbol: str) -> dict:
    return {
        "last_price": 91.45,
        "previous_close": 91.00,
        "volume": 5_000_000,
        "currency": "USD",
        "regular_market_time": OBSERVED_AT,
    }


def _fake_missing(symbol: str) -> dict:
    return {"currency": "USD"}  # no last_price


def _fake_error(symbol: str) -> dict:
    raise RuntimeError("yfinance unreachable")


def _fake_stale(symbol: str) -> dict:
    return {
        "last_price": 91.00,
        "previous_close": 91.00,
        "regular_market_time": "2026-04-23T12:00:00+00:00",  # >24h old
    }


def test_valid_external_observation_is_normalized_and_marked_external():
    row = fetch_external_observation("TLT", provider_fn=_fake_ok, now_utc=NOW_UTC)
    assert isinstance(row, ExternalObservation)
    assert row.symbol == "TLT"
    assert row.price == 91.45
    assert row.previous_close == 91.00
    assert row.change_pct == pytest.approx((91.45 - 91.00) / 91.00, abs=1e-4)
    assert row.volume == 5_000_000
    assert row.currency == "USD"
    assert row.data_quality == "VALID_EXTERNAL"
    assert row.is_external is True
    assert row.is_placeholder is False
    assert row.error is None
    assert row.truth_origin == "external"


def test_provider_error_is_contained_and_flagged():
    row = fetch_external_observation("UNG", provider_fn=_fake_error, now_utc=NOW_UTC)
    assert row.data_quality == "PROVIDER_ERROR"
    assert row.is_external is False
    assert row.is_placeholder is True
    assert row.price is None
    assert row.error is not None
    assert "yfinance" in row.error


def test_missing_price_is_classified_not_failed():
    row = fetch_external_observation("TIP", provider_fn=_fake_missing, now_utc=NOW_UTC)
    assert row.data_quality == "MISSING_PRICE"
    assert row.is_external is False
    assert row.price is None
    assert row.error is None


def test_stale_observation_is_classified_stale_and_counted_as_active():
    row = fetch_external_observation(
        "SPY",
        provider_fn=_fake_stale,
        now_utc=NOW_UTC,
        staleness_limit_seconds=60 * 60,  # 1 hour
    )
    assert row.data_quality == "STALE_EXTERNAL"
    # Stale is still external-ish for the purpose of is_external,
    # because the lane did observe a real price.
    assert row.is_external is True
    assert row.staleness_seconds is not None and row.staleness_seconds > 60 * 60


def test_fetch_batch_dedupes_sorts_and_preserves_partial_failure():
    rows = fetch_external_observations(
        ["ung", "TLT", "UNG", "", "tip"],
        provider_fn=lambda s: _fake_ok(s) if s != "UNG" else (_ for _ in ()).throw(RuntimeError("nope")),
        now_utc=NOW_UTC,
    )
    assert [r.symbol for r in rows] == ["TIP", "TLT", "UNG"]
    by_symbol = {r.symbol: r for r in rows}
    assert by_symbol["TIP"].data_quality == "VALID_EXTERNAL"
    assert by_symbol["TLT"].data_quality == "VALID_EXTERNAL"
    assert by_symbol["UNG"].data_quality == "PROVIDER_ERROR"


def test_summarize_counts_all_quality_buckets():
    rows = [
        fetch_external_observation("TLT", provider_fn=_fake_ok, now_utc=NOW_UTC),
        fetch_external_observation("UNG", provider_fn=_fake_error, now_utc=NOW_UTC),
        fetch_external_observation("TIP", provider_fn=_fake_missing, now_utc=NOW_UTC),
    ]
    summary = summarize_external_observations(rows)
    assert summary["external_observation_count"] == 3
    assert summary["external_observation_valid_count"] == 1
    assert summary["external_observation_error_count"] == 2  # error + missing
    assert summary["external_observation_data_quality_counts"]["VALID_EXTERNAL"] == 1
    assert summary["external_observation_data_quality_counts"]["PROVIDER_ERROR"] == 1
    assert summary["external_observation_data_quality_counts"]["MISSING_PRICE"] == 1
    # every valid quality key always present, even when zero
    assert set(summary["external_observation_data_quality_counts"].keys()) == VALID_DATA_QUALITY


def test_observations_to_signal_context_marks_every_row_as_non_trade():
    rows = [
        fetch_external_observation("TLT", provider_fn=_fake_ok, now_utc=NOW_UTC),
        fetch_external_observation("UNG", provider_fn=_fake_error, now_utc=NOW_UTC),
    ]
    ctx = observations_to_signal_context(rows)
    assert len(ctx) == 2
    for row in ctx:
        assert row["source"] == "external_price_observation"
        assert row["is_trade_signal"] is False
    # valid gets higher confidence than provider-error
    valid = next(r for r in ctx if r["symbol"] == "TLT")
    errored = next(r for r in ctx if r["symbol"] == "UNG")
    assert valid["confidence"] > errored["confidence"]


def test_observations_to_scm_candidates_are_advisory_and_external():
    rows = [
        fetch_external_observation("TLT", provider_fn=_fake_ok, now_utc=NOW_UTC),
        fetch_external_observation("UNG", provider_fn=_fake_error, now_utc=NOW_UTC),
    ]

    candidates = observations_to_scm_candidates(rows)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["ticker"] == "TLT"
    assert candidate["source_name"] == "external_observation"
    assert candidate["signal_origin"] == "external"
    assert candidate["status"] == "WATCHLIST"
    assert candidate["conversion_state"] == "NOT_EXECUTED"
    assert candidate["blocker_attribution"] == "GSCE_PHASE_LOCK"
    assert candidate["source_observation_id"].startswith("obs_yahoo_TLT_")
    assert candidate["price"] == 91.45
    assert candidate["data_quality"] == "VALID_EXTERNAL"
    assert candidate["is_trade_signal"] is False


def test_safe_write_external_observation_report_round_trip(scratch_path: Path):
    rows = [fetch_external_observation("TLT", provider_fn=_fake_ok, now_utc=NOW_UTC)]
    target = scratch_path / "obs.json"
    report = safe_write_external_observation_report(rows, path=target, provider="yahoo")
    assert report["external_observation_active"] is True
    assert report["external_observation_count"] == 1
    assert report["external_observation_report_path"].endswith("obs.json")
    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted["external_observation_valid_count"] == 1
    # coherence layer stamps run_id onto dict writes
    assert "run_id" in persisted
    assert persisted["external_observation_provider"] == "yahoo"


def test_safe_write_is_inactive_when_every_observation_failed(scratch_path: Path):
    rows = [fetch_external_observation("UNG", provider_fn=_fake_error, now_utc=NOW_UTC)]
    report = safe_write_external_observation_report(
        rows, path=scratch_path / "obs.json", write=False
    )
    assert report["external_observation_active"] is False
    assert report["external_observation_error_count"] == 1
    assert report["external_observation_valid_count"] == 0


def test_apply_observation_summary_does_nothing_when_inactive():
    state = {"source_mode": "SYNTHETIC_RUNTIME_FALLBACK"}
    out = apply_observation_summary_to_runtime_state(
        state, {"external_observation_active": False}
    )
    assert "external_observation_active" not in out


def test_apply_observation_summary_sets_flag_when_active():
    state = {}
    out = apply_observation_summary_to_runtime_state(
        state,
        {
            "external_observation_active": True,
            "external_observation_provider": "yahoo",
            "external_observation_providers": ["yahoo"],
        },
    )
    assert out["external_observation_active"] is True
    assert out["external_observation_source"] == "yahoo"


def test_default_staleness_limit_is_reasonable():
    # Smoke: the default must be large enough that a fresh fetch is always
    # VALID_EXTERNAL. One hour would be too tight for a pre-market run;
    # six hours is the current contract.
    assert DEFAULT_STALENESS_LIMIT_SECONDS == 6 * 60 * 60
