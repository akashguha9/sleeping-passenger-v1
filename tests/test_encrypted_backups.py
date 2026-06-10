"""S4-A4 regression: encrypted backups + guarded restore-to-live staging.

Required proofs: ciphertext is not SQLite-readable; wrong key fails
closed; right key restores with checksum parity; promote-to-live without
a receipt fails; promote creates a pre-promote backup; the key never
appears in logs/metadata/filenames; plain backup mode keeps working.
"""
from __future__ import annotations

import base64
import logging
import sqlite3
from pathlib import Path

import pytest

from scripts import operator_permission_guard as guard
from scripts import persistence
from scripts.backup_crypto import (
    MAGIC,
    BackupCryptoError,
    decrypt_file,
    encrypt_file,
    is_encrypted_backup,
)
from scripts.backup_db import perform_backup
from scripts.backup_scheduler import run_scheduled_backup
from scripts.restore_to_live import (
    OPERATION_CLASS,
    OPERATION_NAME,
    promote_live,
    stage_restore,
)

KEY_A = base64.urlsafe_b64encode(b"A" * 32).decode()
KEY_B = base64.urlsafe_b64encode(b"B" * 32).decode()


@pytest.fixture()
def db(tmp_path) -> Path:
    p = tmp_path / "live.db"
    persistence.init_schema(p)
    persistence.insert_manual_trade(
        "MT_ENC", "EVT", "AAPL", "BUY", 1, 100,
        "2026-01-01T00:00:00Z", "t", "", "human", db_path=p,
    )
    return p


def test_encrypted_backup_is_not_plaintext_sqlite(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_A)
    backup = perform_backup(db, tmp_path / "b", label="enc")
    enc = tmp_path / "b" / "x.db.enc"
    encrypt_file(Path(backup["backup_path"]), enc)
    blob = enc.read_bytes()
    assert blob.startswith(MAGIC)
    assert b"SQLite format 3" not in blob
    assert is_encrypted_backup(enc)
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(str(enc)).execute("SELECT 1 FROM sqlite_master").fetchone()


def test_wrong_key_fails_closed(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_A)
    backup = perform_backup(db, tmp_path / "b", label="enc")
    enc = tmp_path / "b" / "x.db.enc"
    encrypt_file(Path(backup["backup_path"]), enc)
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_B)
    with pytest.raises(BackupCryptoError) as exc:
        decrypt_file(enc, tmp_path / "out.db")
    assert "wrong key or tampered" in str(exc.value)
    assert not (tmp_path / "out.db").exists()


def test_missing_key_fails_closed_for_restore(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_A)
    backup = perform_backup(db, tmp_path / "b", label="enc")
    enc = tmp_path / "b" / "x.db.enc"
    encrypt_file(Path(backup["backup_path"]), enc)
    monkeypatch.delenv("MVP_BACKUP_KEY", raising=False)
    monkeypatch.setattr(
        "scripts.backup_crypto._key_file", lambda: tmp_path / "no_such.key"
    )
    with pytest.raises(BackupCryptoError) as exc:
        decrypt_file(enc, tmp_path / "out.db")
    assert "refusing to proceed without the key" in str(exc.value)


def test_roundtrip_with_correct_key_checksum_parity(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_A)
    backup = perform_backup(db, tmp_path / "b", label="enc")
    plain = Path(backup["backup_path"])
    original = plain.read_bytes()
    enc = tmp_path / "b" / "x.db.enc"
    encrypt_file(plain, enc)
    out = tmp_path / "restored_plain.db"
    decrypt_file(enc, out)
    assert out.read_bytes() == original  # byte-exact AEAD round-trip


def test_scheduler_encrypted_mode_and_plain_compat(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_A)
    # plain mode (default) still works
    r_plain = run_scheduled_backup(db, tmp_path / "plainb")
    assert r_plain["ok"] is True
    assert r_plain.get("encrypted") is not True
    assert Path(r_plain["backup_path"]).suffix == ".db"
    # encrypted mode
    monkeypatch.setenv("MVP_BACKUP_ENCRYPTION", "1")
    r_enc = run_scheduled_backup(db, tmp_path / "encb")
    assert r_enc["ok"] is True
    assert r_enc["encrypted"] is True
    enc_path = Path(r_enc["backup_path"])
    assert enc_path.suffixes[-1] == ".enc"
    assert is_encrypted_backup(enc_path)
    # plaintext sibling removed
    assert not enc_path.with_suffix("").exists()


def test_key_never_in_logs_metadata_or_filenames(db, tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_A)
    monkeypatch.setenv("MVP_BACKUP_ENCRYPTION", "1")
    with caplog.at_level(logging.DEBUG):
        result = run_scheduled_backup(db, tmp_path / "kb")
    text = caplog.text + str(result) + result["backup_path"]
    assert KEY_A not in text
    assert "A" * 32 not in text


# ---------------------------------------------------------------------------
# Restore-to-live staging
# ---------------------------------------------------------------------------


def test_stage_restore_runs_full_check_battery(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_BACKUP_KEY", KEY_A)
    backup = perform_backup(db, tmp_path / "b", label="stagetest")
    enc = tmp_path / "b" / "x.db.enc"
    encrypt_file(Path(backup["backup_path"]), enc)
    staged = stage_restore(enc, tmp_path / "staged.db")
    assert staged["ok"] is True, staged.get("error")
    assert staged["checks"]["decryption"] == "ok"
    assert staged["checks"]["integrity_check"] == "ok"
    assert staged["checks"]["schema_missing_tables"] == []
    assert staged["checks"]["row_counts"]["manual_trades"] == 1
    assert staged["checks"]["broker_api_called_violations"] == 0
    assert staged["execution_gate"] == "LOCKED"


def test_promote_without_receipt_is_refused(db, tmp_path, monkeypatch):
    monkeypatch.setenv(guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "no_receipts"))
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "ADMIN")
    staging = tmp_path / "staged.db"
    backup = perform_backup(db, tmp_path / "b", label="noreceipt")
    assert stage_restore(Path(backup["backup_path"]), staging)["ok"]
    with pytest.raises(PermissionError):
        decision = guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(db), operator_role="ADMIN"
        )
        promote_live(staging, db, permission_decision=decision)


def test_promote_with_receipt_creates_pre_promote_backup(db, tmp_path, monkeypatch):
    monkeypatch.setenv(guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "ADMIN")
    staging = tmp_path / "staged.db"
    backup = perform_backup(db, tmp_path / "b", label="promote")
    assert stage_restore(Path(backup["backup_path"]), staging)["ok"]

    guard.write_dry_run_receipt(OPERATION_NAME, 1, str(db))
    decision = guard.build_apply_decision(
        OPERATION_NAME, OPERATION_CLASS, str(db), operator_role="ADMIN"
    )
    result = promote_live(staging, db, permission_decision=decision)
    assert result["ok"] is True
    pre = Path(result["pre_promote_backup"])
    assert pre.exists() and "pre-promote" in pre.name


def test_promote_requires_admin_floor(db, tmp_path, monkeypatch):
    monkeypatch.setenv(guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    guard.write_dry_run_receipt(OPERATION_NAME, 1, str(db))
    with pytest.raises(PermissionError):
        decision = guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(db), operator_role="OPERATOR"
        )
        promote_live(tmp_path / "staged.db", db, permission_decision=decision)
