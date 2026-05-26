"""Watchdog summary must include the Kalshi split-semantic block."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.watchdog_refresh_stale_sources import Snapshot, run_watchdog


def _empty_snapshot(**_kw) -> Snapshot:
    return Snapshot(generated_at_utc="2026-05-26T20:00:00+00:00", entries={}, ttl_hours=6)


def test_watchdog_emits_kalshi_semantic_block(tmp_path, monkeypatch):
    summary_path = tmp_path / "refresh_watchdog_summary.json"
    # Provide a minimal Kalshi health artifact at the canonical path so the
    # classifier can populate the block.  We monkeypatch _REPO_ROOT to a
    # tmp tree so the watchdog reads our artifact instead of the operator's.
    health_dir = tmp_path / "runtime" / "release"
    health_dir.mkdir(parents=True)
    health_path = health_dir / "kalshi_source_health.json"
    health_path.write_text(
        json.dumps(
            {
                "source_freshness_status": "LIVE_VERIFIED",
                "completed_at_utc": "2026-05-26T19:59:00+00:00",
                "records_seen_total": 20,
                "records_allowed": 1,
                "records_quarantined": 19,
            }
        ),
        encoding="utf-8",
    )

    import scripts.watchdog_refresh_stale_sources as wmod

    monkeypatch.setattr(wmod, "_REPO_ROOT", tmp_path)

    runner_calls: list[list[str]] = []

    class _FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _runner(cmd):
        runner_calls.append(list(cmd))
        return _FakeProc()

    result = run_watchdog(
        ttl_hours=6,
        max_retries=0,
        backoff_seconds=(0,),
        no_sleep=True,
        summary_path=summary_path,
        snapshot_fn=_empty_snapshot,
        subprocess_runner=_runner,
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
