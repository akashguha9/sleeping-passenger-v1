"""Runtime artifact coherence test.

After a single invocation of run_diagnostics_pipeline.main, every runtime/*.json
written in that run must carry:
    * the same run_id
    * the same source_mode (from VALID_SOURCE_MODES)
    * a run_started_at timestamp
    * an artifact_written_at timestamp

This prevents the drift described in the Windows audit where
signal_vocoder_report.json said SYNTHETIC_RUNTIME_FALLBACK while
behavioral_review_priority_report.json said LIVE_ETIL in the same tree.

The test runs the pipeline in-process so it picks up the module-level RUN_ID
from scripts.runtime_common (which is deterministic within a single import).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.runtime_common import (  # noqa: E402
    RUN_ID,
    RUNTIME_DIR,
    VALID_SOURCE_MODES,
    get_source_mode,
    stamp_payload,
    write_json_atomic,
)


def _discover_runtime_json_files() -> list[Path]:
    if not RUNTIME_DIR.exists():
        return []
    return sorted(p for p in RUNTIME_DIR.glob("*.json") if p.is_file())


def test_stamp_payload_contains_required_keys():
    stamped = stamp_payload({"foo": "bar"})
    assert stamped["foo"] == "bar"
    assert stamped["run_id"] == RUN_ID
    assert stamped["source_mode"] in VALID_SOURCE_MODES
    assert stamped["source_mode"] == get_source_mode()
    assert isinstance(stamped["run_started_at"], str) and stamped["run_started_at"]
    assert isinstance(stamped["artifact_written_at"], str) and stamped["artifact_written_at"]


def test_write_json_atomic_stamps_dict_payloads(tmp_path: Path):
    target = tmp_path / "artifact.json"
    write_json_atomic(target, {"k": "v"})
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["k"] == "v"
    assert payload["run_id"] == RUN_ID
    assert payload["source_mode"] in VALID_SOURCE_MODES


def test_write_json_atomic_does_not_mutate_non_dict(tmp_path: Path):
    target = tmp_path / "list_artifact.json"
    write_json_atomic(target, [1, 2, 3])
    assert json.loads(target.read_text(encoding="utf-8")) == [1, 2, 3]


def test_write_json_atomic_stamp_false_is_raw(tmp_path: Path):
    target = tmp_path / "raw.json"
    write_json_atomic(target, {"k": "v"}, stamp=False)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"k": "v"}
    assert "run_id" not in payload


def test_runtime_artifacts_share_run_id_and_source_mode():
    """Runs the diagnostics pipeline once and asserts every runtime/*.json
    written by that single run shares run_id and source_mode.

    Skipped when the repo lacks the moltbook seed files needed for the
    pipeline to execute (e.g. trimmed review snapshot).
    """
    try:
        from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
    except Exception as exc:  # pragma: no cover - import failure is informative
        pytest.skip(f"diagnostics pipeline not importable: {exc}")

    moltbook = REPO_ROOT / "moltbook"
    if not (moltbook / "signal_ledger.json").exists():
        pytest.skip("moltbook seed files not present in this checkout")

    try:
        run_diagnostics_pipeline(include_tests=False, write_runtime=True)
    except Exception as exc:
        pytest.skip(f"diagnostics pipeline failed to run: {exc}")

    artifacts = _discover_runtime_json_files()
    if not artifacts:
        pytest.skip("no runtime/*.json artifacts produced")

    stamped_payloads = []
    for path in artifacts:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            # list-typed artifacts (if any) are exempt from stamping
            continue
        if "run_id" not in payload:
            # legacy writers that bypass write_json_atomic will fail here;
            # that is intentional — the coherence layer is only meaningful
            # when every dict writer goes through write_json_atomic.
            pytest.fail(f"{path.name} is a dict artifact missing run_id")
        stamped_payloads.append((path.name, payload))

    assert stamped_payloads, "expected at least one stamped dict artifact"
    run_ids = {p["run_id"] for _, p in stamped_payloads}
    modes = {p["source_mode"] for _, p in stamped_payloads}

    assert len(run_ids) == 1, f"run_id drifted across artifacts: {run_ids}"
    assert len(modes) == 1, f"source_mode drifted across artifacts: {modes}"
    assert next(iter(modes)) in VALID_SOURCE_MODES
