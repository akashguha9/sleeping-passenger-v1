#!/usr/bin/env python3
"""Wipe the local Manual Trade Log, Reconciliation, and Moltbook records.

These three surfaces are operator journals that live ONLY in your local,
git-ignored runtime database (``runtime/mvp_local.db``) plus append-only
JSONL fallback logs under ``logs/``. They are never committed, so this
script can only be run on the machine that holds the data — it deletes
nothing in git.

What it clears
--------------
* DB table ``manual_trades``           (the Manual Trade Log)
* DB table ``reconciliation_results``  (the Reconciliation queue history)
* DB table ``moltbook_entries``        (the Moltbook lessons journal)
* JSONL fallbacks under ``logs/``:
    - manual_trade_log.jsonl
    - trade_reconciliations.jsonl
    - manual_trade_cancellations.jsonl
    - moltbook_entries.jsonl

What it does NOT touch
----------------------
* ``signal_events`` (Live Signals / Signal Inbox feed) — left intact.
* Reflections, AI summaries, inbox state, source health, calibration.

Safety
------
* **Dry-run by default**: prints the row/line counts that WOULD be removed
  and exits without changing anything.  ``--apply`` is required to wipe.
* **Central operator permission guard** (Kanté Defensive Sprint):
  ``--apply`` routes through :mod:`scripts.operator_permission_guard` — a
  destructive table-clear is a ``REPAIR_WRITE`` (OPERATOR+) that fails closed
  unless the role floor is met, a recent dry-run receipt exists, the target DB
  path is a safe local/repo/temp path, and the advisory safety invariants are
  clean.  Every allow *and* deny is written to the operator audit log.
* **Allowlisted tables only**: the write boundary refuses to clear anything
  outside ``_ALLOWED_TABLES`` and refuses broad / ambiguous / external DB
  paths (delegated to the guard's ``classify_db_path``).
* Before wiping, a timestamped backup copy of the database is written next
  to it (``mvp_local.db.bak-YYYYMMDDTHHMMSSZ``) unless ``--no-backup``.
* This is record-keeping only. It never calls a broker and never changes
  ``ai_execution_count`` / ``broker_api_called`` — those stay 0 / false.

Usage
-----
    python scripts/reset_local_logs.py                # dry run (shows counts + writes receipt)
    $env:MVP_OPERATOR_ROLE="OPERATOR"
    python scripts/reset_local_logs.py --apply        # wipe for real (+backup)
    python scripts/reset_local_logs.py --apply --no-backup
    python scripts/reset_local_logs.py --apply --keep-jsonl   # DB only
    python scripts/reset_local_logs.py --db runtime/mvp_local.db --apply

Exit codes
----------
    0  dry-run completed, or --apply succeeded.
    2  --apply denied by the operator permission guard (role/receipt/path/
       safety-invariant), or an unsafe target was refused.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Resolve the canonical DB path and JSONL log locations from the app's own
# modules so this stays in lock-step with the rest of the codebase.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import persistence  # noqa: E402
import signal_inbox_api  # noqa: E402
import moltbook_api  # noqa: E402

try:
    from scripts import operator_permission_guard as _guard  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]  # noqa: E402

# Operation identity for the central permission guard.  Clearing the local
# operator journals is a destructive but record-keeping-only REPAIR_WRITE
# (OPERATOR+); it never deletes from git, never alters schema, and never
# issues an execution action.
OPERATION_NAME = "reset_local_logs"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE

# Tables to purge, in an order that is safe regardless of any future foreign
# keys (children before parents).  This is the *allowlist*: the guarded write
# boundary refuses to clear any table not named here.  ``signal_events`` (Live
# Signals) is deliberately absent — it is never wiped by this script.
_ALLOWED_TABLES: tuple[str, ...] = (
    "reconciliation_results",
    "moltbook_entries",
    "manual_trades",
)
# Backwards-compatible alias (older callers / docs referenced ``_TABLES``).
_TABLES = _ALLOWED_TABLES

_JSONL_LOGS: tuple[Path, ...] = (
    signal_inbox_api.MANUAL_TRADE_LOG,
    signal_inbox_api.RECONCILIATIONS_LOG,
    signal_inbox_api.MANUAL_TRADE_CANCELLATIONS_LOG,
    moltbook_api.MOLTBOOK_LOG,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not row or not row[0]:
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def scan(db_path: Path) -> dict[str, Any]:
    """Read-only: count the rows / JSONL lines that an --apply WOULD remove.

    No writes, no broker calls.  Safe for any role to run.
    """
    if not db_path.exists():
        db_counts: dict[str, int] = {t: 0 for t in _ALLOWED_TABLES}
    else:
        conn = sqlite3.connect(str(db_path))
        try:
            db_counts = {t: _table_count(conn, t) for t in _ALLOWED_TABLES}
        finally:
            conn.close()
    jsonl_counts = {p: _jsonl_line_count(p) for p in _JSONL_LOGS}
    return {
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_counts": db_counts,
        "jsonl_counts": jsonl_counts,
        "total_rows": sum(db_counts.values()),
        "total_lines": sum(jsonl_counts.values()),
    }


def _print_scan(scan_result: dict[str, Any], *, keep_jsonl: bool) -> None:
    db_counts = scan_result["db_counts"]
    jsonl_counts = scan_result["jsonl_counts"]
    print("\nDatabase tables:")
    for table in _ALLOWED_TABLES:
        print(f"  {table:<22} {db_counts[table]:>6} row(s)")
    print("\nJSONL fallback logs:")
    for path in _JSONL_LOGS:
        exists = "exists" if path.exists() else "absent"
        print(f"  {path.name:<34} {jsonl_counts[path]:>6} line(s)  [{exists}]")


@_guard.guarded_mutation(
    operation_name=OPERATION_NAME,
    operation_class=OPERATION_CLASS,
    expected_role_floor=_guard.OperatorRole.OPERATOR,
    require_dry_run=True,
)
def apply_reset(
    db_path: Path,
    *,
    keep_jsonl: bool = False,
    no_backup: bool = False,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Wipe the allowlisted local journal tables + JSONL fallbacks.

    Function-level guard (Kanté Task 4 / collapsed Task B): the
    :func:`operator_permission_guard.guarded_mutation` decorator enforces the
    write boundary, so a caller importing this function directly — bypassing
    the CLI — still cannot run it without a guard-validated, allowed, OPERATOR+
    ``REPAIR_WRITE`` :class:`PermissionDecision`.  The decorator raises
    ``PermissionError`` before any delete if the decision is missing, denied,
    of the wrong operation class, sub-floor, dry-run-less, or has dirty safety
    stamps.

    Two further defence-in-depth checks run inside the boundary: the target DB
    path must be a safe local/repo/temp path, and every table cleared must be
    on ``_ALLOWED_TABLES``.  Returns a structured summary; ``rows_deleted`` is
    0 whenever the guard or these checks would otherwise have to mutate
    something out of contract.
    """
    # Defence in depth — refuse broad / ambiguous / external DB paths even if a
    # decision was somehow minted for one.
    if not _guard.safe_db_path_allowed(str(db_path)):
        raise PermissionError(
            f"reset_local_logs: refusing unsafe / broad DB path: {db_path!r}"
        )

    summary: dict[str, Any] = {
        "applied": True,
        "db_path": str(db_path),
        "rows_deleted": 0,
        "jsonl_files_removed": 0,
        "backup_path": "",
        "tables_cleared": [],
    }

    if db_path.exists() and not no_backup:
        backup = db_path.with_name(f"{db_path.name}.bak-{_utc_stamp()}")
        shutil.copy2(db_path, backup)
        summary["backup_path"] = str(backup)

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            for table in _ALLOWED_TABLES:
                # Allowlist invariant — never clear a table outside the set.
                if table not in _ALLOWED_TABLES:  # pragma: no cover - defensive
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if not exists:
                    continue
                cur = conn.execute(f"DELETE FROM {table}")
                deleted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                summary["rows_deleted"] += deleted
                summary["tables_cleared"].append(table)
            conn.commit()
            # Reclaim space and reset autoincrement counters for a clean slate.
            conn.execute("VACUUM")
        finally:
            conn.close()

    if not keep_jsonl:
        for path in _JSONL_LOGS:
            if path.exists():
                path.unlink()
                summary["jsonl_files_removed"] += 1

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Wipe local Manual Trade Log, Reconciliation, and Moltbook "
            "records (DB + JSONL). Dry-run unless --apply is given. --apply "
            "requires MVP_OPERATOR_ROLE=OPERATOR or ADMIN and a recent dry-run "
            "receipt (it routes through the central operator permission guard)."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag the script only reports "
             "counts. Requires OPERATOR/ADMIN + a recent dry-run receipt.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=persistence.DB_PATH,
        help=f"SQLite DB path (default: {persistence.DB_PATH}).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the timestamped DB backup taken before wiping.",
    )
    parser.add_argument(
        "--keep-jsonl",
        action="store_true",
        help="Only purge the DB tables; leave the JSONL fallback logs alone.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (default behaviour); writes a permission "
             "dry-run receipt so a subsequent --apply can proceed. Read-only.",
    )
    parser.add_argument(
        "--operator-role",
        default=None,
        help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env, else "
             "VIEWER).  --apply requires OPERATOR or ADMIN.",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[reset_local_logs] mode={mode} db={db_path}")

    if not db_path.exists():
        print(
            f"[reset_local_logs] DB does not exist yet: {db_path}\n"
            "  Nothing to wipe in the database (it is created on first use)."
        )

    scan_result = scan(db_path)
    _print_scan(scan_result, keep_jsonl=args.keep_jsonl)

    total_rows = scan_result["total_rows"]
    total_lines = scan_result["total_lines"]

    if not args.apply:
        # Dry-run is read-only and open to any role.  Record a receipt so a
        # later --apply (by an authorized role) can prove a dry-run happened.
        target_count = total_rows + (0 if args.keep_jsonl else total_lines)
        try:
            receipt = _guard.write_dry_run_receipt(
                OPERATION_NAME, target_count=target_count, db_path=str(db_path))
            print(f"\n[reset_local_logs] dry-run receipt written: {receipt.name}")
        except Exception:  # pragma: no cover - receipt is best-effort
            pass
        print(
            "[reset_local_logs] DRY-RUN — nothing was deleted.\n"
            f"  Would delete {total_rows} DB row(s)"
            + ("" if args.keep_jsonl else f" and {total_lines} JSONL line(s)")
            + ".\n  Re-run with --apply (as OPERATOR/ADMIN) to perform the wipe."
        )
        print(
            "[reset_local_logs] [safety] broker_api_called=False "
            "ai_execution_count=0 execution_gate=LOCKED record_keeping_only=True"
        )
        return 0

    # --apply path: central permission guard (fails closed; audits allow/deny).
    # The per-CLI request/role/receipt boilerplate is collapsed into
    # build_apply_decision (Kanté Task B).
    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(db_path),
            operator_role=args.operator_role)
    except PermissionError as exc:
        print(f"[reset_local_logs] [DENY] {exc}", file=sys.stderr)
        return 2

    try:
        summary = apply_reset(
            db_path,
            keep_jsonl=args.keep_jsonl,
            no_backup=args.no_backup,
            permission_decision=decision,
        )
    except PermissionError as exc:  # defence-in-depth boundary refusal
        print(f"[reset_local_logs] [DENY] {exc}", file=sys.stderr)
        return 2

    if summary["backup_path"]:
        print(f"\n[reset_local_logs] backup written: {summary['backup_path']}")
    print(f"[reset_local_logs] deleted {summary['rows_deleted']} DB row(s).")
    if args.keep_jsonl:
        print("[reset_local_logs] --keep-jsonl set; JSONL logs left untouched.")
    else:
        print(f"[reset_local_logs] removed {summary['jsonl_files_removed']} "
              "JSONL log file(s).")
    print(
        "\n[reset_local_logs] done. Manual Trade Log, Reconciliation, and "
        "Moltbook are now empty.\n  Live Signals / Signal Inbox (signal_events) "
        "were NOT touched."
    )
    print(
        "[reset_local_logs] [safety] broker_api_called=False "
        "ai_execution_count=0 execution_gate=LOCKED record_keeping_only=True"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
