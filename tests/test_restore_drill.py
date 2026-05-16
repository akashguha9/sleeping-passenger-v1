"""Tests for the cold restore drill (``scripts/restore_drill.py``).

The drill exists to prove the *restore* half of the backup loop works
*without ever touching the live runtime DB*.  These tests cover:

* Refusal when no backup or manifest is available.
* Successful copy into a fresh temp dir + checksum + DB integrity check.
* Detection of checksum mismatch (corrupted backup).
* Live ``runtime/mvp_local.db`` is never touched, even when the drill
  is run with the real backup root.
* Output carries the standard advisory-only safety stamps and the
  PASS / WARN / FAIL contract.
* No broker / execution / trade-permission language anywhere in the
  drill module or its output.
"""
from __future__ import annotations

import inspect
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import backup_local_state, restore_drill  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_fake_repo(tmp_path: Path) -> Path:
    """Mini-repo with a live DB, paper ledger, refresh summary, logs."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    db_path = runtime / "mvp_local.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t (id) VALUES (1)")
    conn.commit()
    conn.close()

    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "paper_trade_template.csv").write_text(
        "paper_trade_id,thesis\n", encoding="utf-8"
    )
    (exports / "paper_trade_2026Q2.csv").write_text(
        "paper_trade_id,thesis\nT001,test\n", encoding="utf-8"
    )

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "live_signal_refresh_summary.json").write_text(
        json.dumps({"advisory_status": "ADVISORY_ONLY"}), encoding="utf-8"
    )
    return tmp_path


def _patch_backup_module(monkeypatch, repo: Path) -> Path:
    out_root = repo / "backup_local_state"
    monkeypatch.setattr(backup_local_state, "_REPO_ROOT", repo, raising=True)
    monkeypatch.setattr(
        backup_local_state, "_DEFAULT_DB", repo / "runtime" / "mvp_local.db", raising=True
    )
    monkeypatch.setattr(
        backup_local_state, "_DEFAULT_OUT_ROOT", out_root, raising=True
    )
    return out_root


def _patch_drill_module(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(restore_drill, "_REPO_ROOT", repo, raising=True)
    monkeypatch.setattr(
        restore_drill, "_LIVE_RUNTIME_DB", repo / "runtime" / "mvp_local.db", raising=True
    )
    monkeypatch.setattr(
        restore_drill,
        "_DEFAULT_BACKUP_ROOT",
        repo / "backup_local_state",
        raising=True,
    )


def _create_real_backup(repo: Path) -> Path:
    """Use the real backup_local_state.perform_backup to seed a backup."""
    out_root = repo / "backup_local_state"
    result = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=False
    )
    assert result["ok"], result["errors"]
    return Path(result["backup_dir"])


# ---------------------------------------------------------------------------
# Behavior
# ---------------------------------------------------------------------------


def test_no_backup_present_returns_fail_with_clear_error(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    # No backup_local_state/ directory created — drill must FAIL but stay
    # read-only and never touch the live DB.
    report = restore_drill.perform_drill(
        backup_dir=None,
        backup_root=repo / "backup_local_state",
        temp_dir=tmp_path / "drill",
    )
    assert report["status"] == restore_drill.STATUS_FAIL
    assert any("no_backup_found" in e for e in report["errors"])
    assert report["live_runtime_db_touched"] is False


def test_manifest_missing_in_target_is_rejected(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    bogus = repo / "backup_local_state" / "not_a_backup"
    bogus.mkdir(parents=True)
    (bogus / "exports").mkdir()
    # Intentionally no manifest.json.

    report = restore_drill.perform_drill(
        backup_dir=bogus,
        backup_root=repo / "backup_local_state",
        temp_dir=tmp_path / "drill",
    )
    assert report["status"] == restore_drill.STATUS_FAIL
    assert any("manifest_missing" in e for e in report["errors"])


def test_drill_copies_into_temp_and_verifies_checksums(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    backup_dir = _create_real_backup(repo)
    drill_dir = tmp_path / "drill"

    report = restore_drill.perform_drill(
        backup_dir=backup_dir,
        backup_root=repo / "backup_local_state",
        temp_dir=drill_dir,
        keep=True,
    )

    assert report["status"] == restore_drill.STATUS_PASS, report
    restored = Path(report["restored_dir"])
    assert restored.is_dir()
    assert (restored / "manifest.json").is_file()
    # Restored DB is present + verify_backup passed PRAGMA integrity_check.
    db_info = report["verify"].get("db_integrity")
    assert db_info is not None
    assert db_info["ok"] is True
    assert db_info["result"] == "ok"
    # All copied files matched their manifest checksums.
    assert all(
        f.get("sha256_match") is True for f in report["verify"]["files_checked"]
    )


def test_drill_detects_checksum_mismatch(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    backup_dir = _create_real_backup(repo)
    # Corrupt a copied file in the backup *before* the drill copies it
    # into temp — verify_backup runs against the copied tree and will
    # detect the mismatch.
    target = backup_dir / "exports" / "paper_trade_2026Q2.csv"
    target.write_text("CORRUPTED-PAYLOAD\n", encoding="utf-8")

    drill_dir = tmp_path / "drill"
    report = restore_drill.perform_drill(
        backup_dir=backup_dir,
        backup_root=repo / "backup_local_state",
        temp_dir=drill_dir,
        keep=True,
    )

    assert report["status"] == restore_drill.STATUS_FAIL
    assert any(
        "checksum" in e or "size" in e for e in report["verify"]["errors"]
    )


def test_drill_runs_integrity_check_on_restored_db_copy_only(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    backup_dir = _create_real_backup(repo)
    drill_dir = tmp_path / "drill"

    # Snapshot live DB bytes before the drill.
    live_db = repo / "runtime" / "mvp_local.db"
    before = live_db.read_bytes()

    report = restore_drill.perform_drill(
        backup_dir=backup_dir,
        backup_root=repo / "backup_local_state",
        temp_dir=drill_dir,
        keep=True,
    )

    # PRAGMA integrity_check ran against the *restored copy*, not the live DB.
    db_info = report["verify"]["db_integrity"]
    assert db_info["ok"] is True
    # Live DB byte-identical after the drill — proves it was untouched.
    after = live_db.read_bytes()
    assert before == after
    assert report["live_runtime_db_touched"] is False


def test_drill_never_touches_runtime_db_when_corrupted(tmp_path, monkeypatch):
    """Even when verification fails, the live runtime DB must stay intact."""
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    backup_dir = _create_real_backup(repo)
    # Corrupt the copied DB inside the backup tree so the restored copy
    # also has a tampered file.
    (backup_dir / "exports" / "paper_trade_2026Q2.csv").write_text(
        "broken\n", encoding="utf-8"
    )
    drill_dir = tmp_path / "drill"

    live_db = repo / "runtime" / "mvp_local.db"
    before = live_db.read_bytes()

    report = restore_drill.perform_drill(
        backup_dir=backup_dir,
        backup_root=repo / "backup_local_state",
        temp_dir=drill_dir,
        keep=True,
    )
    after = live_db.read_bytes()

    assert before == after
    assert report["live_runtime_db_touched"] is False
    assert report["status"] in (
        restore_drill.STATUS_FAIL,
        restore_drill.STATUS_WARN,
    )


def test_drill_output_carries_safety_stamps(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)
    backup_dir = _create_real_backup(repo)

    report = restore_drill.perform_drill(
        backup_dir=backup_dir,
        backup_root=repo / "backup_local_state",
        temp_dir=tmp_path / "drill",
        keep=True,
    )

    assert report["advisory_only"] is True
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["execution_permission"] is False
    assert report["can_execute"] is False
    assert report["ai_execution_count"] == 0


def test_drill_emits_pass_warn_fail_contract(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    # Failing path (no backup at all).
    fail_report = restore_drill.perform_drill(
        backup_dir=None,
        backup_root=repo / "backup_local_state",
        temp_dir=tmp_path / "drill_fail",
    )
    assert fail_report["status"] in {
        restore_drill.STATUS_PASS,
        restore_drill.STATUS_WARN,
        restore_drill.STATUS_FAIL,
    }
    assert fail_report["status"] == restore_drill.STATUS_FAIL

    # Passing path.
    _create_real_backup(repo)
    pass_report = restore_drill.perform_drill(
        backup_dir=None,
        backup_root=repo / "backup_local_state",
        temp_dir=tmp_path / "drill_pass",
        keep=True,
    )
    assert pass_report["status"] == restore_drill.STATUS_PASS


def test_drill_module_has_no_broker_or_execution_language() -> None:
    src = inspect.getsource(restore_drill)
    lowered = src.lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "trade now",
        "ai-approved",
        "permission to trade",
        "auto-trading",
        "order_id",
    ):
        assert forbidden not in lowered, (
            f"forbidden phrase {forbidden!r} present in restore_drill"
        )
    # Also confirm no broker-vendor names made it in.
    for pat in (
        r"\balpaca\b",
        r"\bibkr\b",
        r"\binteractive[\s_-]?brokers\b",
        r"\btd[\s_-]?ameritrade\b",
        r"\bschwab[\s_-]?api\b",
        r"\boanda\b",
    ):
        assert re.search(pat, src, flags=re.IGNORECASE) is None, pat


def test_drill_output_has_no_secrets(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    # Plant a secret in .env to be sure the drill never reads it.
    (repo / ".env").write_text("MVP_API_TOKEN=hunter2\n", encoding="utf-8")
    _patch_backup_module(monkeypatch, repo)
    _patch_drill_module(monkeypatch, repo)

    backup_dir = _create_real_backup(repo)
    report = restore_drill.perform_drill(
        backup_dir=backup_dir,
        backup_root=repo / "backup_local_state",
        temp_dir=tmp_path / "drill",
        keep=True,
    )
    serialized = json.dumps(report, default=str)
    assert "hunter2" not in serialized
    assert "MVP_API_TOKEN=" not in serialized
