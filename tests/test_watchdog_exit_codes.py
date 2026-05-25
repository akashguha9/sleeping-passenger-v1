"""
Pin the watchdog exit-code semantics that the Windows wrapper relies on.

Contract:
  HEALTHY              -> exit 0  (wrapper: PASS)
  IMPROVED_BUT_STALE   -> exit 0  (wrapper: PASS)
  STALE_UNCHANGED      -> exit 2  (wrapper: PASS_WITH_STALE_SOURCES -> 0)
  ERROR                -> exit 1  (wrapper: FAIL -> 1)

Without distinct codes Task Scheduler shows the task as failed every
time upstreams are still down, hiding actual watchdog crashes in the
same signal.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.watchdog_refresh_stale_sources import (
    EXIT_ERROR,
    EXIT_HEALTHY,
    EXIT_IMPROVED_BUT_STALE,
    EXIT_STALE_UNCHANGED,
    STATUS_ERROR,
    STATUS_HEALTHY,
    STATUS_IMPROVED_BUT_STALE,
    STATUS_STALE_UNCHANGED,
    Snapshot,
    SourceSnapshotEntry,
    run_watchdog,
)


def _entry(key, freshness="fresh", excluded=None, tier="core"):
    return SourceSnapshotEntry(
        source_key=key,
        tier=tier,
        adapter_status="implemented",
        requires_api_key=False,
        credential_configured=True,
        freshness_state=freshness,
        last_success_at="2026-05-25T10:00:00+00:00",
        last_refresh_attempt_at="2026-05-25T10:00:00+00:00",
        last_refresh_success=(freshness == "fresh"),
        last_refresh_skipped=False,
        last_refresh_error="",
        last_refresh_skipped_reason="",
        latest_event_at="2026-05-25T10:00:00+00:00",
        hours_since_last_success=0.5 if freshness == "fresh" else 25.0,
        excluded_reason=excluded,
        is_stale_active=(excluded is None and freshness != "fresh"),
        is_derived=False,
        parent_sources=(),
    )


def _snap(entries):
    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries=dict(entries),
        ttl_hours=6,
    )


def _runner_ok(cmd):
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def test_exit_code_constants_are_distinct():
    """STALE_UNCHANGED must use a distinct code from ERROR so the
    Windows wrapper can map them differently."""
    assert EXIT_HEALTHY == 0
    assert EXIT_IMPROVED_BUT_STALE == 0
    assert EXIT_STALE_UNCHANGED == 2
    assert EXIT_ERROR == 1
    assert EXIT_STALE_UNCHANGED != EXIT_ERROR


def test_healthy_returns_exit_zero(tmp_path):
    snap = _snap({"polymarket": _entry("polymarket")})
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "s.json",
        subprocess_runner=_runner_ok,
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: snap,
    )
    assert result.status == STATUS_HEALTHY
    assert result.exit_code == EXIT_HEALTHY == 0


def test_stale_unchanged_returns_exit_two(tmp_path):
    """The flagship exit-code change: STALE_UNCHANGED -> 2, not 1."""
    snap = _snap(
        {
            "polymarket": _entry("polymarket"),
            "kalshi": _entry("kalshi", freshness="stale", tier="optional"),
        }
    )
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "s.json",
        subprocess_runner=_runner_ok,
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: snap,
    )
    assert result.status == STATUS_STALE_UNCHANGED
    assert result.exit_code == EXIT_STALE_UNCHANGED == 2


def test_improved_but_stale_returns_exit_zero(tmp_path):
    before = _snap(
        {
            "polymarket": _entry("polymarket"),
            "kalshi": _entry("kalshi", freshness="stale", tier="optional"),
            "gdelt": _entry("gdelt", freshness="stale"),
        }
    )
    # After parent refresh, kalshi cleared but gdelt remains stale.
    mid_entries = dict(before.entries)
    mid_entries["kalshi"] = _entry("kalshi", tier="optional")
    mid = _snap(mid_entries)
    snapshots = iter([before, mid, mid])
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "s.json",
        subprocess_runner=_runner_ok,
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert result.status == STATUS_IMPROVED_BUT_STALE
    assert result.exit_code == EXIT_IMPROVED_BUT_STALE == 0


def test_error_returns_exit_one(tmp_path):
    def _explode(**_):
        raise RuntimeError("simulated db failure")

    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "s.json",
        subprocess_runner=_runner_ok,
        sleep_fn=lambda s: None,
        snapshot_fn=_explode,
    )
    assert result.status == STATUS_ERROR
    assert result.exit_code == EXIT_ERROR == 1
