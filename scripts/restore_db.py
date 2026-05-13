"""
Safe SQLite restore for the local advisory MVP.

Default mode is DRY RUN.  The current DB is never overwritten without
both --yes (or --force) AND a successful pre-restore backup.

Safety invariant (formal):
  RestoreAllowed =
      backup_file_exists
      AND backup_file_valid_sqlite
      AND target_path_resolved != backup_path_resolved
      AND (dry_run OR explicit_yes)
      AND pre_restore_backup_success   # when target exists

The script never:
  * deletes the backup source
  * deletes runtime/
  * overwrites the source DB silently
  * mutates the backup file
  * drops or alters any table inside either DB

Advisory invariants survive a restore because we copy bytes verbatim.

Usage:
    # safe dry-run (default)
    python scripts/restore_db.py --backup-file runtime/backups/mvp_local-20260101-120000.db

    # actually restore
    python scripts/restore_db.py --backup-file <path> --yes

    # restore to a non-default target
    python scripts/restore_db.py --backup-file <path> --db-path runtime/other.db --yes
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from typing import Any

try:
    from scripts.runtime_config import get_db_path  # type: ignore
except ModuleNotFoundError:
    REPO_ROOT = Path(__file__).resolve().parents[1]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.runtime_config import get_db_path  # type: ignore
    except ModuleNotFoundError:
        get_db_path = None  # type: ignore[assignment]

try:
    from scripts.backup_db import (  # type: ignore
        _is_sqlite_file,
        perform_backup as _perform_backup,
    )
except ModuleNotFoundError:
    from backup_db import _is_sqlite_file, perform_backup as _perform_backup  # type: ignore


def _default_db_path() -> Path:
    if get_db_path is not None:
        try:
            return Path(get_db_path())
        except Exception:
            pass
    return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _default_backup_dir(db_path: Path) -> Path:
    return db_path.parent / "backups"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def perform_restore(
    backup_file: Path,
    db_path: Path,
    dry_run: bool = True,
    explicit_yes: bool = False,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    """Perform a single restore.  Returns a structured result dict.

    Never raises; failures are reported via result["ok"] = False.
    On dry_run, ok=True means the restore *would* succeed.
    """
    result: dict[str, Any] = {
        "ok": False,
        "dry_run": bool(dry_run),
        "explicit_yes": bool(explicit_yes),
        "backup_file": str(backup_file),
        "db_path": str(db_path),
        "pre_restore_backup": None,
        "bytes_written": 0,
        "error": None,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }

    # ---- preflight ----
    backup_file = backup_file.expanduser()
    db_path = db_path.expanduser()
    try:
        backup_resolved = backup_file.resolve(strict=False)
        target_resolved = db_path.resolve(strict=False)
    except OSError as exc:
        result["error"] = f"could not resolve paths: {exc}"
        return result

    if backup_resolved == target_resolved:
        result["error"] = "refusing to restore: backup file and target db are the same path"
        return result

    if not backup_file.exists():
        result["error"] = f"backup file does not exist: {backup_file}"
        return result
    if not backup_file.is_file():
        result["error"] = f"backup file is not a regular file: {backup_file}"
        return result
    if not _is_sqlite_file(backup_file):
        result["error"] = "backup file is not a valid SQLite database"
        return result

    # Deeper validation: try to open it.  Read-only so we never mutate the backup.
    try:
        with sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True) as conn:
            cur = conn.execute("PRAGMA schema_version;")
            _ = cur.fetchone()
    except sqlite3.Error as exc:
        result["error"] = f"backup file failed sqlite open: {exc}"
        return result

    if not explicit_yes and not dry_run:
        # belt-and-braces; CLI also enforces this.
        result["error"] = "refusing to restore without --yes or --force (or use --dry-run)"
        return result

    # ---- dry-run path ----
    if dry_run:
        result["ok"] = True
        result["error"] = None
        return result

    # ---- real restore path ----
    target_dir = target_resolved.parent
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["error"] = f"could not create target dir: {exc}"
        return result

    pre_restore: dict[str, Any] | None = None
    if target_resolved.exists():
        # mandatory pre-restore backup
        bk_dir = (backup_dir or _default_backup_dir(target_resolved)).expanduser().resolve()
        pre_restore = _perform_backup(
            db_path=target_resolved,
            backup_dir=bk_dir,
            label="prerestore",
            timestamp=_timestamp(),
        )
        result["pre_restore_backup"] = pre_restore
        if not pre_restore.get("ok"):
            result["error"] = (
                f"pre-restore backup failed: {pre_restore.get('error', 'unknown')}"
            )
            return result

    # Copy backup over target.  copyfile is byte-exact; we do NOT use
    # sqlite3.backup() in this direction because we want bit-for-bit fidelity
    # to the backup file the operator pointed us at.
    try:
        copyfile(str(backup_file), str(target_resolved))
    except OSError as exc:
        result["error"] = f"copy failed: {exc}"
        return result

    if not _is_sqlite_file(target_resolved):
        result["error"] = "post-restore target is not a valid SQLite file (corrupt copy?)"
        return result

    try:
        result["bytes_written"] = target_resolved.stat().st_size
    except OSError:
        result["bytes_written"] = 0

    result["ok"] = True
    return result


def _emit_text(result: dict[str, Any]) -> None:
    print("Sleeping Passenger DB Restore")
    print(f"backup : {result['backup_file']}")
    print(f"target : {result['db_path']}")
    if result["dry_run"]:
        print("[INFO] dry-run mode (no changes made)")
    pre = result.get("pre_restore_backup")
    if pre:
        if pre.get("ok"):
            print(f"[PASS] pre-restore backup: {pre.get('backup_path')}")
        else:
            print(f"[FAIL] pre-restore backup error: {pre.get('error')}")
    if result["ok"]:
        if result["dry_run"]:
            print("[PASS] restore WOULD succeed (rerun with --yes to apply)")
        else:
            print(f"[PASS] restore applied ({result['bytes_written']} bytes)")
        print(f"[PASS] advisory_status={result['advisory_status']}")
        print(f"[PASS] execution_gate={result['execution_gate']}")
        print("RESULT: PASS")
    else:
        print(f"[FAIL] {result['error']}")
        print("RESULT: FAIL")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="restore_db.py",
        description=(
            "Safe SQLite restore.  Default mode is DRY RUN.  Pre-restore "
            "backup is mandatory when overwriting an existing DB."
        ),
    )
    parser.add_argument(
        "--backup-file",
        type=Path,
        required=True,
        help="Path to the backup .db file to restore from.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Override the target DB path (default: MVP_DB_PATH or runtime/mvp_local.db).",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Override the directory for the pre-restore backup (default: <target parent>/backups).",
    )
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate everything and report, but do not overwrite. (Default.)",
    )
    grp.add_argument(
        "--yes",
        action="store_true",
        help="Apply the restore (requires successful pre-restore backup if target exists).",
    )
    grp.add_argument(
        "--force",
        action="store_true",
        help="Alias for --yes.",
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

    explicit_yes = bool(args.yes or args.force)
    # default is dry-run; if neither --yes/--force nor explicit --dry-run, treat as dry-run.
    dry_run = (not explicit_yes) or bool(args.dry_run)

    db_path = (args.db_path or _default_db_path()).expanduser()
    result = perform_restore(
        backup_file=args.backup_file,
        db_path=db_path,
        dry_run=dry_run,
        explicit_yes=explicit_yes,
        backup_dir=args.backup_dir,
    )

    if args.json:
        print(json.dumps(result, sort_keys=True, default=str))
    else:
        _emit_text(result)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
