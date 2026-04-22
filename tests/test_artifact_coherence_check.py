import json
import subprocess
import sys
from pathlib import Path

from scripts.artifact_coherence_check import build_artifact_coherence_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def _artifact_payload(run_id: str, artifact_written_at: str) -> dict:
    return {
        "run_id": run_id,
        "source_mode": "SYNTHETIC_RUNTIME_FALLBACK",
        "operating_mode": "seeded",
        "truth_origin": "seeded",
        "truth_origin_tags": ["seeded", "placeholder"],
        "artifact_written_at": artifact_written_at,
        "commit_hash": "abc1234",
        "config_fingerprint": "cfg123456789",
    }


def test_artifact_coherence_report_passes_for_consistent_artifacts(scratch_path: Path) -> None:
    runtime_dir = scratch_path / "runtime"
    runtime_dir.mkdir()
    snapshot_log_path = scratch_path / "system_snapshots.jsonl"

    (runtime_dir / "a.json").write_text(
        json.dumps(_artifact_payload("run-1", "2026-04-22T10:00:00+00:00")),
        encoding="utf-8",
    )
    (runtime_dir / "b.json").write_text(
        json.dumps(_artifact_payload("run-1", "2026-04-22T10:00:01+00:00")),
        encoding="utf-8",
    )
    snapshot_row = _artifact_payload("run-1", "2026-04-22T10:00:02+00:00")
    snapshot_row["timestamp"] = "2026-04-22T10:00:02+00:00"
    snapshot_log_path.write_text(json.dumps(snapshot_row) + "\n", encoding="utf-8")

    report = build_artifact_coherence_report(
        runtime_dir=runtime_dir,
        snapshot_log_path=snapshot_log_path,
    )

    assert report["coherent"] is True
    assert report["artifact_count"] == 3
    assert report["missing_fields"] == {}
    assert report["mismatched_fields"] == {}
    assert report["stale_artifacts"] == []


def test_artifact_coherence_report_flags_missing_metadata(scratch_path: Path) -> None:
    runtime_dir = scratch_path / "runtime"
    runtime_dir.mkdir()

    payload = _artifact_payload("run-1", "2026-04-22T10:00:00+00:00")
    payload.pop("commit_hash")
    target = runtime_dir / "missing.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    report = build_artifact_coherence_report(runtime_dir=runtime_dir)

    assert report["coherent"] is False
    assert "commit_hash" in report["missing_fields"][target.as_posix()]


def test_artifact_coherence_check_cli_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "artifact_coherence_check.py"), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert "coherent" in payload
    assert "artifact_count" in payload
    assert "missing_fields" in payload
    assert "mismatched_fields" in payload
