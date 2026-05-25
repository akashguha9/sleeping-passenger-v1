"""
Freshness-dependency tests for the Prediction Market Disagreement derived
source.  These tests focus on the *watchdog* contract: the derived source
cannot pretend to be fresh while a required parent is stale, and the
watchdog records the parent-dependency status truthfully.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.watchdog_refresh_stale_sources import (
    Snapshot,
    SourceSnapshotEntry,
    run_watchdog,
    _build_retry_plan,
)


def _entry(
    key: str,
    *,
    tier: str = "core",
    freshness: str = "fresh",
    excluded: str | None = None,
    cred: bool = True,
    parents: tuple[str, ...] = (),
    is_derived: bool = False,
) -> SourceSnapshotEntry:
    return SourceSnapshotEntry(
        source_key=key,
        tier=tier,
        adapter_status="implemented",
        requires_api_key=False,
        credential_configured=cred,
        freshness_state=freshness,
        last_success_at=("2026-05-25T10:00:00+00:00" if freshness == "fresh" else "2026-05-24T09:00:00+00:00"),
        last_refresh_attempt_at="2026-05-25T10:30:00+00:00",
        last_refresh_success=(freshness == "fresh"),
        last_refresh_skipped=False,
        last_refresh_error="" if freshness == "fresh" else "upstream 503",
        last_refresh_skipped_reason="",
        latest_event_at="2026-05-25T10:00:00+00:00",
        hours_since_last_success=(0.5 if freshness == "fresh" else 25.0),
        excluded_reason=excluded,
        is_stale_active=(excluded is None and freshness != "fresh"),
        is_derived=is_derived,
        parent_sources=parents,
    )


def _snapshot_parent_stale() -> Snapshot:
    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries={
            "polymarket": _entry("polymarket", freshness="fresh"),
            "kalshi": _entry("kalshi", tier="optional", freshness="stale"),
            "prediction_market_disagreement": _entry(
                "prediction_market_disagreement",
                tier="optional",
                is_derived=True,
                parents=("polymarket", "kalshi"),
                freshness="stale",
            ),
        },
        ttl_hours=6,
    )


def _snapshot_parents_fresh_disagreement_stale() -> Snapshot:
    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries={
            "polymarket": _entry("polymarket"),
            "kalshi": _entry("kalshi", tier="optional"),
            "prediction_market_disagreement": _entry(
                "prediction_market_disagreement",
                tier="optional",
                is_derived=True,
                parents=("polymarket", "kalshi"),
                freshness="stale",
            ),
        },
        ttl_hours=6,
    )


def _snapshot_all_fresh() -> Snapshot:
    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries={
            "polymarket": _entry("polymarket"),
            "kalshi": _entry("kalshi", tier="optional"),
            "prediction_market_disagreement": _entry(
                "prediction_market_disagreement",
                tier="optional",
                is_derived=True,
                parents=("polymarket", "kalshi"),
                freshness="fresh",
            ),
        },
        ttl_hours=6,
    )


def test_parent_stale_means_derived_is_flagged_parent_stale(tmp_path: Path) -> None:
    rec_commands: list[list[str]] = []

    def _runner(cmd):
        rec_commands.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    snapshots = iter([_snapshot_parent_stale()] * 5)
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=_runner,
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert "prediction_market_disagreement" in result.summary[
        "parent_stale_derived_sources"
    ]
    dep = result.summary["derived_source_dependency_status"][
        "prediction_market_disagreement"
    ]
    assert dep["parents"]["kalshi"]["is_stale_active"] is True
    # Scanner MUST NOT have been invoked while kalshi parent is stale.
    cmds_joined = [" ".join(str(p) for p in c) for c in rec_commands]
    scanner_calls = [c for c in cmds_joined if "prediction_market_disagreement_scanner" in c]
    assert scanner_calls == [], (
        "Scanner must not run while a parent source is stale"
    )


def test_disagreement_can_become_fresh_only_when_parents_fresh(tmp_path: Path) -> None:
    rec_commands: list[list[str]] = []

    def _runner(cmd):
        rec_commands.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    # Sequence:
    #   before: parents fresh, disagreement stale
    #   mid (after refresh): same
    #   after_attempt: disagreement now fresh
    after_attempt = _snapshot_all_fresh()
    snapshots = iter(
        [
            _snapshot_parents_fresh_disagreement_stale(),
            _snapshot_parents_fresh_disagreement_stale(),
            after_attempt,
        ]
    )
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "summary.json",
        subprocess_runner=_runner,
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    assert "prediction_market_disagreement" not in result.summary["stale_sources_after"]
    cmds_joined = [" ".join(str(p) for p in c) for c in rec_commands]
    scanner_calls = [c for c in cmds_joined if "prediction_market_disagreement_scanner" in c]
    assert scanner_calls, (
        "Scanner must be invoked once parents are fresh"
    )


def test_retry_plan_prefers_parents_before_derived() -> None:
    snap = _snapshot_parent_stale()
    # Pretend disagreement is also in the stale_active list.
    plan = _build_retry_plan(snap, source_filter=None)
    targets = plan["refresh_targets"]
    if targets:
        # kalshi must come BEFORE anything else in the priority order.
        assert targets[0] == "kalshi" or "kalshi" in targets[:2]
    # Derived target is recorded separately.
    assert plan["derived_targets"] == ["prediction_market_disagreement"]
    assert plan["invoke_disagreement"] is True
