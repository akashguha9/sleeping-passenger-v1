"""Fix 3: the diagnostics --summary surfaces a read-only stale/legacy advisory.

Constructs runtime artifacts in a tmp dir (no shared fixtures, no conftest
changes) and asserts the advisory line exposes the stale/legacy/mismatch
counts. The advisory is informational only and must not touch governance.
"""

import json
from pathlib import Path

from scripts.run_diagnostics_pipeline import format_artifact_coherence_advisory


def test_coherence_advisory_line_surfaces_stale_count(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    # Newer artifact establishes the reference run_id.
    (runtime_dir / "current.json").write_text(
        json.dumps(
            {
                "run_id": "RUN_CURRENT",
                "artifact_written_at": "2026-06-04T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    # Older artifact carries a different run_id -> classified as stale.
    (runtime_dir / "leftover.json").write_text(
        json.dumps(
            {
                "run_id": "RUN_PREVIOUS",
                "artifact_written_at": "2026-06-04T11:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    line = format_artifact_coherence_advisory(
        runtime_dir=runtime_dir,
        snapshot_log_path=tmp_path / "no_such_snapshots.jsonl",
    )

    assert line.startswith("artifact_coherence_advisory=")
    assert "stale=1" in line
    assert "legacy=" in line
    assert "mismatched=" in line
    assert "coherent=" in line
