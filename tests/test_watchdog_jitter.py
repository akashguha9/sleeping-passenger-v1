"""
Tests for the watchdog jitter feature.

Asserts:
  - the pure ``_compute_jittered_sleep`` math stays within bounds and is
    deterministic with a seeded RNG
  - the ``run_watchdog`` summary surfaces the new jitter fields
  - ``--disable-jitter`` makes planned/actual sleeps exactly equal to the
    base backoff sequence
  - ``--no-sleep`` zeros out actual sleep regardless of jitter setting
  - Safety invariants are preserved on every payload.
"""
from __future__ import annotations

import random
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.watchdog_refresh_stale_sources import (
    DEFAULT_BACKOFF_JITTER_PCT,
    MIN_SLEEP_SECONDS,
    Snapshot,
    SourceSnapshotEntry,
    _compute_jittered_sleep,
    run_watchdog,
)


# ---------------------------------------------------------------------------
# Pure jitter math
# ---------------------------------------------------------------------------


def test_compute_jittered_sleep_default_pct_within_bounds() -> None:
    rng = random.Random(42)
    base = 60.0
    pct = 0.15
    samples = [_compute_jittered_sleep(base, pct, rng=rng) for _ in range(200)]
    for s in samples:
        assert s >= MIN_SLEEP_SECONDS, s
        assert s >= base * (1 - pct) - 1e-9, s
        assert s <= base * (1 + pct) + 1e-9, s


def test_compute_jittered_sleep_pct_zero_returns_base() -> None:
    rng = random.Random(0)
    assert _compute_jittered_sleep(60.0, 0.0, rng=rng) == 60.0
    assert _compute_jittered_sleep(60.0, -0.5, rng=rng) == 60.0


def test_compute_jittered_sleep_zero_base_returns_zero() -> None:
    rng = random.Random(0)
    assert _compute_jittered_sleep(0.0, 0.15, rng=rng) == 0.0


def test_compute_jittered_sleep_floor_at_min_sleep_seconds() -> None:
    # An aggressive pct would otherwise pull the value near zero; the
    # floor must keep it at MIN_SLEEP_SECONDS.
    rng = random.Random(1)
    # base=2, pct=0.99 -> range [0.02, 3.98]; with seed=1 the draw
    # is reproducible; we just assert the >= floor property.
    for _ in range(50):
        val = _compute_jittered_sleep(2.0, 0.99, rng=random.Random(1))
        assert val >= MIN_SLEEP_SECONDS


def test_compute_jittered_sleep_deterministic_with_seeded_rng() -> None:
    a = _compute_jittered_sleep(60.0, 0.15, rng=random.Random(123))
    b = _compute_jittered_sleep(60.0, 0.15, rng=random.Random(123))
    assert a == b


# ---------------------------------------------------------------------------
# Summary integration
# ---------------------------------------------------------------------------


def _stale_snapshot() -> Snapshot:
    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries={
            "kalshi": SourceSnapshotEntry(
                source_key="kalshi",
                tier="optional",
                adapter_status="implemented",
                requires_api_key=False,
                credential_configured=True,
                freshness_state="stale",
                last_success_at="2026-05-24T09:00:00+00:00",
                last_refresh_attempt_at="2026-05-25T10:30:00+00:00",
                last_refresh_success=False,
                last_refresh_skipped=False,
                last_refresh_error="upstream 503",
                last_refresh_skipped_reason="",
                latest_event_at="2026-05-24T09:00:00+00:00",
                hours_since_last_success=25.0,
                excluded_reason=None,
                is_stale_active=True,
                is_derived=False,
                parent_sources=(),
                dependency_critical=True,
                used_by_derived=("prediction_market_disagreement",),
                stale_severity="dependency_blocking",
            ),
        },
        ttl_hours=6,
    )


def _safety(summary: dict) -> None:
    assert summary["advisory_only"] is True
    assert summary["human_execution_required"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["can_execute"] is False
    assert summary["ai_execution_count"] == 0


def test_summary_includes_jitter_fields(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot()] * 10)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=2,
        backoff_seconds=(7, 11),
        backoff_jitter_pct=0.20,
        jitter_seed=99,
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    summary = result.summary
    assert "backoff_jitter_pct" in summary
    assert summary["backoff_jitter_pct"] == 0.20
    assert summary["jitter_enabled"] is True
    assert isinstance(summary["planned_sleep_seconds_per_retry"], list)
    assert isinstance(summary["actual_sleep_seconds_per_retry"], list)
    # max_retries=2 -> the retry block runs after the failing first
    # attempt; expect at least one planned-sleep entry.
    assert len(summary["planned_sleep_seconds_per_retry"]) >= 1
    # no-sleep -> actual_sleep entries are all zero
    assert all(v == 0.0 for v in summary["actual_sleep_seconds_per_retry"])
    # planned values stay within the jitter band
    for planned, base in zip(summary["planned_sleep_seconds_per_retry"], (7, 11)):
        assert planned >= base * 0.8 - 1e-9
        assert planned <= base * 1.2 + 1e-9
    _safety(summary)


def test_disable_jitter_makes_planned_equal_base(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot()] * 10)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=2,
        backoff_seconds=(13, 17),
        backoff_jitter_pct=0.30,
        disable_jitter=True,
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    summary = result.summary
    assert summary["jitter_enabled"] is False
    assert summary["planned_sleep_seconds_per_retry"][0] == 13.0
    if len(summary["planned_sleep_seconds_per_retry"]) > 1:
        assert summary["planned_sleep_seconds_per_retry"][1] == 17.0
    _safety(summary)


def test_jitter_seed_is_deterministic(tmp_path: Path) -> None:
    snapshots_a = iter([_stale_snapshot()] * 20)
    a = run_watchdog(
        ttl_hours=6,
        max_retries=3,
        backoff_seconds=(60, 180, 300),
        backoff_jitter_pct=0.15,
        jitter_seed=2026,
        no_sleep=True,
        summary_path=tmp_path / "a.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots_a),
    )
    snapshots_b = iter([_stale_snapshot()] * 20)
    b = run_watchdog(
        ttl_hours=6,
        max_retries=3,
        backoff_seconds=(60, 180, 300),
        backoff_jitter_pct=0.15,
        jitter_seed=2026,
        no_sleep=True,
        summary_path=tmp_path / "b.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots_b),
    )
    assert (
        a.summary["planned_sleep_seconds_per_retry"]
        == b.summary["planned_sleep_seconds_per_retry"]
    )
    _safety(a.summary)
    _safety(b.summary)


def test_no_sleep_prevents_real_sleep_calls(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot()] * 10)
    real_sleeps: list[float] = []
    run_watchdog(
        ttl_hours=6,
        max_retries=2,
        backoff_seconds=(7, 11),
        backoff_jitter_pct=DEFAULT_BACKOFF_JITTER_PCT,
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        sleep_fn=lambda s: real_sleeps.append(s),
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert real_sleeps == []
