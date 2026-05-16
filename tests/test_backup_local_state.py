"""Sprint 10C tests — private operator backup + verify.

Covers backup_local_state.py (plan / dry-run / real copy / manifest /
no-env / advisory invariants) and verify_backup.py (good / missing /
checksum mismatch / integrity_check).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import backup_local_state, verify_backup  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_repo(tmp_path: Path, *, with_db: bool = True, with_paper: bool = True) -> Path:
    """Build a miniature repo layout the backup script can read."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    if with_db:
        db_path = runtime / "mvp_local.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t (id) VALUES (1)")
        conn.commit()
        conn.close()

    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "paper_trade_template.csv").write_text("paper_trade_id,thesis\n", encoding="utf-8")
    if with_paper:
        (exports / "paper_trade_2026Q2.csv").write_text(
            "paper_trade_id,thesis\nT001,test\n", encoding="utf-8"
        )

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "live_signal_refresh_summary.json").write_text(
        json.dumps({"advisory_status": "ADVISORY_ONLY"}), encoding="utf-8"
    )
    (logs / "live_signal_refresh.log").write_text("[2026-05-16] ok\n", encoding="utf-8")
    return tmp_path


def _patch_repo(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(backup_local_state, "_REPO_ROOT", repo, raising=True)
    monkeypatch.setattr(backup_local_state, "_DEFAULT_DB", repo / "runtime" / "mvp_local.db", raising=True)
    monkeypatch.setattr(
        backup_local_state, "_DEFAULT_OUT_ROOT", repo / "backup_local_state", raising=True
    )


# ---------------------------------------------------------------------------
# backup_local_state
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write_files(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"

    result = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=True
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert not (out_root.exists()), "dry-run must not create the backup directory"
    # Files were *planned* but not copied.
    relatives = {f["relative"] for f in result["files_copied"]}
    assert "runtime/mvp_local.db" in relatives
    assert "exports/paper_trade_template.csv" in relatives
    assert "exports/paper_trade_2026Q2.csv" in relatives
    # No logs unless --include-logs.
    assert not any(r.endswith(".log") for r in relatives)


def test_real_backup_writes_manifest_and_checksums(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"

    result = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=False
    )

    assert result["ok"] is True, result["errors"]
    backup_dir = Path(result["backup_dir"])
    assert backup_dir.exists()
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))

    # Manifest carries the advisory stamps required by the safety doctrine.
    assert manifest["advisory_only"] is True
    assert manifest["execution_gate"] == "LOCKED"
    assert manifest["broker_api_called"] is False
    assert manifest["ai_execution_count"] == 0
    assert manifest["can_execute"] is False

    # Every copied file has a sha256 + size, and the file actually exists.
    for entry in manifest["files_copied"]:
        dest = backup_dir / entry["relative"]
        assert dest.is_file(), f"missing copied file: {entry['relative']}"
        assert entry["sha256"], "manifest must include sha256"
        assert dest.stat().st_size == entry["size_bytes"]


def test_include_logs_flag_copies_log_files(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"

    result = backup_local_state.perform_backup(
        output_root=out_root, include_logs=True, dry_run=False
    )
    assert result["ok"] is True
    relatives = {f["relative"] for f in result["files_copied"]}
    assert "logs/live_signal_refresh.log" in relatives


def test_backup_never_copies_env(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    (repo / ".env").write_text("SECRET=hunter2\n", encoding="utf-8")
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"

    result = backup_local_state.perform_backup(
        output_root=out_root, include_logs=True, dry_run=False
    )
    assert result["ok"] is True
    backup_dir = Path(result["backup_dir"])
    # No file named .env anywhere under the backup tree.
    for p in backup_dir.rglob(".env"):
        pytest.fail(f"backup must NOT contain .env: {p}")
    # Manifest carries the explicit reminder.
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert ".env" in manifest["secrets_reminder"]


def test_dry_run_advisory_stamps_present(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"

    result = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=True
    )
    assert result["advisory_only"] is True
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    assert result["can_execute"] is False


# ---------------------------------------------------------------------------
# verify_backup
# ---------------------------------------------------------------------------


def test_verify_passes_on_clean_backup(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"
    res = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=False
    )
    assert res["ok"] is True

    report = verify_backup.verify_backup(Path(res["backup_dir"]))
    assert report["ok"] is True, report["errors"]
    assert report["manifest_present"] is True
    assert report["db_integrity"]["ok"] is True
    assert all(f.get("sha256_match") is True for f in report["files_checked"])


def test_verify_detects_checksum_mismatch(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"
    res = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=False
    )
    backup_dir = Path(res["backup_dir"])

    # Corrupt a copied paper-trade CSV after the manifest was written.
    target = backup_dir / "exports" / "paper_trade_2026Q2.csv"
    target.write_text("CORRUPTED\n", encoding="utf-8")

    report = verify_backup.verify_backup(backup_dir)
    assert report["ok"] is False
    assert any("checksum" in e or "size" in e for e in report["errors"])


def test_verify_handles_missing_manifest(tmp_path):
    report = verify_backup.verify_backup(tmp_path)
    assert report["ok"] is False
    assert report["manifest_present"] is False
    assert "manifest_missing" in report["errors"]


def test_verify_safety_stamps(tmp_path, monkeypatch):
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"
    res = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=False
    )
    report = verify_backup.verify_backup(Path(res["backup_dir"]))
    assert report["advisory_only"] is True
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["can_execute"] is False


def test_verify_does_not_touch_live_runtime_db(tmp_path, monkeypatch):
    """The live runtime DB must remain byte-identical after verify runs."""
    repo = _make_fake_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    out_root = tmp_path / "out"
    res = backup_local_state.perform_backup(
        output_root=out_root, include_logs=False, dry_run=False
    )

    live_db = repo / "runtime" / "mvp_local.db"
    before = live_db.read_bytes()
    verify_backup.verify_backup(Path(res["backup_dir"]))
    after = live_db.read_bytes()
    assert before == after, "verify_backup must not mutate the live runtime DB"
