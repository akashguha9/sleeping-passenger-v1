"""
Tests for scripts/backup_db.py and scripts/restore_db.py.

All tests operate on tmp_path SQLite files.  None touches runtime/mvp_local.db.

Safety invariants verified:
  * source DB is never mutated by backup
  * restore is dry-run by default
  * actual restore requires --yes/--force
  * restore creates a pre-restore backup before overwriting an existing target
  * restore refuses same source and target path
  * restore refuses non-SQLite files
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.backup_db import (  # type: ignore
    _is_sqlite_file,
    main as backup_main,
    perform_backup,
)
from scripts.restore_db import (  # type: ignore
    main as restore_main,
    perform_restore,
)


def _make_db(path: Path, rows: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE journal (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO journal (note) VALUES (?)",
            [(f"row-{i}",) for i in range(rows)],
        )
        conn.commit()


def _row_count(path: Path, table: str = "journal") -> int:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _source_hash(path: Path) -> bytes:
    return path.read_bytes()


# ---------------------------------------------------------------------------
# backup_db
# ---------------------------------------------------------------------------


def test_backup_creates_file_from_valid_db(tmp_path: Path) -> None:
    db = tmp_path / "src.db"
    _make_db(db, rows=5)
    backups = tmp_path / "backups"

    result = perform_backup(db_path=db, backup_dir=backups)

    assert result["ok"] is True, result
    backup_path = Path(result["backup_path"])
    assert backup_path.exists()
    assert backup_path.parent == backups.resolve() or backup_path.parent == backups
    assert _is_sqlite_file(backup_path)
    assert _row_count(backup_path) == 5


def test_backup_does_not_mutate_source(tmp_path: Path) -> None:
    db = tmp_path / "src.db"
    _make_db(db, rows=4)
    before = _source_hash(db)

    perform_backup(db_path=db, backup_dir=tmp_path / "bk")

    after = _source_hash(db)
    assert before == after


def test_backup_preserves_safety_stamps(tmp_path: Path) -> None:
    db = tmp_path / "src.db"
    _make_db(db)
    result = perform_backup(db_path=db, backup_dir=tmp_path / "bk")
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0


def test_backup_fails_when_source_missing(tmp_path: Path) -> None:
    db = tmp_path / "does_not_exist.db"
    result = perform_backup(db_path=db, backup_dir=tmp_path / "bk")
    assert result["ok"] is False
    assert "does not exist" in (result["error"] or "")
    assert result["backup_path"] is None


def test_backup_rejects_non_sqlite_file(tmp_path: Path) -> None:
    fake = tmp_path / "fake.db"
    fake.write_text("not a sqlite file")
    result = perform_backup(db_path=fake, backup_dir=tmp_path / "bk")
    assert result["ok"] is False
    assert "sqlite" in (result["error"] or "").lower()


def test_backup_filename_includes_label(tmp_path: Path) -> None:
    db = tmp_path / "src.db"
    _make_db(db)
    result = perform_backup(
        db_path=db, backup_dir=tmp_path / "bk", label="predemo"
    )
    assert result["ok"] is True
    assert Path(result["backup_path"]).name.endswith("-predemo.db")


def test_backup_cli_exits_zero_on_success(tmp_path: Path, capsys) -> None:
    db = tmp_path / "src.db"
    _make_db(db)
    rc = backup_main([
        "--db-path", str(db),
        "--backup-dir", str(tmp_path / "bk"),
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "RESULT: PASS" in out


def test_backup_cli_exits_nonzero_when_source_missing(tmp_path: Path, capsys) -> None:
    rc = backup_main([
        "--db-path", str(tmp_path / "missing.db"),
        "--backup-dir", str(tmp_path / "bk"),
    ])
    out = capsys.readouterr().out
    assert rc == 1
    assert "RESULT: FAIL" in out


def test_backup_cli_json_mode(tmp_path: Path, capsys) -> None:
    db = tmp_path / "src.db"
    _make_db(db)
    rc = backup_main([
        "--db-path", str(db),
        "--backup-dir", str(tmp_path / "bk"),
        "--json",
    ])
    import json
    payload = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert payload["ok"] is True
    assert payload["advisory_status"] == "ADVISORY_ONLY"


def test_backup_rejects_bad_label(tmp_path: Path, capsys) -> None:
    db = tmp_path / "src.db"
    _make_db(db)
    rc = backup_main([
        "--db-path", str(db),
        "--backup-dir", str(tmp_path / "bk"),
        "--label", "has spaces/slash",
    ])
    assert rc == 2
    assert "RESULT: FAIL" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# restore_db
# ---------------------------------------------------------------------------


def test_restore_dry_run_does_not_overwrite_target(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src, rows=2)
    target = tmp_path / "target.db"
    _make_db(target, rows=99)  # target has different content
    before = _source_hash(target)

    result = perform_restore(
        backup_file=src, db_path=target, dry_run=True, explicit_yes=False
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    after = _source_hash(target)
    assert before == after
    assert _row_count(target) == 99


def test_restore_requires_yes_for_actual_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src)
    target = tmp_path / "target.db"
    _make_db(target, rows=7)
    # Neither dry-run nor explicit yes => refuse.
    result = perform_restore(
        backup_file=src, db_path=target, dry_run=False, explicit_yes=False
    )
    assert result["ok"] is False
    assert "yes" in (result["error"] or "").lower() or "force" in (result["error"] or "").lower()
    assert _row_count(target) == 7  # unchanged


def test_restore_creates_pre_restore_backup_before_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src, rows=2)
    target = tmp_path / "target.db"
    _make_db(target, rows=11)
    bk_dir = tmp_path / "bk"

    result = perform_restore(
        backup_file=src,
        db_path=target,
        dry_run=False,
        explicit_yes=True,
        backup_dir=bk_dir,
    )

    assert result["ok"] is True
    pre = result["pre_restore_backup"]
    assert pre is not None and pre["ok"] is True
    pre_path = Path(pre["backup_path"])
    assert pre_path.exists()
    assert "-prerestore" in pre_path.name
    # pre-restore backup must contain the pre-overwrite content (11 rows).
    assert _row_count(pre_path) == 11
    # target now has the source's 2 rows.
    assert _row_count(target) == 2


def test_restore_refuses_same_source_and_target(tmp_path: Path) -> None:
    db = tmp_path / "only.db"
    _make_db(db)
    result = perform_restore(
        backup_file=db, db_path=db, dry_run=False, explicit_yes=True
    )
    assert result["ok"] is False
    assert "same" in (result["error"] or "").lower()


def test_restore_rejects_invalid_backup_file(tmp_path: Path) -> None:
    fake = tmp_path / "not_a_db.db"
    fake.write_text("totally not sqlite")
    target = tmp_path / "target.db"
    _make_db(target)
    result = perform_restore(
        backup_file=fake, db_path=target, dry_run=True, explicit_yes=False
    )
    assert result["ok"] is False
    assert "sqlite" in (result["error"] or "").lower()


def test_restore_to_missing_target_skips_pre_restore_backup(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src, rows=3)
    target = tmp_path / "fresh" / "new.db"  # does not exist yet
    result = perform_restore(
        backup_file=src,
        db_path=target,
        dry_run=False,
        explicit_yes=True,
    )
    assert result["ok"] is True
    assert result["pre_restore_backup"] is None
    assert target.exists()
    assert _row_count(target) == 3


def test_restore_safety_stamps_present(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src)
    result = perform_restore(
        backup_file=src,
        db_path=tmp_path / "target.db",
        dry_run=True,
        explicit_yes=False,
    )
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0


def test_restore_cli_dry_run_default(tmp_path: Path, capsys) -> None:
    src = tmp_path / "src.db"
    _make_db(src)
    target = tmp_path / "target.db"
    _make_db(target, rows=4)

    rc = restore_main([
        "--backup-file", str(src),
        "--db-path", str(target),
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry-run" in out.lower()
    assert _row_count(target) == 4  # untouched


def test_restore_cli_yes_applies(tmp_path: Path, capsys) -> None:
    src = tmp_path / "src.db"
    _make_db(src, rows=1)
    target = tmp_path / "target.db"
    _make_db(target, rows=8)

    rc = restore_main([
        "--backup-file", str(src),
        "--db-path", str(target),
        "--backup-dir", str(tmp_path / "bk"),
        "--yes",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "RESULT: PASS" in out
    assert _row_count(target) == 1
