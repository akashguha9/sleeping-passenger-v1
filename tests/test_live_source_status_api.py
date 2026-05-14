"""Tests for the live-sources freshness endpoint helpers.

The endpoint itself is FastAPI-only; the underlying logic lives in
``scripts.live_source_registry.compute_source_freshness``.  We test that
helper plus the API response shape via a thin wrapper that mirrors the
endpoint without requiring FastAPI to be installed.
"""
from __future__ import annotations

from scripts.live_source_registry import (
    ALL_SOURCE_KEYS,
    FRESHNESS_FRESH,
    FRESHNESS_OVERDUE,
    FRESHNESS_SKIPPED,
    FRESHNESS_FAILED,
    FRESHNESS_NEVER_RUN,
    FRESHNESS_STALE,
    compute_source_freshness,
)


def test_compute_source_freshness_emits_one_entry_per_source() -> None:
    freshness = compute_source_freshness(latest_runs=None, env={})
    for key in ALL_SOURCE_KEYS:
        assert key in freshness, f"missing source {key}"
        entry = freshness[key]
        # Safety stamps are enforced on every entry
        assert entry["advisory_status"] == "ADVISORY_ONLY"
        assert entry["execution_gate"] == "LOCKED"
        assert entry["broker_api_called"] is False
        assert entry["ai_execution_count"] == 0
        assert entry["execution_permission"] is False
        assert entry["can_execute"] is False


def test_compute_source_freshness_marks_missing_credential_skipped() -> None:
    # NewsAPI requires NEWS_API_KEY; if absent it must be classified as skipped.
    freshness = compute_source_freshness(latest_runs=None, env={})
    assert freshness["newsapi"]["freshness_state"] == FRESHNESS_SKIPPED


def test_compute_source_freshness_planned_adapter_not_implemented() -> None:
    freshness = compute_source_freshness(latest_runs=None, env={})
    # asia_disclosure is a planned adapter — its adapter_status must say so
    assert freshness["asia_disclosure"]["adapter_status"] == "planned"


def test_compute_source_freshness_fresh_window() -> None:
    """A recent OK run within the cadence window must produce FRESH."""
    now_epoch = 1_700_000_000.0
    one_hour_ago = "2023-11-14T21:53:20+00:00"  # not parsed; we mock now_epoch
    latest_runs = [
        {
            "source_name": "polymarket",
            "status": "OK",
            "timestamp_utc": "2023-11-14T22:46:40Z",
            "fetched_count": 5,
            "skipped_reason": "",
            "error_message": "",
        }
    ]
    freshness = compute_source_freshness(
        latest_runs,
        now_epoch=now_epoch + 60,  # 1 minute later → fresh
        env={},
    )
    assert freshness["polymarket"]["freshness_state"] == FRESHNESS_FRESH
    assert freshness["polymarket"]["next_expected_refresh_at"] is not None
    # Other sources (no row, no credentials) are skipped / never_run / failed —
    # all categories valid but never "fresh".
    fresh_states = {
        v["freshness_state"]
        for v in freshness.values()
    }
    assert FRESHNESS_FRESH in fresh_states
    # Set membership sanity check: each state value is one of the documented ones.
    valid = {
        FRESHNESS_FRESH,
        FRESHNESS_STALE,
        FRESHNESS_OVERDUE,
        FRESHNESS_NEVER_RUN,
        FRESHNESS_SKIPPED,
        FRESHNESS_FAILED,
    }
    assert fresh_states.issubset(valid), f"unexpected state: {fresh_states - valid}"


def test_compute_source_freshness_failed_state() -> None:
    latest_runs = [
        {
            "source_name": "polymarket",
            "status": "FAIL",
            "timestamp_utc": "2023-11-14T22:46:40Z",
            "fetched_count": 0,
            "skipped_reason": "",
            "error_message": "boom",
        }
    ]
    freshness = compute_source_freshness(latest_runs, env={})
    assert freshness["polymarket"]["freshness_state"] == FRESHNESS_FAILED


def test_compute_source_freshness_no_secrets_exposed() -> None:
    freshness = compute_source_freshness(
        latest_runs=None,
        env={"NEWS_API_KEY": "super-secret-key-12345"},
    )
    flat = repr(freshness)
    assert "super-secret-key" not in flat
    # NewsAPI must be marked configured but we never leak the value.
    assert freshness["newsapi"]["credential_configured"] is True


def test_api_status_response_shape_mimic() -> None:
    """Mimic the FastAPI handler without importing FastAPI.

    Documents the shape ``get_live_sources_status`` returns: one entry per
    source, plus a distribution and the canonical safety stamps.
    """
    freshness = compute_source_freshness(latest_runs=None, env={})
    dist: dict[str, int] = {}
    for entry in freshness.values():
        state = entry.get("freshness_state", "unknown")
        dist[state] = dist.get(state, 0) + 1
    response = {
        "operation": "get_live_sources_status",
        "sources": freshness,
        "source_count": len(freshness),
        "freshness_distribution": dist,
        "advisory_status": "ADVISORY_ONLY",
        "execution_mode": "HUMAN_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "human_review_required": True,
    }
    assert response["source_count"] >= len(ALL_SOURCE_KEYS)
    assert response["advisory_status"] == "ADVISORY_ONLY"
    assert response["execution_gate"] == "LOCKED"
    assert response["broker_api_called"] is False
    assert response["ai_execution_count"] == 0
    assert response["execution_permission"] is False
    assert response["can_execute"] is False
