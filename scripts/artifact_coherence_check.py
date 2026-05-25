from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.runtime_common import RUNTIME_DIR, SNAPSHOT_LOG_PATH, repo_relative
except ModuleNotFoundError:
    from runtime_common import RUNTIME_DIR, SNAPSHOT_LOG_PATH, repo_relative


REQUIRED_FIELDS = [
    "run_id",
    "source_mode",
    "operating_mode",
    "truth_origin",
    "truth_origin_tags",
    "artifact_written_at",
    "commit_hash",
    "config_fingerprint",
]
COMPARE_FIELDS = [
    "run_id",
    "source_mode",
    "operating_mode",
    "truth_origin",
    "commit_hash",
    "config_fingerprint",
]


def _classify_artifact_state(name: str, payload: dict[str, Any], missing: list[str]) -> str:
    artifact_kind = str(payload.get("artifact_kind") or "").strip().lower()
    if not missing:
        return "managed"
    if artifact_kind.endswith("_runtime_artifact") and len(missing) >= 4:
        return "legacy_unmanaged"
    if "run_id" in missing and "artifact_written_at" in missing:
        return "legacy_unmanaged"
    return "partial_metadata"


def _read_text_bom_tolerant(path: Path) -> str | None:
    """Read ``path`` as text, tolerating UTF-8 BOM, UTF-16 LE/BE BOM, and CP1252.

    Returns ``None`` when the file cannot be decoded at all so callers can
    silently skip pollution (e.g. a runtime artifact written via PowerShell
    ``Out-File`` which defaults to UTF-16 LE) rather than crashing the
    governance check.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            return None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _load_json_payload(path: Path) -> dict[str, Any] | None:
    text = _read_text_bom_tolerant(path)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _latest_snapshot_row(path: Path) -> tuple[str, dict[str, Any]] | None:
    if not path.exists():
        return None
    text = _read_text_bom_tolerant(path)
    if text is None:
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return (f"{repo_relative(path)}:last", payload)


def _artifact_written_sort_key(payload: dict[str, Any]) -> str:
    return str(payload.get("artifact_written_at") or payload.get("timestamp") or "")


def build_artifact_coherence_report(
    runtime_dir: Path | None = None,
    snapshot_log_path: Path | None = None,
) -> dict[str, Any]:
    resolved_runtime_dir = runtime_dir or RUNTIME_DIR
    resolved_snapshot_log_path = snapshot_log_path or SNAPSHOT_LOG_PATH

    artifacts: list[tuple[str, dict[str, Any]]] = []
    if resolved_runtime_dir.exists():
        for path in sorted(resolved_runtime_dir.glob("*.json")):
            payload = _load_json_payload(path)
            if payload is None:
                continue
            artifacts.append((repo_relative(path), payload))

    latest_snapshot = _latest_snapshot_row(resolved_snapshot_log_path)
    if latest_snapshot is not None:
        artifacts.append(latest_snapshot)

    missing_fields: dict[str, list[str]] = {}
    artifact_states: dict[str, str] = {}
    field_values: dict[str, set[str]] = {field: set() for field in COMPARE_FIELDS}
    reference_run_id = None
    reference_written_at = None
    stale_artifacts: list[str] = []

    if artifacts:
        latest_name, latest_payload = max(artifacts, key=lambda item: _artifact_written_sort_key(item[1]))
        reference_run_id = latest_payload.get("run_id")
        reference_written_at = latest_payload.get("artifact_written_at") or latest_payload.get("timestamp")
        if reference_run_id is None:
            stale_artifacts.append(latest_name)

    for name, payload in artifacts:
        missing = []
        for field in REQUIRED_FIELDS:
            value = payload.get(field)
            if value is None or value == "":
                missing.append(field)
            elif field in COMPARE_FIELDS:
                field_values[field].add(json.dumps(value, sort_keys=True))
        artifact_states[name] = _classify_artifact_state(name, payload, missing)
        if missing:
            missing_fields[name] = missing
        if reference_run_id and payload.get("run_id") not in {None, reference_run_id}:
            stale_artifacts.append(name)

    mismatched_fields = {
        field: sorted(values)
        for field, values in field_values.items()
        if len(values) > 1
    }
    legacy_artifacts = sorted(
        name for name, state in artifact_states.items() if state == "legacy_unmanaged"
    )
    coherent = bool(artifacts) and not missing_fields and not mismatched_fields and not stale_artifacts
    return {
        "coherent": coherent,
        "artifact_count": len(artifacts),
        "required_fields": REQUIRED_FIELDS,
        "reference_run_id": reference_run_id,
        "reference_written_at": reference_written_at,
        "missing_fields": missing_fields,
        "artifact_states": artifact_states,
        "legacy_artifacts": legacy_artifacts,
        "mismatched_fields": mismatched_fields,
        "stale_artifacts": sorted(set(stale_artifacts)),
        "artifacts_checked": [name for name, _ in artifacts],
        "note": (
            "Flags mixed-run, mixed-mode, partially stamped, and legacy unmanaged artifacts "
            "across runtime JSON outputs and the latest snapshot row."
        ),
    }


def format_artifact_coherence_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Artifact Coherence Check",
            f"coherent={str(report['coherent']).lower()}",
            f"artifact_count={report['artifact_count']}",
            f"reference_run_id={report['reference_run_id']}",
            f"legacy_artifact_count={len(report['legacy_artifacts'])}",
            f"stale_artifact_count={len(report['stale_artifacts'])}",
            f"mismatch_field_count={len(report['mismatched_fields'])}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check whether current runtime artifacts share coherent run metadata."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_artifact_coherence_report()
    if args.summary:
        print(format_artifact_coherence_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
