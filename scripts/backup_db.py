"""
Safe SQLite backup for the local advisory MVP.

Reads:
    runtime/mvp_local.db   (or MVP_DB_PATH / --db-path override)

Writes:
    runtime/backups/mvp_local-YYYYMMDD-HHMMSS[-label].db

Properties:
  * stdlib only (sqlite3 + pathlib + argparse + datetime).
  * Uses the sqlite3 connection.backup() API so the source DB is never
    touched and a hot copy is safe even if writers are active.
  * Never deletes or overwrites the source DB.
  * Never prints secrets.  No env values are echoed.
  * Exits 0 on PASS, non-zero on FAIL.
  * Preserves all advisory safety invariants -- this script does not
    mutate any DB row, table, or pragma, so:
        execution_gate     = LOCKED
        ai_execution_count = 0
        broker_api_called  = False
        advisory_status    = ADVISORY_ONLY
    remain intact across backup.

Usage:
    python scripts/backup_db.py
    python scripts/backup_db.py --label predemo
    python scripts/backup_db.py --db-path /tmp/foo.db --backup-dir /tmp/bk
    python scripts/backup_db.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_config import get_db_path  # type: ignore
except ModuleNotFoundError:  # running as a loose script
    REPO_ROOT = Path(__file__).resolve().parents[1]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.runtime_config import get_db_path  # type: ignore
    except ModuleNotFoundError:
        get_db_path = None  # type: ignore[assignment]


_DEFAULT_BACKUP_DIRNAME = "backups"
_LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


def _default_db_path() -> Path:
    if get_db_path is not None:
        try:
            return Path(get_db_path())
        except Exception:
            pass
    return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _default_backup_dir(db_path: Path) -> Path:
    # Default: <db_path parent>/backups  (so runtime/mvp_local.db -> runtime/backups)
    return db_path.parent / _DEFAULT_BACKUP_DIRNAME


def _sanitize_label(label: str | None) -> str | None:
    if label is None:
        return None
    label = label.strip()
    if not label:
        return None
    if not _LABEL_RE.match(label):
        raise ValueError(
            "label must be 1-32 chars of [A-Za-z0-9._-]; got something else"
        )
    return label


def _is_sqlite_file(path: Path) -> bool:
    """Cheap header check.  Real validation happens when sqlite3 opens it."""
    try:
        with path.open("rb") as fh:
            header = fh.read(16)
        return header.startswith(b"SQLite format 3")
    except OSError:
        return False


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _build_backup_filename(db_path: Path, label: str | None, stamp: str) -> str:
    stem = db_path.stem  # e.g. "mvp_local"
    if label:
        return f"{stem}-{stamp}-{label}.db"
    return f"{stem}-{stamp}.db"


def perform_backup(
    db_path: Path,
    backup_dir: Path,
    label: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Perform a single backup.  Returns a structured result dict.

    Never raises; failures are reported via result["ok"] = False.
    """
    result: dict[str, Any] = {
        "ok": False,
        "db_path": str(db_path),
        "backup_dir": str(backup_dir),
        "backup_path": None,
        "bytes": 0,
        "label": label,
        "error": None,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }

    if not db_path.exists():
        result["error"] = f"source DB does not exist: {db_path}"
        return result
    if not db_path.is_file():
        result["error"] = f"source DB is not a regular file: {db_path}"
        return result
    if not _is_sqlite_file(db_path):
        result["error"] = "source file does not look like a SQLite database"
        return result

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["error"] = f"could not create backup dir: {exc}"
        return result

    stamp = timestamp or _timestamp()
    backup_name = _build_backup_filename(db_path, label, stamp)
    backup_path = backup_dir / backup_name

    if backup_path.exists():
        result["error"] = f"backup target already exists: {backup_path}"
        return result

    src: sqlite3.Connection | None = None
    dst: sqlite3.Connection | None = None
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(str(backup_path))
        src.backup(dst)
        dst.close()
        dst = None
        src.close()
        src = None
    except sqlite3.Error as exc:
        result["error"] = f"sqlite backup failed: {exc}"
        try:
            if backup_path.exists():
                backup_path.unlink()
        except OSError:
            pass
        return result
    finally:
        for conn in (dst, src):
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    if not _is_sqlite_file(backup_path):
        result["error"] = "produced backup is not a valid SQLite file"
        try:
            backup_path.unlink()
        except OSError:
            pass
        return result

    try:
        result["bytes"] = backup_path.stat().st_size
    except OSError:
        result["bytes"] = 0

    result["backup_path"] = str(backup_path)
    result["ok"] = True
    return result


def _emit_text(result: dict[str, Any]) -> None:
    print(f"Sleeping Passenger DB Backup")
    print(f"source : {result['db_path']}")
    print(f"target : {result['backup_path'] or '(none)'}")
    if result["label"]:
        print(f"label  : {result['label']}")
    if result["ok"]:
        print(f"[PASS] backup written ({result['bytes']} bytes)")
        print(f"[PASS] advisory_status={result['advisory_status']}")
        print(f"[PASS] execution_gate={result['execution_gate']}")
        print(f"RESULT: PASS")
    else:
        print(f"[FAIL] {result['error']}")
        print(f"RESULT: FAIL")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup_db.py",
        description=(
            "Safe SQLite backup for the local advisory MVP. "
            "Source DB is never mutated."
        ),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Override the source DB path (default: MVP_DB_PATH or runtime/mvp_local.db).",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Override the backup directory (default: <db parent>/backups).",
    )
    parser.add_argument(
        "--label",
        type=str,
        default=None,
        help="Optional label appended to the filename (e.g. predemo, prerestore).",
    )
    parser.add_argument(
        "--operator-role",
        default=None,
        help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env). "
             "Creating a backup requires OPERATOR.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout instead of human text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Creating a backup file is an OPERATOR-level write-like action.  Fail
    # closed for unauthorized roles (the source DB is never read until cleared).
    try:
        try:
            from scripts.operator_audit_log import enforce as _enforce
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from operator_audit_log import enforce as _enforce  # type: ignore[no-redef]
        _enforce("backup_db", role=args.operator_role,
                 resource=str(args.db_path or "runtime/mvp_local.db"))
    except PermissionError as exc:
        msg = str(exc)
        if args.json:
            print(json.dumps({"ok": False, "error": msg, "denied": True}))
        else:
            print(f"[DENY] {msg}")
            print("RESULT: FAIL")
        return 2

    try:
        label = _sanitize_label(args.label)
    except ValueError as exc:
        msg = str(exc)
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"[FAIL] {msg}")
            print("RESULT: FAIL")
        return 2

    db_path = (args.db_path or _default_db_path()).expanduser().resolve()
    backup_dir = (args.backup_dir or _default_backup_dir(db_path)).expanduser().resolve()

    result = perform_backup(db_path=db_path, backup_dir=backup_dir, label=label)

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        _emit_text(result)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
