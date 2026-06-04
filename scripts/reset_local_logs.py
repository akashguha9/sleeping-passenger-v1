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

Usage
-----
    python scripts/reset_local_logs.py                # dry run (shows counts)
    python scripts/reset_local_logs.py --apply        # wipe for real (+backup)
    python scripts/reset_local_logs.py --apply --no-backup
    python scripts/reset_local_logs.py --apply --keep-jsonl   # DB only
    python scripts/reset_local_logs.py --db /path/to/mvp_local.db --apply
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
        return 0

    # --- APPLY -----------------------------------------------------------
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
