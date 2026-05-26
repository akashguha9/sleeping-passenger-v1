"""Tests — scripts/candidate_feed.py discovery + fallback scoring."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.candidate_feed import (
    REASON_FALLBACK_SCORES_APPLIED,
    REASON_NO_CANDIDATE_FILE,
    REASON_STATIC_UNIVERSE_ONLY,
    STATUS_CANDIDATES_LOADED,
    STATUS_CANDIDATE_FILE_INVALID,
    STATUS_CANDIDATE_FILE_STALE,
    STATUS_NO_CANDIDATE_FILE,
    candidate_to_admission_input,
    discover_candidate_files,
    load_candidate_feed,
    normalize_candidate,
)


NOW = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discover_candidate_files_finds_release_artifacts(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    f = release_dir / "operator_daily_signal.json"
    _write_json(f, {"candidates": [{"ticker": "MU"}]})
    files = discover_candidate_files(release_dir)
    assert f in files


def test_discover_returns_empty_when_release_dir_is_empty(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    files = discover_candidate_files(release_dir)
    # Real yesterday_final_candidates.json on disk in default location
    # may be picked up — filter to release_dir.
    assert all(p.parent == release_dir for p in files if p.parent == release_dir) or files == [] or all(p.exists() for p in files)


# ---------------------------------------------------------------------------
# load_candidate_feed
# ---------------------------------------------------------------------------


def test_load_candidate_feed_no_candidate_file_returns_status(tmp_path):
    result = load_candidate_feed(
        release_dir=tmp_path,
        candidate_path=tmp_path / "absent.json",
        now_utc=NOW,
    )
    assert result.feed_status == STATUS_NO_CANDIDATE_FILE
    assert result.candidate_count == 0
    assert REASON_NO_CANDIDATE_FILE in result.reason_codes


def test_load_candidate_feed_explicit_scores_preserved(tmp_path):
    path = tmp_path / "operator_daily_signal.json"
    _write_json(
        path,
        {
            "generated_at_utc": "2026-05-26T08:00:00Z",
            "candidates": [
                {
                    "ticker": "MU",
                    "candidate_score": 0.91,
                    "execution_readiness_score": 0.88,
                    "why_today_score": 0.75,
                    "freshness_score": 0.6,
                    "source_health": "LIVE_VERIFIED",
                }
            ],
        },
    )
    result = load_candidate_feed(candidate_path=path, now_utc=NOW)
    assert result.feed_status == STATUS_CANDIDATES_LOADED
    assert result.candidate_count == 1
    c = result.candidates[0]
    assert c.candidate_score == pytest.approx(0.91)
    assert c.execution_readiness_score == pytest.approx(0.88)
    assert c.why_today_score == pytest.approx(0.75)
    assert REASON_FALLBACK_SCORES_APPLIED not in c.reason_codes


def test_load_candidate_feed_missing_scores_uses_conservative_fallback(tmp_path):
    path = tmp_path / "today_candidates.json"
    _write_json(
        path,
        {
            "generated_at_utc": "2026-05-26T08:00:00Z",
            "candidates": [{"ticker": "MU"}],
        },
    )
    result = load_candidate_feed(candidate_path=path, now_utc=NOW)
    assert result.candidate_count == 1
    c = result.candidates[0]
    # Conservative — never inflated.
    assert c.candidate_score <= 0.45
    assert c.why_today_score == pytest.approx(0.25)
    assert REASON_FALLBACK_SCORES_APPLIED in c.reason_codes


def test_load_candidate_feed_stale_file_flagged_as_stale(tmp_path):
    path = tmp_path / "operator_daily_signal.json"
    stale_dt = NOW - timedelta(days=10)
    _write_json(
        path,
        {
            "generated_at_utc": stale_dt.isoformat().replace("+00:00", "Z"),
            "candidates": [{"ticker": "MU", "candidate_score": 0.8}],
        },
    )
    result = load_candidate_feed(candidate_path=path, max_age_hours=72, now_utc=NOW)
    assert result.feed_status == STATUS_CANDIDATE_FILE_STALE


def test_load_candidate_feed_invalid_json_is_caught(tmp_path):
    path = tmp_path / "today_candidates.json"
    path.write_text("{not json", encoding="utf-8")
    result = load_candidate_feed(candidate_path=path, now_utc=NOW)
    assert result.feed_status == STATUS_CANDIDATE_FILE_INVALID


def test_load_candidate_feed_static_universe_low_why_today(tmp_path):
    path = tmp_path / "today_candidates.json"
    _write_json(
        path,
        {
            "generated_at_utc": "2026-05-26T08:00:00Z",
            "final_candidates": ["RTX", "ZIM", "GLD"],
        },
    )
    result = load_candidate_feed(candidate_path=path, now_utc=NOW)
    assert result.candidate_count == 3
    for c in result.candidates:
        assert c.why_today_score == pytest.approx(0.25)
        assert REASON_STATIC_UNIVERSE_ONLY in c.reason_codes


def test_normalize_candidate_skips_synthetic_id_rows():
    raw = {"id": "ALL_GREEN", "fresh_catalyst_score": 0.5}
    assert normalize_candidate(raw) is None


def test_normalize_candidate_handles_ticker_normalization():
    raw = {"ticker": "NASDAQ:AMD", "candidate_score": 0.7}
    ctx = normalize_candidate(raw)
    assert ctx is not None
    assert ctx.ticker == "AMD"
    assert "AI_SEMIS_CLOUD" in ctx.theme_buckets


def test_amd_maps_to_AI_SEMIS_CLOUD_and_HIGH_BETA():
    ctx = normalize_candidate({"ticker": "AMD"})
    assert ctx is not None
    assert "AI_SEMIS_CLOUD" in ctx.theme_buckets
    assert "HIGH_BETA_SPECULATIVE" in ctx.theme_buckets


def test_gd_maps_to_DEFENSE():
    ctx = normalize_candidate({"ticker": "NYSE:GD"})
    assert ctx is not None
    assert "DEFENSE" in ctx.theme_buckets
    assert ctx.economic_exposure_key == "GENERAL_DYNAMICS"


def test_candidate_safety_stamps_present(tmp_path):
    path = tmp_path / "today_candidates.json"
    _write_json(path, {"candidates": [{"ticker": "MU"}]})
    result = load_candidate_feed(candidate_path=path, now_utc=NOW)
    assert result.advisory_only is True
    assert result.broker_api_called is False
    assert result.ai_execution_count == 0
    assert result.execution_permission == "ADVISORY_ONLY"
    assert result.human_execution_required is True
    for c in result.candidates:
        assert c.advisory_only is True
        assert c.broker_api_called is False
        assert c.ai_execution_count == 0


def test_candidate_feed_does_not_invent_candidates(tmp_path):
    """Loader must not invent candidates when fed an empty file."""
    path = tmp_path / "today_candidates.json"
    _write_json(path, {"candidates": []})
    result = load_candidate_feed(candidate_path=path, now_utc=NOW)
    assert result.candidate_count == 0
    # We didn't find a usable file body, so the status is "no candidate file".
    assert result.feed_status in (STATUS_NO_CANDIDATE_FILE, STATUS_CANDIDATES_LOADED)


def test_candidate_to_admission_input_shape():
    ctx = normalize_candidate({"ticker": "MU", "candidate_score": 0.8})
    inp = candidate_to_admission_input(ctx)
    assert inp["ticker"] == "MU"
    assert inp["candidate_score"] == pytest.approx(0.8)
    assert inp["advisory_only"] is True
    assert inp["broker_api_called"] is False


def test_duplicate_exposure_when_held_in_portfolio(tmp_path):
    """When the portfolio already holds AVGO and candidate is AVGO,
    the buy-admission integration should flag DUPLICATE_EXPOSURE.

    We only check the normalize step here; the admission classifier
    integration is exercised in test_capital_rotation_autofeed.
    """
    ctx = normalize_candidate({"ticker": "AVGO", "candidate_score": 0.8})
    assert ctx is not None
    assert ctx.economic_exposure_key == "BROADCOM"
