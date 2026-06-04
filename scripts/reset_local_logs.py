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
* Dry-run by default: prints the row/line counts that WOULD be removed and
  exits without changing anything. Pass ``--apply`` to actually wipe.
* Before wiping, a timestamped backup copy of the database is written next
  to it (``mvp_local.db.bak-YYYYMMDDTHHMMSSZ``) unless ``--no-backup``.
* This is record-keeping only. It never calls a broker and never changes
  ``ai_execution_count`` / ``broker_api_called`` — those stay 0 / false.
* ``--apply`` is a privileged maintenance action routed through the operator
  guard (``operator_permission_guard`` + ``operator_audit_log``): it requires
  the ADMIN role and is audited. The dry-run needs no role. The guard never
  unlocks broker execution.

Usage
-----
    python scripts/reset_local_logs.py                       # dry run (no role)
    python scripts/reset_local_logs.py --apply --operator-role admin   # wipe (+backup)
    # ...or set the role via env instead of the flag:
    MVP_OPERATOR_ROLE=ADMIN python scripts/reset_local_logs.py --apply
    python scripts/reset_local_logs.py --apply --operator-role admin --no-backup
    python scripts/reset_local_logs.py --apply --operator-role admin --keep-jsonl
    python scripts/reset_local_logs.py --db /path/to/mvp_local.db --apply --operator-role admin

On Windows PowerShell, set the env var for one session with:
    $env:MVP_OPERATOR_ROLE = "ADMIN"
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve the canonical DB path and JSONL log locations from the app's own
# modules so this stays in lock-step with the rest of the codebase.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import persistence  # noqa: E402
import signal_inbox_api  # noqa: E402
import moltbook_api  # noqa: E402

# Operator-guard boundary. This is a high-severity local mutation (it runs
# ``DELETE FROM`` on the runtime DB), so — like the other maintenance scripts
# (moltbook_cleanup_fake_seed, quarantine_fake_manual_trades, …) — the
# destructive ``--apply`` path routes through the centralized operator guard:
# ADMIN authorization is required and the mutation is audited. Advisory-only;
# the guard NEVER unlocks broker execution.
try:  # noqa: E402
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]
try:  # noqa: E402
    from scripts.operator_audit_log import enforce as _enforce
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from operator_audit_log import enforce as _enforce  # type: ignore[no-redef]

# Tables to purge, in an order that is safe regardless of any future foreign
# keys (children before parents).
_TABLES: tuple[str, ...] = (
    "reconciliation_results",
    "moltbook_entries",
    "manual_trades",
)

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Wipe local Manual Trade Log, Reconciliation, and Moltbook "
            "records (DB + JSONL). Dry-run unless --apply is given."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag the script only reports counts.",
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
        "--operator-role",
        default=None,
        help=(
            "Operator role for the guard (VIEWER/OPERATOR/ADMIN). --apply is a "
            "privileged maintenance action and requires ADMIN; resolves from the "
            "MVP_OPERATOR_ROLE env var when omitted. Never unlocks execution."
        ),
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
        db_counts: dict[str, int] = {t: 0 for t in _TABLES}
    else:
        conn = sqlite3.connect(str(db_path))
        try:
            db_counts = {t: _table_count(conn, t) for t in _TABLES}
        finally:
            conn.close()

    print("\nDatabase tables:")
    for table in _TABLES:
        print(f"  {table:<22} {db_counts[table]:>6} row(s)")

    jsonl_counts = {p: _jsonl_line_count(p) for p in _JSONL_LOGS}
    print("\nJSONL fallback logs:")
    for path in _JSONL_LOGS:
        exists = "exists" if path.exists() else "absent"
        print(f"  {path.name:<34} {jsonl_counts[path]:>6} line(s)  [{exists}]")

    total_rows = sum(db_counts.values())
    total_lines = sum(jsonl_counts.values())

    if not args.apply:
        print(
            "\n[reset_local_logs] DRY-RUN — nothing was deleted.\n"
            f"  Would delete {total_rows} DB row(s)"
            + ("" if args.keep_jsonl else f" and {total_lines} JSONL line(s)")
            + ".\n  Re-run with --apply to perform the wipe."
        )
        # Advisory dry-run receipt (audit-only, never canonical) — the same
        # convention the other guarded maintenance scripts follow.
        _guard.write_dry_run_receipt(
            "reset_local_logs", target_count=total_rows, db_path=str(db_path)
        )
        return 0

    # --- APPLY -----------------------------------------------------------
    # Operator authorization. ``--apply`` is a privileged ADMIN maintenance
    # action (it deletes rows from the runtime DB). ``enforce`` audits and
    # fails closed; ``build_apply_decision`` produces the guard-validated
    # PermissionDecision the mutation context requires. Advisory-only — the
    # decision carries execution_gate=LOCKED, broker_api_called=False.
    try:
        _enforce(
            "cleanup_scripts",
            role=args.operator_role,
            resource="manual_trades,reconciliation_results,moltbook_entries",
        )
    except PermissionError as exc:
        print(f"[reset_local_logs] [DENY] {exc}")
        print(
            "  --apply requires ADMIN. Re-run with --operator-role admin "
            "or set MVP_OPERATOR_ROLE=ADMIN."
        )
        return 2
    try:
        decision = _guard.build_apply_decision(
            "reset_local_logs",
            _guard.OperationClass.REPAIR_WRITE,
            str(db_path),
            operator_role=args.operator_role,
            reason=(
                f"{_guard.NO_DRY_RUN_NEEDED}: idempotent full-table wipe of the "
                "local advisory journals; default mode is the read-only dry-run."
            ),
        )
    except PermissionError as exc:
        print(f"[reset_local_logs] [DENY] {exc}")
        return 2

    with _guard.guarded_mutation_context(
        decision,
        operation_name="reset_local_logs",
        operation_class=_guard.OperationClass.REPAIR_WRITE,
        require_dry_run=False,
    ):
        if db_path.exists() and not args.no_backup:
            backup = db_path.with_name(f"{db_path.name}.bak-{_utc_stamp()}")
            shutil.copy2(db_path, backup)
            print(f"\n[reset_local_logs] backup written: {backup}")

        deleted_rows = 0
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            try:
                for table in _TABLES:
                    exists = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if not exists:
                        continue
                    cur = conn.execute(f"DELETE FROM {table}")
                    deleted_rows += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                conn.commit()
                # Reclaim space and reset autoincrement counters for a clean slate.
                conn.execute("VACUUM")
            finally:
                conn.close()
        print(f"[reset_local_logs] deleted {deleted_rows} DB row(s).")

        cleared_files = 0
        if not args.keep_jsonl:
            for path in _JSONL_LOGS:
                if path.exists():
                    path.unlink()
                    cleared_files += 1
            print(f"[reset_local_logs] removed {cleared_files} JSONL log file(s).")
        else:
            print("[reset_local_logs] --keep-jsonl set; JSONL logs left untouched.")

    print(
        "\n[reset_local_logs] done. Manual Trade Log, Reconciliation, and "
        "Moltbook are now empty.\n  Live Signals / Signal Inbox (signal_events) "
        "were NOT touched."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
