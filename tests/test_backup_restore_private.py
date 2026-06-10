"""Encrypted backup / safe restore proofs (Pass 3, Phase 5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import backup_private_data as bpd
from scripts import restore_private_data as rpd


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("MVP_LOCKDOWN_MODE", raising=False)
    monkeypatch.setenv("MVP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    db = tmp_path / "mvp_local.db"
    db.write_bytes(b"SQLite format 3\x00" + b"journal-bytes" * 100)
    backups = tmp_path / "backups"
    return {"db": db, "backups": backups, "tmp": tmp_path}


def _backup(workspace, **kwargs):
    return bpd.create_backup(
        db_path=workspace["db"], backup_dir=workspace["backups"], **kwargs
    )


def test_backup_creates_archive_manifest_and_checksum(workspace):
    manifest = _backup(workspace)
    archive = Path(manifest["archive_path"])
    manifest_file = Path(manifest["manifest_path"])
    assert archive.exists() and manifest_file.exists()
    assert manifest["archive_sha256"] == bpd.sha256_file(archive)
    assert manifest["env_secrets_included"] is False
    assert manifest["encrypted"] is False
    on_disk = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert on_disk["archive"] == archive.name


def test_backup_never_contains_env_secrets(workspace, monkeypatch):
    import tarfile

    monkeypatch.setenv("EDINET_API_KEY", "super-secret-provider-key")
    manifest = _backup(workspace)
    archive = Path(manifest["archive_path"])
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        assert all(".env" not in n for n in names)
        summary = tar.extractfile("config_summary.redacted.json").read().decode()
    # The summary records THAT the key is set, never its value.
    assert "EDINET_API_KEY" in summary
    assert "super-secret-provider-key" not in summary


def test_restore_dry_run_writes_nothing(workspace):
    manifest = _backup(workspace)
    original = workspace["db"].read_bytes()
    workspace["db"].write_bytes(b"SQLite format 3\x00CHANGED")
    report = rpd.restore(Path(manifest["manifest_path"]), db_path=workspace["db"])
    assert report["mode"] == "dry_run"
    assert workspace["db"].read_bytes() == b"SQLite format 3\x00CHANGED"
    assert any("dry-run" in r for r in report["restored"])
    assert Path(report["report_path"]).exists()
    assert original  # silence unused warning


def test_corrupted_backup_is_refused(workspace):
    manifest = _backup(workspace)
    archive = Path(manifest["archive_path"])
    archive.write_bytes(archive.read_bytes() + b"TAMPER")
    with pytest.raises(rpd.RestoreRefused) as ei:
        rpd.restore(Path(manifest["manifest_path"]), db_path=workspace["db"])
    assert "checksum mismatch" in str(ei.value)


def test_apply_requires_force_when_db_exists(workspace):
    manifest = _backup(workspace)
    with pytest.raises(rpd.RestoreRefused) as ei:
        rpd.restore(Path(manifest["manifest_path"]), apply=True, db_path=workspace["db"])
    assert "--force" in str(ei.value)


def test_apply_with_force_restores_and_keeps_previous(workspace):
    manifest = _backup(workspace)
    original = workspace["db"].read_bytes()
    workspace["db"].write_bytes(b"SQLite format 3\x00DIFFERENT-NOW")
    report = rpd.restore(
        Path(manifest["manifest_path"]), apply=True, force=True,
        db_path=workspace["db"],
    )
    assert workspace["db"].read_bytes() == original
    pre_restore = list(workspace["tmp"].glob("*.pre_restore.*"))
    assert pre_restore, "previous DB must be kept aside"
    assert any("->" in r for r in report["restored"])


def test_apply_to_missing_db_needs_no_force(workspace):
    manifest = _backup(workspace)
    target = workspace["tmp"] / "fresh_location.db"
    report = rpd.restore(
        Path(manifest["manifest_path"]), apply=True, db_path=target
    )
    assert target.exists()
    assert report["mode"] == "apply"


needs_crypto = pytest.mark.skipif(
    not bpd.encryption_available(), reason="optional 'cryptography' package absent"
)


@needs_crypto
def test_encrypted_backup_roundtrip(workspace):
    manifest = _backup(workspace, encrypt=True, passphrase="correct horse battery")
    assert manifest["encrypted"] is True
    archive = Path(manifest["archive_path"])
    assert archive.suffix == ".enc"
    # Raw DB bytes must not appear in the sealed archive.
    assert b"journal-bytes" not in archive.read_bytes()

    target = workspace["tmp"] / "restored.db"
    report = rpd.restore(
        Path(manifest["manifest_path"]), apply=True, db_path=target,
        passphrase="correct horse battery",
    )
    assert target.read_bytes() == workspace["db"].read_bytes()
    assert report["checksum"] == "verified"


@needs_crypto
def test_wrong_passphrase_refused(workspace):
    manifest = _backup(workspace, encrypt=True, passphrase="correct horse battery")
    with pytest.raises(rpd.RestoreRefused) as ei:
        rpd.restore(
            Path(manifest["manifest_path"]), apply=True,
            db_path=workspace["tmp"] / "x.db", passphrase="wrong",
        )
    assert "decryption failed" in str(ei.value)


def test_backup_and_restore_emit_audit_events(workspace, tmp_path):
    from scripts import verify_audit_log as val

    manifest = _backup(workspace)
    rpd.restore(Path(manifest["manifest_path"]), db_path=workspace["db"])
    audit_path = tmp_path / "audit.jsonl"
    events = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines()]
    types = [e["event_type"] for e in events]
    assert "backup" in types and "restore" in types
    assert val.verify_chain(audit_path)["valid"] is True
