"""Watchdog summary must include the Kalshi split-semantic block.

The watchdog calls ``build_kalshi_truth`` with the live
``datetime.now(timezone.utc)`` (no injectable clock), so the fake
health artifact's ``completed_at_utc`` MUST be generated relative to
wall-clock ``now`` in tests.  Hardcoded ISO strings silently flip from
LIVE_VERIFIED to STALE_HEALTH once 6h elapses and turn the assertion
into a time-bomb.  See [[kalshi-truth-split]] for the api_health vs.
canonical_signal contract.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from scripts.watchdog_refresh_stale_sources import Snapshot, run_watchdog


def _utc_iso(dt: _dt.datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _empty_snapshot(**_kw) -> Snapshot:
    return Snapshot(
        generated_at_utc=_utc_iso(_dt.datetime.now(_dt.timezone.utc)),
        entries={},
        ttl_hours=6,
    )


def _write_health_artifact(health_dir: Path, *, completed_at_utc: str) -> Path:
    health_dir.mkdir(parents=True, exist_ok=True)
    health_path = health_dir / "kalshi_source_health.json"
    health_path.write_text(
        json.dumps(
            {
                "source_freshness_status": "LIVE_VERIFIED",
                "completed_at_utc": completed_at_utc,
                "records_seen_total": 20,
                "records_allowed": 1,
                "records_quarantined": 19,
            }
        ),
        encoding="utf-8",
    )
    return health_path


class _FakeProc:
    returncode = 0
    stdout = ""
    stderr = ""


def _no_op_runner(cmd):  # noqa: ARG001 - signature mandated by watchdog
    return _FakeProc()


def test_watchdog_emits_kalshi_semantic_block(tmp_path, monkeypatch):
    """A fresh Kalshi health artifact must surface as LIVE_VERIFIED."""
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    fresh_completed_at = _utc_iso(now_utc - _dt.timedelta(minutes=1))

    # Provide a minimal Kalshi health artifact at the canonical path so the
    # classifier can populate the block.  We monkeypatch _REPO_ROOT to a
    # tmp tree so the watchdog reads our artifact instead of the operator's.
    _write_health_artifact(
        tmp_path / "runtime" / "release",
        completed_at_utc=fresh_completed_at,
    )

    import scripts.watchdog_refresh_stale_sources as wmod

    monkeypatch.setattr(wmod, "_REPO_ROOT", tmp_path)

    summary_path = tmp_path / "refresh_watchdog_summary.json"
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(0,),
        no_sleep=True,
        summary_path=summary_path,
        snapshot_fn=_empty_snapshot,
        subprocess_runner=_no_op_runner,
        sleep_fn=lambda s: None,
    )
    summary = result.summary
    assert "kalshi_semantic" in summary
    ksem = summary["kalshi_semantic"]
    assert ksem["api_health_status"] == "LIVE_VERIFIED"
    assert "canonical_signal_status" in ksem
    assert "operator_message" in ksem
    assert ksem["advisory_only"] is True
    assert ksem["execution_gate"] == "LOCKED"
    assert ksem["broker_api_called"] is False
    assert ksem["can_execute"] is False


def test_watchdog_marks_old_kalshi_health_artifact_as_stale(tmp_path, monkeypatch):
    """A health artifact older than the 6h TTL must surface as STALE_HEALTH.

    Pinned negative test: production must keep degrading stale Kalshi
    health regardless of how the LIVE_VERIFIED branch is wired.
    """
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    stale_completed_at = _utc_iso(now_utc - _dt.timedelta(hours=24))

    _write_health_artifact(
        tmp_path / "runtime" / "release",
        completed_at_utc=stale_completed_at,
    )

    import scripts.watchdog_refresh_stale_sources as wmod

    monkeypatch.setattr(wmod, "_REPO_ROOT", tmp_path)

    summary_path = tmp_path / "refresh_watchdog_summary.json"
    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(0,),
        no_sleep=True,
        summary_path=summary_path,
        snapshot_fn=_empty_snapshot,
        subprocess_runner=_no_op_runner,
        sleep_fn=lambda s: None,
    )
    ksem = result.summary["kalshi_semantic"]
    assert ksem["api_health_status"] == "STALE_HEALTH"
    assert ksem["semantic_fresh"] is False
    # Safety invariants must remain locked even when health is stale.
    assert ksem["advisory_only"] is True
    assert ksem["execution_gate"] == "LOCKED"
    assert ksem["broker_api_called"] is False
    assert ksem["can_execute"] is False
