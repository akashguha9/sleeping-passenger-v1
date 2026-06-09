"""H4 regression: scheduled backups, retention, WAL verification, restore drill.

Sprint 1 residuals: backups were operator-initiated only, WAL was set but
never verified, and no restore was ever exercised ("an unverified backup
is not a backup").
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import persistence
from scripts.backup_db import perform_backup, perform_restore
from scripts.backup_scheduler import (
    SCHEDULED_LABEL,
    prune_backups,
    run_scheduled_backup,
    scheduled_backups_enabled,
)


def _make_db(path: Path, rows: int = 3) -> None:
    persistence.init_schema(path)
    for i in range(rows):
        persistence.insert_manual_trade(
            f"MT_B{i}", f"EVT_B{i}", "AAPL", "BUY", 1, 100 + i,
            "2026-01-01T00:00:00Z", "t", "", "human", db_path=path,
        )


def _table_checksum(path: Path, table: str) -> tuple[int, str]:
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY 1"
        ).fetchall()
    finally:
        conn.close()
    digest = hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
    return len(rows), digest


# ---------------------------------------------------------------------------
# Scheduled backup + retention
# ---------------------------------------------------------------------------


def test_scheduler_disabled_under_pytest_by_default():
    # PYTEST_CURRENT_TEST is set inside the suite — default must be off so
    # TestClient startups never write backups.
    assert scheduled_backups_enabled() is False


def test_run_scheduled_backup_creates_file_and_prunes(tmp_path):
    db = tmp_path / "sched.db"
    _make_db(db)
    result = run_scheduled_backup(db, tmp_path / "backups")
    assert result["ok"] is True
    assert Path(result["backup_path"]).exists()
    assert SCHEDULED_LABEL in result["backup_path"]
    assert result["retention"]["deleted"] == []
    # advisory stamps on the result
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False


def _touch_backup(dirpath: Path, ts: datetime) -> Path:
    stamp = ts.strftime("%Y%m%d-%H%M%S")
    f = dirpath / f"mvp_local-{stamp}-{SCHEDULED_LABEL}.db"
    f.write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)
    return f


def test_retention_keeps_7_daily_plus_4_weekly(tmp_path):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    now = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
    # 45 consecutive daily backups (enough span for 4 weekly slots
    # beyond the 7-day daily window).
    files = [_touch_backup(bdir, now - timedelta(days=i)) for i in range(45)]
    out = prune_backups(bdir)
    kept = set(out["kept"])
    # newest 7 days kept...
    for i in range(7):
        assert files[i].name in kept, f"day -{i} should be kept"
    # ...plus 4 weekly representatives beyond the daily window.
    assert len(kept) == 7 + 4
    # deleted files are gone from disk; kept remain.
    for f in files:
        assert f.exists() == (f.name in kept)


def test_retention_never_touches_non_scheduled_backups(tmp_path):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    precious = bdir / "mvp_local.pre-f3-money.20260101T000000Z.db"
    precious.write_bytes(b"SQLite format 3\x00")
    manual = bdir / "mvp_local-20260101-000000-prerepair.db"
    manual.write_bytes(b"SQLite format 3\x00")
    now = datetime(2026, 6, 9, tzinfo=timezone.utc)
    for i in range(20):
        _touch_backup(bdir, now - timedelta(days=i))
    prune_backups(bdir)
    assert precious.exists()
    assert manual.exists()


# ---------------------------------------------------------------------------
# Restore drill — the score mover
# ---------------------------------------------------------------------------


def test_restore_drill_roundtrip_parity(tmp_path):
    db = tmp_path / "live.db"
    _make_db(db, rows=5)
    pre_count, pre_checksum = _table_checksum(db, "manual_trades")

    # 1. take a backup
    backup = perform_backup(db, tmp_path / "backups", label="drill")
    assert backup["ok"] is True

    # 2. mutate the live DB after the backup
    persistence.insert_manual_trade(
        "MT_AFTER", "EVT_AFTER", "TSLA", "SELL", 1, 999,
        "2026-01-02T00:00:00Z", "post-backup mutation", "", "human",
        db_path=db,
    )
    mut_count, mut_checksum = _table_checksum(db, "manual_trades")
    assert mut_count == pre_count + 1
    assert mut_checksum != pre_checksum

    # 3. restore the backup to a separate path
    restored = tmp_path / "restored.db"
    result = perform_restore(Path(backup["backup_path"]), restored)
    assert result["ok"] is True, result["error"]
    assert result["integrity_check"] == "ok"

    # 4. parity with the PRE-mutation state
    r_count, r_checksum = _table_checksum(restored, "manual_trades")
    assert r_count == pre_count
    assert r_checksum == pre_checksum


def test_restore_refuses_to_overwrite_existing_target(tmp_path):
    db = tmp_path / "live.db"
    _make_db(db, rows=1)
    backup = perform_backup(db, tmp_path / "backups", label="drill2")
    target = tmp_path / "exists.db"
    target.write_bytes(b"do not clobber me")
    result = perform_restore(Path(backup["backup_path"]), target)
    assert result["ok"] is False
    assert "refusing to overwrite" in result["error"]
    assert target.read_bytes() == b"do not clobber me"


# ---------------------------------------------------------------------------
# WAL post-set verification
# ---------------------------------------------------------------------------


def test_wal_verified_on_healthy_filesystem(tmp_path):
    persistence._reset_wal_verify_failures()
    db = tmp_path / "wal.db"
    persistence.init_schema(db)
    conn = persistence._get_conn(db)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert str(mode).upper() == "WAL"
    assert persistence.wal_verify_failure_count() == 0


def test_wal_refusal_is_counted_and_logged(tmp_path, monkeypatch, caplog):
    import logging

    persistence._reset_wal_verify_failures()

    class _NoWalConn:
        """Accepts every pragma but reports journal_mode=delete."""

        def execute(self, sql, *a, **k):
            class _Cur:
                def fetchone(_self):
                    return ("delete",)

            if "journal_mode" in sql.lower():
                return _Cur()
            return _Cur()

    with caplog.at_level(logging.ERROR, logger="scripts.persistence"):
        persistence._apply_pragmas(_NoWalConn())
    assert persistence.wal_verify_failure_count() == 1
    assert any("journal_mode=WAL requested" in r.message for r in caplog.records)
    persistence._reset_wal_verify_failures()


def test_health_full_surfaces_wal_failures(monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    monkeypatch.setattr(persistence, "_WAL_VERIFY_FAILURES", 2)
    client = TestClient(srv.app, raise_server_exceptions=False)
    h = client.get("/health/full").json()
    assert h["wal_verification_failures"] == 2
    assert h["degraded"] is True


# ---------------------------------------------------------------------------
# Manual trigger endpoint
# ---------------------------------------------------------------------------


def test_admin_backup_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    db = tmp_path / "admin.db"
    _make_db(db, rows=2)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    client = TestClient(srv.app, raise_server_exceptions=False)
    r = client.post("/admin/backup")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert Path(body["backup_path"]).exists()
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False


def test_admin_backup_failure_is_stamped_500(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    monkeypatch.setattr(
        persistence, "DB_PATH", tmp_path / "missing.db", raising=True
    )
    client = TestClient(srv.app, raise_server_exceptions=False)
    r = client.post("/admin/backup")
    assert r.status_code == 500
    body = r.json()
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_api_called"] is False
