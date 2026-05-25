"""
Pin the same-tick disagreement-recompute tracking fields added to
the watchdog summary:

  - parent_recovery_detected (bool)
  - disagreement_recompute_invoked_in_tick (bool)
  - derived_recompute_attempts (list[dict])
  - derived_recompute_skipped (list[dict])

When a previously stale Kalshi parent becomes fresh inside the same
watchdog tick (because the parent refresh succeeded), the watchdog
must record:
  - parent_recovery_detected=True
  - disagreement_recompute_invoked_in_tick=True
  - one entry in derived_recompute_attempts

When a parent remains stale, the scanner must be skipped with reason
"parents_not_fresh" and an entry must appear in
derived_recompute_skipped.  The summary must NOT silently drop the
attempt.
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
    FRESHNESS_DEGRADED_PARENT_STALE,
    Snapshot,
    SourceSnapshotEntry,
    run_watchdog,
)


def _entry(
    key,
    freshness="fresh",
    tier="core",
    parents=(),
    is_derived=False,
    excluded=None,
):
    return SourceSnapshotEntry(
        source_key=key,
        tier=tier,
        adapter_status="implemented",
        requires_api_key=False,
        credential_configured=True,
        freshness_state=freshness,
        last_success_at="2026-05-25T10:00:00+00:00",
        last_refresh_attempt_at="2026-05-25T10:30:00+00:00",
        last_refresh_success=(freshness == "fresh"),
        last_refresh_skipped=False,
        last_refresh_error="",
        last_refresh_skipped_reason="",
        latest_event_at="2026-05-25T10:00:00+00:00",
        hours_since_last_success=0.5 if freshness == "fresh" else 25.0,
        excluded_reason=excluded,
        is_stale_active=(excluded is None and freshness != "fresh"),
        is_derived=is_derived,
        parent_sources=parents,
    )


def _snap(entries):
    return Snapshot(
        generated_at_utc="2026-05-25T10:35:00+00:00",
        entries=dict(entries),
        ttl_hours=6,
    )


def _scanner_runner(commands_seen):
    def _run(cmd):
        commands_seen.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    return _run


def test_parent_recovery_triggers_same_tick_recompute(tmp_path):
    # before: kalshi stale, polymarket fresh, PMD degraded_parent_stale
    before = _snap(
        {
            "polymarket": _entry("polymarket"),
            "kalshi": _entry("kalshi", freshness="stale", tier="optional"),
            "prediction_market_disagreement": _entry(
                "prediction_market_disagreement",
                tier="optional",
                parents=("polymarket", "kalshi"),
                is_derived=True,
                freshness=FRESHNESS_DEGRADED_PARENT_STALE,
            ),
        }
    )
    # mid (after parent refresh): kalshi is now fresh
    mid_entries = dict(before.entries)
    mid_entries["kalshi"] = _entry("kalshi", tier="optional")
    mid = _snap(mid_entries)
    # after_attempt: same as mid (disagreement recompute happens, but
    # the mock runner does not insert a PMD source_run_log row in this
    # unit test — what matters is the tracking fields).
    after = mid
    snapshots = iter([before, mid, after])
    commands_seen: list[list[str]] = []

    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "s.json",
        subprocess_runner=_scanner_runner(commands_seen),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    summary = result.summary
    assert summary["parent_recovery_detected"] is True
    assert summary["disagreement_recompute_invoked_in_tick"] is True
    assert len(summary["derived_recompute_attempts"]) >= 1
    attempt = summary["derived_recompute_attempts"][0]
    assert "kalshi" in attempt["recovered_parents"]
    assert attempt["parent_states"]["polymarket"] == "fresh"
    assert attempt["parent_states"]["kalshi"] == "fresh"
    # The scanner command was actually invoked.
    cmds = [" ".join(c) for c in commands_seen]
    assert any("prediction_market_disagreement_scanner.py" in c for c in cmds)


def test_parent_remains_stale_records_skip_with_reason(tmp_path):
    # before: kalshi stale, polymarket fresh, PMD degraded_parent_stale
    before = _snap(
        {
            "polymarket": _entry("polymarket"),
            "kalshi": _entry("kalshi", freshness="stale", tier="optional"),
            "prediction_market_disagreement": _entry(
                "prediction_market_disagreement",
                tier="optional",
                parents=("polymarket", "kalshi"),
                is_derived=True,
                freshness=FRESHNESS_DEGRADED_PARENT_STALE,
            ),
        }
    )
    # mid (after parent refresh): kalshi STILL stale
    mid = before
    after = before
    snapshots = iter([before, mid, after])
    commands_seen: list[list[str]] = []

    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "s.json",
        subprocess_runner=_scanner_runner(commands_seen),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: next(snapshots),
    )
    summary = result.summary
    assert summary["parent_recovery_detected"] is False
    assert summary["disagreement_recompute_invoked_in_tick"] is False
    # The skip must be RECORDED with the reason, not silently dropped.
    assert len(summary["derived_recompute_skipped"]) >= 1
    skip = summary["derived_recompute_skipped"][0]
    assert skip["reason"] == "parents_not_fresh"
    # Scanner command was NOT invoked.
    cmds = [" ".join(c) for c in commands_seen]
    assert not any("prediction_market_disagreement_scanner.py" in c for c in cmds)


def test_no_execution_keys_in_recompute_payload(tmp_path):
    """Defensive sweep: the new fields cannot ever introduce broker/execution keys."""
    before = _snap({"polymarket": _entry("polymarket")})
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(1,),
        no_sleep=True,
        summary_path=tmp_path / "s.json",
        subprocess_runner=lambda c: types.SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        sleep_fn=lambda s: None,
        snapshot_fn=lambda **_: before,
    )
    summary = result.summary
    forbidden = {"order_placed", "broker_order_id", "execute_trade", "broker_url"}
    for k in forbidden:
        assert k not in summary
    # Safety stamps still present.
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["can_execute"] is False
    assert summary["ai_execution_count"] == 0
