"""Lightweight, non-destructive schema versioning (Kanté Sprint 2 — Task 7).

SQLite remains the canonical store; :mod:`scripts.persistence` already applies
its tables and additive column migrations with ``CREATE TABLE IF NOT EXISTS`` /
guarded ``ALTER ... ADD COLUMN``.  This module adds the missing piece — a
recorded **schema version** — so the operator can detect when a runtime DB was
created by older code than the running checkout.

Design (deliberately tiny — no migration framework)
---------------------------------------------------
* ``schema_version(version, applied_at, code_version, advisory stamps)``.
* :func:`get_schema_version` is **read-only** — it never creates the table.
* :func:`init_schema_version` creates the table (``IF NOT EXISTS``) and inserts
  the current version only if absent.  Idempotent; never drops/alters data.
* :func:`check_version` compares runtime vs code version without writing.

No destructive DDL.  No broker calls.  No execution.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

# The schema version the *current code* expects.  Bump when a structural
# (non-additive) change ships.  Sprint 2 baseline is 1.
CODE_SCHEMA_VERSION = 1

_TABLE = "schema_version"


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:  # pragma: no cover - defensive
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def schema_version_table_exists(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
        ).fetchone()
        return row is not None
    except sqlite3.Error:  # pragma: no cover - defensive
        return False
    finally:
        conn.close()


def get_schema_version(db_path: Path | None = None) -> int | None:
    """Return the recorded schema version, or ``None``.  **Read-only.**

    Never creates the table — a fresh DB without a version table returns None.
    """
    path = Path(db_path) if db_path is not None else _default_db_path()
    if not schema_version_table_exists(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(path))
        except sqlite3.Error:
            return None
    try:
        row = conn.execute(
            f"SELECT MAX(version) FROM {_TABLE}"
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])
    except sqlite3.Error:  # pragma: no cover - defensive
        return None
    finally:
        conn.close()


def init_schema_version(
    db_path: Path | None = None,
    *,
    version: int = CODE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Create the version table (IF NOT EXISTS) and record ``version`` if absent.

    Idempotent and non-destructive: only ``CREATE TABLE IF NOT EXISTS`` and an
    ``INSERT`` of the version row when none exists.  Never drops/alters data.
    """
    path = Path(db_path) if db_path is not None else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    created = False
    inserted = False
    try:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            " version INTEGER NOT NULL,"
            " applied_at TEXT NOT NULL,"
            " code_version INTEGER NOT NULL,"
            " advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',"
            " execution_gate TEXT NOT NULL DEFAULT 'LOCKED'"
            ")"
        )
        created = True
        existing = conn.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0]
        if not existing:
            conn.execute(
                f"INSERT INTO {_TABLE} (version, applied_at, code_version,"
                " advisory_status, execution_gate) VALUES (?, ?, ?, ?, ?)",
                (int(version), _utc_now(), int(CODE_SCHEMA_VERSION),
                 _contract.ADVISORY_STATUS, _contract.EXECUTION_GATE_LOCKED),
            )
            inserted = True
        conn.commit()
    finally:
        conn.close()
    return {
        "operation": "init_schema_version",
        "db_path": str(path),
        "table_ensured": created,
        "version_inserted": inserted,
        "version": get_schema_version(path),
        "code_schema_version": CODE_SCHEMA_VERSION,
        **_contract.advisory_safety_stamps(),
    }


def check_version(db_path: Path | None = None) -> dict[str, Any]:
    """Compare runtime vs code schema version.  Read-only."""
    path = Path(db_path) if db_path is not None else _default_db_path()
    runtime = get_schema_version(path)
    return {
        "report": "schema_version_check",
        "db_path": str(path),
        "db_exists": path.exists(),
        "runtime_version": runtime,
        "code_version": CODE_SCHEMA_VERSION,
        "version_table_present": schema_version_table_exists(path),
        "matches": runtime == CODE_SCHEMA_VERSION,
        "behind": runtime is not None and runtime < CODE_SCHEMA_VERSION,
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="schema_migrations.py",
        description=(
            "Lightweight non-destructive schema versioning. Read-only unless "
            "--init-schema-version.  Never a broker call."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--init-schema-version", action="store_true",
                   help="Create the version table and record the current version.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db = Path(args.db_path) if args.db_path else None
    if args.init_schema_version:
        report = init_schema_version(db)
    else:
        report = check_version(db)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(json.dumps(report, indent=2, default=str))
    return 0


__all__ = [
    "CODE_SCHEMA_VERSION",
    "schema_version_table_exists",
    "get_schema_version",
    "init_schema_version",
    "check_version",
]


if __name__ == "__main__":
    raise SystemExit(main())
