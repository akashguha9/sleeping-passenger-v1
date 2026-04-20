import json
import subprocess
import sys
from pathlib import Path

from scripts.trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_trend_report_from_seed_snapshot_log() -> None:
    report = build_trend_report(write_runtime=False)

    assert report["snapshot_count"] >= 3
    assert report["scm_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}
    assert report["chaos_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}
    assert report["watchlist_conversion_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}
    assert report["policy_improvement_trend"]["label"] in {"DETERIORATING", "FLAT", "IMPROVING"}


def test_trend_report_from_scratch_log() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "trend_engine_snapshots.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-04-18T12:00:00+00:00","scm_rate":0.2,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK"],"policy_state":"RESTRICTED","clean_entries":1,"chaos_entries":2,"signals_above_threshold":6,"watchlist_count":3,"chaos_count":2}',
                '{"timestamp":"2026-04-19T12:00:00+00:00","scm_rate":0.25,"scm_state":"LOW_CONVERSION","blockers_active":["GSCE_PHASE_LOCK"],"policy_state":"LIMITED_DEPLOY","clean_entries":2,"chaos_entries":1,"signals_above_threshold":6,"watchlist_count":2,"chaos_count":1}',
                '{"timestamp":"2026-04-20T12:00:00+00:00","scm_rate":0.35,"scm_state":"PARTIAL_CONVERSION","blockers_active":[],"policy_state":"READY","clean_entries":3,"chaos_entries":0,"signals_above_threshold":6,"watchlist_count":1,"chaos_count":0}'
            ]
        ),
        encoding="utf-8",
    )

    try:
        report = build_trend_report(log_path=log_path, write_runtime=False)
        assert report["scm_trend"]["label"] == "IMPROVING"
        assert report["chaos_trend"]["label"] == "IMPROVING"
        assert report["watchlist_conversion_trend"]["label"] == "IMPROVING"
        assert report["policy_improvement_trend"]["label"] == "IMPROVING"
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_trend_engine_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts\\trend_engine.py", "--summary", "--no-write"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Trend Engine"
    assert lines[1].startswith("snapshot_count=")
    assert lines[2].startswith("scm_trend=")
    assert lines[3].startswith("chaos_trend=")
    assert lines[4].startswith("watchlist_conversion_trend=")
    assert lines[5].startswith("policy_improvement_trend=")
