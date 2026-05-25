"""Runtime artifact coherence STRICT — every release JSON is stamped or manifest-listed.

Identity Collapse + First-Day Operator sprint, Phase 7.

This complements the existing ``test_runtime_artifact_coherence.py`` (which
asserts ``run_id`` / ``source_mode`` / ``operating_mode`` cohesion within a
single pipeline invocation).  The STRICT variant focuses on the
operator-facing ``runtime/release/`` directory: every JSON artifact there
must either carry the canonical safety stamps OR be listed in the
``docs/runtime_artifact_manifest.json`` with a reason.

Coherence requirement
~~~~~~~~~~~~~~~~~~~~~
``A_unknown`` (artifacts neither stamped nor manifest-listed) must be 0.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO_ROOT / "runtime" / "release"
MANIFEST_PATH = REPO_ROOT / "docs" / "runtime_artifact_manifest.json"


PRIMARY_STAMP_KEYS = (
    "advisory_status",
    "execution_gate",
    "broker_api_called",
    "ai_execution_count",
)

# When the primary keys are absent, an artifact is still considered stamped
# if a recognised legacy equivalent is present.
LEGACY_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "advisory_status": ("advisory_only", "advisory_only_ok"),
    "execution_gate": ("execution_locked",),
    "broker_api_called": (),
    "ai_execution_count": (),
}


def _load_manifest() -> dict:
    assert MANIFEST_PATH.exists(), f"manifest missing: {MANIFEST_PATH}"
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest.get("advisory_status") == "ADVISORY_ONLY"
    assert manifest.get("execution_gate") == "LOCKED"
    assert manifest.get("broker_api_called") is False
    assert manifest.get("ai_execution_count") == 0
    assert manifest.get("jsonl_is_canonical") is False
    return manifest


def _manifest_listed_paths(manifest: dict) -> set[str]:
    out: set[str] = set()
    for key in ("non_dict_artifacts", "legacy_stamped_artifacts", "ignored_artifacts"):
        for entry in manifest.get(key, []) or []:
            p = entry.get("path")
            if isinstance(p, str) and p.strip():
                out.add(p.strip())
    return out


def _has_stamp(data: dict, primary: str) -> bool:
    if primary in data:
        return True
    for legacy in LEGACY_EQUIVALENTS.get(primary, ()):
        if legacy in data:
            return True
    return False


def _is_canonically_stamped(data: dict) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for key in PRIMARY_STAMP_KEYS:
        if not _has_stamp(data, key):
            missing.append(key)
    return (not missing, missing)


def test_strict_manifest_loads_cleanly():
    manifest = _load_manifest()
    assert manifest["manifest_kind"] == "runtime_artifact_manifest"
    assert "canonical_stamp_keys" in manifest


def test_strict_release_artifact_coherence():
    """A_unknown == 0 — every release JSON is stamped OR manifest-listed."""
    if not RELEASE_DIR.exists():
        pytest.skip(f"{RELEASE_DIR} does not exist (gitignored on fresh clones)")

    manifest = _load_manifest()
    listed = _manifest_listed_paths(manifest)

    json_files = sorted(p for p in RELEASE_DIR.iterdir() if p.is_file() and p.suffix == ".json")
    json_files = [p for p in json_files if p.name != "runtime_artifact_manifest.json"]

    a_total = len(json_files)
    a_stamped: list[str] = []
    a_legacy_manifest: list[str] = []
    a_unknown: list[tuple[str, str]] = []

    for path in json_files:
        rel = path.name
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            if rel in listed:
                a_legacy_manifest.append(rel)
                continue
            a_unknown.append((rel, f"parse-error:{type(exc).__name__}"))
            continue

        if not isinstance(data, dict):
            if rel in listed:
                a_legacy_manifest.append(rel)
            else:
                a_unknown.append((rel, f"non-dict-shape:{type(data).__name__}"))
            continue

        ok, missing = _is_canonically_stamped(data)
        if ok:
            a_stamped.append(rel)
            continue

        if rel in listed:
            a_legacy_manifest.append(rel)
            continue

        a_unknown.append((rel, f"missing-keys:{missing}"))

    coherence = (len(a_stamped) + len(a_legacy_manifest)) / max(1, a_total)
    msg = (
        f"a_total={a_total} a_stamped={len(a_stamped)} "
        f"a_legacy_manifest={len(a_legacy_manifest)} a_unknown={len(a_unknown)} "
        f"coherence={coherence:.3f}\nunknown={a_unknown}"
    )
    assert not a_unknown, msg
    assert coherence == 1.0, msg


def test_strict_manifest_listed_paths_have_reasons():
    manifest = _load_manifest()
    for key in ("non_dict_artifacts", "legacy_stamped_artifacts", "ignored_artifacts"):
        for entry in manifest.get(key, []) or []:
            assert entry.get("path"), f"manifest entry in {key} missing 'path': {entry}"
            assert entry.get("reason"), f"manifest entry {entry.get('path')!r} missing 'reason'"


def test_strict_manifest_advisory_stamps_present():
    manifest = _load_manifest()
    for key in PRIMARY_STAMP_KEYS:
        assert key in manifest, f"manifest missing canonical stamp: {key}"
