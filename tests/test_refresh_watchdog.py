"""
Tests for scripts/watchdog_refresh_stale_sources.py.

Every test injects a fake snapshot loader and a fake subprocess runner so
no real DB read, no real ``refresh_live_signals.py`` invocation, and no
real sleep occurs.  Safety invariants are asserted on every summary.
"""
from __future__ import annotations

import json
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.watchdog_refresh_stale_sources import (
    DEFAULT_BACKOFF_SECONDS,
    STATUS_ERROR,
    STATUS_HEALTHY,
    STATUS_IMPROVED_BUT_STALE,
    STATUS_STALE_UNCHANGED,
    Snapshot,
    SourceSnapshotEntry,
    run_watchdog,
    main as watchdog_main,
)


# ---------------------------------------------------------------------------
# Snapshot builders
# ---------------------------------------------------------------------------


def _entry(
    key: str,
    *,
    tier: str = "core",
    freshness: str = "fresh",
    excluded: str | None = None,
    cred: bool = True,
    parents: tuple[str, ...] = (),
    is_derived: bool = False,
    last_success_at: str | None = "2026-05-25T10:00:00+00:00",
    last_refresh_attempt_at: str | None = "2026-05-25T10:00:00+00:00",
    last_refresh_success: bool = True,
    last_refresh_error: str = "",
    last_refresh_skipped_reason: str = "",
    latest_event_at: str | None = "2026-05-25T10:00:00+00:00",
    is_stale_active: bool | None = None,
    dependency_critical: bool = False,
    used_by_derived: tuple[str, ...] = (),
    stale_severity: str = "",
    degraded_parent_stale_parents: tuple[str, ...] = (),
) -> SourceSnapshotEntry:
    if is_stale_active is None:
        is_stale_active = (
            excluded is None
            and freshness
            in {"stale", "overdue", "never_run", "failed", "degraded_parent_stale"}
        )
    return SourceSnapshotEntry(
        source_key=key,
        tier=tier,
        adapter_status="implemented",
        requires_api_key=False,
        credential_configured=cred,
        freshness_state=freshness,
        last_success_at=last_success_at,
        last_refresh_attempt_at=last_refresh_attempt_at,
        last_refresh_success=last_refresh_success,
        last_refresh_skipped=False,
        last_refresh_error=last_refresh_error,
        last_refresh_skipped_reason=last_refresh_skipped_reason,
        latest_event_at=latest_event_at,
        hours_since_last_success=(0.5 if freshness == "fresh" else 7.5),
        excluded_reason=excluded,
        is_stale_active=is_stale_active,
        is_derived=is_derived,
        parent_sources=parents,
        dependency_critical=dependency_critical,
        used_by_derived=used_by_derived,
        stale_severity=stale_severity,
        degraded_parent_stale_parents=degraded_parent_stale_parents,
    )


def _snapshot(entries: dict[str, SourceSnapshotEntry]) -> Snapshot:
    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries=dict(entries),
        ttl_hours=6,
    )


def _healthy_snapshot_all_fresh() -> Snapshot:
    return _snapshot({
        "polymarket": _entry("polymarket"),
        "kalshi": _entry("kalshi", tier="optional"),
        "gdelt": _entry("gdelt"),
        "etherscan": _entry(
            "etherscan",
            tier="optional",
            cred=False,
            excluded="optional_config_missing",
            freshness="skipped",
            last_success_at=None,
            last_refresh_success=False,
        ),
        "prediction_market_disagreement": _entry(
            "prediction_market_disagreement",
            tier="optional",
            parents=("polymarket", "kalshi"),
            is_derived=True,
        ),
    })


def _stale_snapshot_current_scenario() -> Snapshot:
    """Mirrors the cockpit screenshot in the prompt."""
    return _snapshot({
        "polymarket": _entry("polymarket"),
        "kalshi": _entry(
            "kalshi",
            tier="optional",
            freshness="stale",
            last_success_at="2026-05-24T09:00:00+00:00",
            last_refresh_attempt_at="2026-05-25T10:34:00+00:00",
            last_refresh_success=False,
            last_refresh_error="upstream 503",
        ),
        "gdelt": _entry(
            "gdelt",
            freshness="stale",
            last_success_at="2026-05-24T22:30:00+00:00",
            last_refresh_attempt_at="2026-05-25T10:34:00+00:00",
            last_refresh_success=False,
            last_refresh_error="upstream timeout after 10s",
        ),
        "etherscan": _entry(
            "etherscan",
            tier="optional",
            cred=False,
            excluded="optional_config_missing",
            freshness="skipped",
            last_success_at=None,
            last_refresh_success=False,
        ),
        "prediction_market_disagreement": _entry(
            "prediction_market_disagreement",
            tier="optional",
            parents=("polymarket", "kalshi"),
            is_derived=True,
            freshness="stale",
            last_success_at="2026-05-24T09:30:00+00:00",
            last_refresh_attempt_at="2026-05-24T10:00:00+00:00",
            last_refresh_success=False,
        ),
    })


# ---------------------------------------------------------------------------
# Fake subprocess + sleep
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.sleeps: list[float] = []

    def runner(self, cmd: list[str]):
        self.commands.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    def sleep(self, s: float) -> None:
        self.sleeps.append(float(s))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_healthy_when_no_stale_active_sources(tmp_path: Path) -> None:
    rec = _Recorder()
    summary_path = tmp_path / "summary.json"
    result = run_watchdog(
        ttl_hours=6,
        max_retries=2,
        backoff_seconds=(1, 2),
        no_sleep=True,
        summary_path=summary_path,
        subprocess_runner=rec.runner,
        sleep_fn=rec.sleep,
        snapshot_fn=lambda **_: _healthy_snapshot_all_fresh(),
    )
    assert result.status == STATUS_HEALTHY
    assert result.exit_code == 0
    assert result.summary["stale_sources_before"] == []
    assert result.summary["stale_sources_after"] == []
    assert "etherscan" in result.summary["excluded_optional_sources"]
    assert rec.commands == []
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == STATUS_HEALTHY
    _assert_safety(payload)


def test_calls_refresh_when_stale(tmp_path: Path) -> None:
    rec = _Recorder()
    snapshots = iter(
        [
            _stale_snapshot_current_scenario(),
            _stale_snapshot_current_scenario(),  # mid (after parent refresh)
            _stale_snapshot_current_scenario(),  # after_attempt
        ]
    )
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=rec.runner,
        sleep_fn=rec.sleep,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert rec.commands, "refresh_live_signals.py must be invoked"
    first_cmd = rec.commands[0]
    assert any("refresh_live_signals.py" in str(p) for p in first_cmd)
    assert "--write" in first_cmd
    # GDELT and Kalshi are stale; both must appear in --sources.
    if "--sources" in first_cmd:
        idx = first_cmd.index("--sources")
        targets = first_cmd[idx + 1].split(",")
        assert "kalshi" in targets
        assert "gdelt" in targets
    assert result.status in {STATUS_STALE_UNCHANGED, STATUS_IMPROVED_BUT_STALE}
    _assert_safety(result.summary)


def test_no_sleep_skips_actual_sleep(tmp_path: Path) -> None:
    rec = _Recorder()
    snapshots = iter([_stale_snapshot_current_scenario()] * 10)
    run_watchdog(
        ttl_hours=6,
        max_retries=2,
        backoff_seconds=(7, 11),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=rec.runner,
        sleep_fn=rec.sleep,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert rec.sleeps == []


def test_stale_unchanged_after_max_retries(tmp_path: Path) -> None:
    rec = _Recorder()
    snapshots = iter([_stale_snapshot_current_scenario()] * 20)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=2,
        backoff_seconds=(1, 1),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=rec.runner,
        sleep_fn=rec.sleep,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert result.status == STATUS_STALE_UNCHANGED
    assert result.exit_code == 1
    assert set(result.summary["stale_sources_after"]) >= {"kalshi", "gdelt", "prediction_market_disagreement"}
    _assert_safety(result.summary)


def test_improved_but_stale_when_one_source_recovers(tmp_path: Path) -> None:
    rec = _Recorder()
    before = _stale_snapshot_current_scenario()

    # mid snapshot: GDELT recovered, Kalshi still stale
    mid_entries = dict(before.entries)
    mid_entries["gdelt"] = _entry(
        "gdelt",
        freshness="fresh",
        last_success_at="2026-05-25T10:36:00+00:00",
        last_refresh_attempt_at="2026-05-25T10:36:00+00:00",
        last_refresh_success=True,
    )
    mid = _snapshot(mid_entries)

    # after snapshot: same — Kalshi & disagreement still stale
    snapshots = iter([before, mid, mid])

    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=rec.runner,
        sleep_fn=rec.sleep,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert result.status == STATUS_IMPROVED_BUT_STALE
    assert result.exit_code == 0
    assert "kalshi" in result.summary["stale_sources_after"]
    assert "gdelt" not in result.summary["stale_sources_after"]
    assert result.summary["freshness_improved"] is True
    _assert_safety(result.summary)


def test_never_healthy_while_stale_active_remain(tmp_path: Path) -> None:
    """The watchdog must NOT claim HEALTHY if any active stale remains."""
    snapshots = iter([_stale_snapshot_current_scenario()] * 10)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert result.status != STATUS_HEALTHY
    assert result.summary["stale_sources_after"], (
        "stale_sources_after must remain non-empty when nothing improved"
    )


def test_etherscan_excluded_when_no_key(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot_current_scenario()] * 5)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert "etherscan" in result.summary["excluded_optional_sources"]
    assert "etherscan" not in result.summary["stale_sources_before"]


def test_gdelt_timeout_not_optional_missing(tmp_path: Path) -> None:
    """GDELT timeout must appear in stale_active, never excluded_optional."""
    snapshots = iter([_stale_snapshot_current_scenario()] * 5)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert "gdelt" in result.summary["stale_sources_before"]
    assert "gdelt" not in result.summary["excluded_optional_sources"]
    gdelt_before = result.summary["gdelt_status_before"]
    assert gdelt_before["is_stale_active"] is True
    assert "timeout" in (gdelt_before.get("last_refresh_error") or "").lower()


def test_kalshi_stale_treated_as_active(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot_current_scenario()] * 5)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert "kalshi" in result.summary["stale_sources_before"]
    assert "kalshi" not in result.summary["excluded_optional_sources"]
    k_before = result.summary["kalshi_status_before"]
    assert k_before["is_stale_active"] is True
    assert k_before["tier"] == "optional"


def test_disagreement_marked_stale_when_kalshi_parent_stale(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot_current_scenario()] * 5)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    dep = result.summary["derived_source_dependency_status"]
    assert "prediction_market_disagreement" in dep
    parents = dep["prediction_market_disagreement"]["parents"]
    assert parents["kalshi"]["is_stale_active"] is True
    # In this scenario, Polymarket is fresh in the snapshot fixture.
    assert parents["polymarket"]["freshness_state"] == "fresh"


def test_summary_safety_invariants(tmp_path: Path) -> None:
    snapshots = iter([_healthy_snapshot_all_fresh()])
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    _assert_safety(result.summary)


def test_summary_per_source_before_after_present_for_tracked_sources(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot_current_scenario()] * 5)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    for src in ("kalshi", "gdelt", "prediction_market_disagreement"):
        assert f"{src}_status_before" in result.summary
        assert f"{src}_status_after" in result.summary


def test_summary_includes_refresh_attempts_with_return_codes(tmp_path: Path) -> None:
    snapshots = iter([_stale_snapshot_current_scenario()] * 5)
    rec = _Recorder()
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=rec.runner,
        sleep_fn=rec.sleep,
        snapshot_fn=lambda **_: next(snapshots),
    )
    attempts = result.summary["refresh_attempts"]
    assert attempts
    actions = attempts[0]["actions"]
    assert actions
    assert any("returncode" in a for a in actions)


def test_error_status_when_snapshot_loader_raises(tmp_path: Path) -> None:
    def _explode(**_):
        raise RuntimeError("simulated db failure")

    result = run_watchdog(
        ttl_hours=6,
        max_retries=1,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=lambda cmd: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=_explode,
    )
    assert result.status == STATUS_ERROR
    assert result.exit_code == 1
    assert any("simulated db failure" in e for e in result.summary["errors"])
    _assert_safety(result.summary)


def test_main_returns_exit_code(monkeypatch, tmp_path: Path) -> None:
    import scripts.watchdog_refresh_stale_sources as wd

    snapshots = iter([_healthy_snapshot_all_fresh()])
    monkeypatch.setattr(
        wd,
        "_load_snapshot",
        lambda **_: next(snapshots),
    )
    monkeypatch.setattr(
        wd,
        "_default_subprocess_runner",
        lambda cmd: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    summary_path = tmp_path / "main_summary.json"
    rc = watchdog_main(
        [
            "--ttl-hours",
            "6",
            "--max-retries",
            "0",
            "--no-sleep",
            "--summary-path",
            str(summary_path),
            "--quiet",
        ]
    )
    assert rc == 0
    assert summary_path.exists()


def _assert_safety(summary: dict) -> None:
    assert summary.get("advisory_only") is True, summary
    assert summary.get("human_execution_required") is True, summary
    assert summary.get("execution_gate") == "LOCKED", summary
    assert summary.get("broker_api_called") is False, summary
    assert summary.get("can_execute") is False, summary
    assert summary.get("ai_execution_count") == 0, summary
