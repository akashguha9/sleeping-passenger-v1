"""
Local DB integrity + backup verification.

Purpose
-------
Before real-money self-testing, the local SQLite truth source must be
inspectable.  This script reads the DB *read-only*, runs SQLite's own
``PRAGMA integrity_check``, verifies that the journal-quality / process-
quality columns the operator depends on actually exist, and reports
whether at least one backup is present and openable.

Read-only by design.  Never mutates any row, table, pragma, or backup.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----
    python scripts/db_integrity_check.py
    python scripts/db_integrity_check.py --json
    python scripts/db_integrity_check.py --db-path runtime/mvp_local.db --json
    python scripts/db_integrity_check.py --backup-dir runtime/backups --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

REQUIRED_TABLES: tuple[str, ...] = ("manual_trades", "reconciliation_results")

REQUIRED_MANUAL_TRADES_COLUMNS: tuple[str, ...] = (
    "invalidation_level",
    "expected_horizon",
    "risk_reason",
    "entry_reason",
    "exit_plan",
    "confidence_before",
    "emotional_state",
    "mistake_tags",
    "lesson",
)

REQUIRED_RECON_COLUMNS: tuple[str, ...] = (
    "outcome_quality",
    "process_error",
    "process_error_notes",
    "mistake_tags",
    "lesson",
)


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _default_backup_dir(db_path: Path) -> Path:
    return db_path.parent / "backups"


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {r[1] for r in rows}


def _read_pragma(conn: sqlite3.Connection, name: str) -> Any:
    try:
        row = conn.execute(f"PRAGMA {name}").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _newest_backup(backup_dir: Path) -> Path | None:
    if not backup_dir.exists() or not backup_dir.is_dir():
        return None
    candidates = []
    for p in backup_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
            candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _backup_age_hours(path: Path, now: _dt.datetime) -> float | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    delta = now - _dt.datetime.fromtimestamp(mtime, tz=_dt.timezone.utc)
    return round(delta.total_seconds() / 3600.0, 4)


def _is_openable_sqlite(path: Path) -> bool:
    """Return True if ``path`` opens cleanly with sqlite3 in read-only mode."""
    if not path.exists():
        return False
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return False
    try:
        try:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.Error:
            return False
        return True
    finally:
        conn.close()


def _check(
    results: list[dict[str, Any]],
    failed: list[str],
    warnings: list[str],
    *,
    name: str,
    status: str,
    detail: str = "",
) -> None:
    """Record a check result. status ∈ {PASS, FAIL, WARN, INFO}."""
    results.append({"name": name, "status": status, "detail": detail})
    if status == "FAIL":
        failed.append(name)
    elif status == "WARN":
        warnings.append(name)


def run_integrity_check(
    db_path: Path | None = None,
    *,
    backup_dir: Path | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Run the full read-only integrity check.

    Parameters
    ----------
    db_path : Path | None
        DB to inspect.  Defaults to persistence.DB_PATH.
    backup_dir : Path | None
        Directory of *.db backups to inspect.  Defaults to <db_path parent>/backups.
    now : datetime | None
        Override for deterministic age math in tests.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    path = Path(db_path) if db_path else _default_db_path()
    bdir = Path(backup_dir) if backup_dir else _default_backup_dir(path)

    check_results: list[dict[str, Any]] = []
    failed_checks: list[str] = []
    warnings: list[str] = []

    payload: dict[str, Any] = {
        "report": "db_integrity_check",
        "db_path": str(path),
        "backup_dir": str(bdir),
        "ok": False,
        "check_results": check_results,
        "failed_checks": failed_checks,
        "warnings": warnings,
        "operator_action": "",
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    payload.update(_SAFETY_STAMPS)

    # 1. DB exists.
    if not path.exists():
        _check(check_results, failed_checks, warnings,
               name="db_exists", status="FAIL",
               detail=f"missing: {path}")
        payload["operator_action"] = (
            "Run scripts/persistence.init_schema() or open the API once "
            "to create the DB before re-running this check."
        )
        return payload
    _check(check_results, failed_checks, warnings,
           name="db_exists", status="PASS", detail=str(path))

    conn = _readonly_connect(path)
    if conn is None:
        _check(check_results, failed_checks, warnings,
               name="db_openable", status="FAIL",
               detail="could not open DB read-only")
        payload["operator_action"] = (
            "DB file present but cannot be opened. Verify file is not "
            "corrupted or locked by another process."
        )
        return payload
    _check(check_results, failed_checks, warnings,
           name="db_openable", status="PASS")

    try:
        # 2. integrity_check.
        ic = _read_pragma(conn, "integrity_check")
        if ic == "ok":
            _check(check_results, failed_checks, warnings,
                   name="integrity_check", status="PASS", detail="ok")
        else:
            _check(check_results, failed_checks, warnings,
                   name="integrity_check", status="FAIL", detail=str(ic))

        # 3. Required tables.
        for table in REQUIRED_TABLES:
            if _table_exists(conn, table):
                _check(check_results, failed_checks, warnings,
                       name=f"table:{table}", status="PASS")
            else:
                _check(check_results, failed_checks, warnings,
                       name=f"table:{table}", status="FAIL",
                       detail="missing")

        # 4. Required columns on manual_trades.
        if _table_exists(conn, "manual_trades"):
            cols = _columns(conn, "manual_trades")
            missing = [c for c in REQUIRED_MANUAL_TRADES_COLUMNS if c not in cols]
            if missing:
                _check(check_results, failed_checks, warnings,
                       name="manual_trades_journal_columns",
                       status="FAIL", detail=",".join(missing))
            else:
                _check(check_results, failed_checks, warnings,
                       name="manual_trades_journal_columns", status="PASS")

        # 5. Required columns on reconciliation_results.
        if _table_exists(conn, "reconciliation_results"):
            cols = _columns(conn, "reconciliation_results")
            missing = [c for c in REQUIRED_RECON_COLUMNS if c not in cols]
            if missing:
                _check(check_results, failed_checks, warnings,
                       name="reconciliation_results_columns",
                       status="FAIL", detail=",".join(missing))
            else:
                _check(check_results, failed_checks, warnings,
                       name="reconciliation_results_columns", status="PASS")

        # 6. Journal mode + busy timeout (informational).
        jm = _read_pragma(conn, "journal_mode")
        _check(check_results, failed_checks, warnings,
               name="journal_mode", status="INFO", detail=str(jm))
        bt = _read_pragma(conn, "busy_timeout")
        _check(check_results, failed_checks, warnings,
               name="busy_timeout_ms", status="INFO", detail=str(bt))

        # 7. Foreign keys (informational only).
        fk = _read_pragma(conn, "foreign_keys")
        _check(check_results, failed_checks, warnings,
               name="foreign_keys", status="INFO", detail=str(fk))
    finally:
        conn.close()

    # 8. Backup directory.
    if bdir.exists() and bdir.is_dir():
        _check(check_results, failed_checks, warnings,
               name="backup_dir_exists", status="PASS", detail=str(bdir))
        newest = _newest_backup(bdir)
        if newest is None:
            _check(check_results, failed_checks, warnings,
                   name="backup_present", status="WARN",
                   detail="no .db files in backup dir")
        else:
            age = _backup_age_hours(newest, now)
            _check(check_results, failed_checks, warnings,
                   name="backup_present", status="PASS",
                   detail=f"{newest.name}, age={age}h")
            if _is_openable_sqlite(newest):
                _check(check_results, failed_checks, warnings,
                       name="latest_backup_openable", status="PASS")
            else:
                _check(check_results, failed_checks, warnings,
                       name="latest_backup_openable", status="FAIL",
                       detail=f"cannot open {newest.name} as sqlite")
            if age is not None and age > 7 * 24:
                _check(check_results, failed_checks, warnings,
                       name="backup_recency", status="WARN",
                       detail=f"newest backup older than 7 days: {age}h")
            else:
                _check(check_results, failed_checks, warnings,
                       name="backup_recency", status="PASS")
    else:
        _check(check_results, failed_checks, warnings,
               name="backup_dir_exists", status="WARN",
               detail=f"missing: {bdir}")

    payload["ok"] = len(failed_checks) == 0
    if not payload["ok"]:
        payload["operator_action"] = (
            "Fix the failing checks before logging real-money manual trades. "
            "Re-run db_integrity_check after applying schema migrations or "
            "restoring a healthy backup."
        )
    elif warnings:
        payload["operator_action"] = (
            "DB integrity is OK but warnings exist (see warnings list). "
            "Consider running scripts/backup_db.py to refresh the backup "
            "before logging real-money manual trades."
        )
    else:
        payload["operator_action"] = (
            "DB integrity OK and backup verified.  Safe for local "
            "self-test logging."
        )
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("DB Integrity Check")
    lines.append(f"DB:     {payload['db_path']}")
    lines.append(f"Backup: {payload['backup_dir']}")
    for c in payload["check_results"]:
        line = f"[{c['status']}] {c['name']}"
        if c["detail"]:
            line += f" {c['detail']}"
        lines.append(line)
    lines.append(f"RESULT: {'PASS' if payload['ok'] else 'FAIL'}")
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="db_integrity_check.py",
        description=(
            "Read-only local DB integrity + backup verification. Never "
            "writes the DB."
        ),
    )
    p.add_argument("--db-path", type=str, default=None,
                   help="Path to runtime/mvp_local.db (default: persistence).")
    p.add_argument("--backup-dir", type=str, default=None,
                   help="Backup directory (default: <db parent>/backups).")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    payload = run_integrity_check(db_path, backup_dir=backup_dir)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload["ok"] else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "REQUIRED_TABLES",
    "REQUIRED_MANUAL_TRADES_COLUMNS",
    "REQUIRED_RECON_COLUMNS",
    "run_integrity_check",
]


if __name__ == "__main__":
    raise SystemExit(main())
