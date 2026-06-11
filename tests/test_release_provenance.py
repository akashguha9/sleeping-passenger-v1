"""Release provenance proofs (Pass 3, Phase 8)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import build_release_manifest as brm
from scripts import generate_checksums as gc

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_manifest_includes_required_fields():
    manifest = brm.build_manifest(test_summary="6551 passed")
    for field in (
        "generated_utc", "git_commit", "git_branch", "git_dirty",
        "python_version", "node_version", "file_hashes", "test_summary",
        "advisory_invariants",
    ):
        assert field in manifest, field
    assert manifest["test_summary"] == "6551 passed"
    hashes = manifest["file_hashes"]
    for key in ("requirements.txt", "frontend/package-lock.json",
                ".github/workflows/pytest.yml", "scripts/api_server.py"):
        assert key in hashes
        assert len(hashes[key]) == 64  # real sha256, file exists


def test_manifest_pins_advisory_invariants():
    inv = brm.build_manifest()["advisory_invariants"]
    assert inv["advisory_status"] == "ADVISORY_ONLY"
    assert inv["execution_mode"] == "HUMAN_ONLY"
    assert inv["execution_gate"] == "LOCKED"
    assert inv["ai_execution_count"] == 0
    assert inv["broker_api_called"] is False


def test_dirty_state_is_flagged(monkeypatch):
    monkeypatch.setattr(brm, "_git", lambda *a: "M somefile" if "status" in a else "abc")
    manifest = brm.build_manifest()
    assert manifest["git_dirty"] is True
    assert "DIRTY" in (manifest["dirty_warning"] or "")
    monkeypatch.setattr(brm, "_git", lambda *a: "" if "status" in a else "abc")
    assert brm.build_manifest()["git_dirty"] is False


def test_checksums_write_and_verify_roundtrip(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "requirements.txt").write_text("pkg==1\n", encoding="utf-8")
    (root / "LICENSE").write_text("All Rights Reserved\n", encoding="utf-8")
    dist = root / "dist"
    sums = gc.write_sums(root, dist)
    assert sums.exists()
    assert gc.verify_sums(root, dist) == []


def test_checksum_verification_catches_tampering(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "requirements.txt"
    target.write_text("pkg==1\n", encoding="utf-8")
    dist = root / "dist"
    gc.write_sums(root, dist)
    target.write_text("pkg==1\nmalicious-extra==9\n", encoding="utf-8")
    problems = gc.verify_sums(root, dist)
    assert any("MISMATCH" in p for p in problems)


def test_checksum_verification_catches_missing_file(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "LICENSE").write_text("x\n", encoding="utf-8")
    dist = root / "dist"
    gc.write_sums(root, dist)
    (root / "LICENSE").unlink()
    problems = gc.verify_sums(root, dist)
    assert any("missing" in p for p in problems)


def test_checksums_cover_newest_manifest(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "LICENSE").write_text("x\n", encoding="utf-8")
    dist = root / "dist"
    dist.mkdir()
    (dist / "release_manifest_20260101T000000Z.json").write_text("{}", encoding="utf-8")
    (dist / "release_manifest_20260601T000000Z.json").write_text(
        json.dumps({"newer": True}), encoding="utf-8"
    )
    sums = gc.write_sums(root, dist)
    text = sums.read_text(encoding="utf-8")
    assert "release_manifest_20260601T000000Z.json" in text
    assert "release_manifest_20260101T000000Z.json" not in text
