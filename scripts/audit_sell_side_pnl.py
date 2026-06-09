#!/usr/bin/env python3
"""F4 one-off audit: find SELL-side reconciliations with sign-inverted P/L.

Background
----------
Audit finding F4: until the side-aware fix in
:func:`scripts.reconciliation_extras.compute_realized_pnl`, every
reconciled ``side='SELL'`` trade had its realized P/L computed with the
long-only formula ``(exit - entry) * qty`` — the exact negation of the
true short-side P/L.  Historical rows persisted before the fix may
therefore carry an inverted ``pnl_estimate``.

What this script does
---------------------
* **Report (default, read-only):** joins ``reconciliation_results`` to
  ``manual_trades`` on ``trade_id``, selects rows where the trade side is
  SELL, recomputes the corrected P/L from the stored entry price, fill
  price and quantity, and prints stored vs corrected.  Rows where stored
  == corrected (operator typed the P/L manually with the right sign, or
  pnl came straight from the request) are listed as ALREADY_CONSISTENT.
* **--apply:** rewrites ``pnl_estimate`` for the flagged rows ONLY after
  a successful automatic backup via :mod:`scripts.backup_db` (native
  ``sqlite3`` backup API).  Every rewritten row is recorded in a JSON
  report next to the DB.  Without ``--apply`` nothing is written.

This never calls a broker, never grants execution permission —
record-keeping repair only.

Usage
-----
    python scripts/audit_sell_side_pnl.py                 # report only
    python scripts/audit_sell_side_pnl.py --apply         # backup + fix
    python scripts/audit_sell_side_pnl.py --db path/to.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import persistence  # noqa: E402
from backup_db import perform_backup  # noqa: E402
from reconciliation_extras import compute_realized_pnl  # noqa: E402

# Stored vs corrected differences below one basis point of a cent are
# float-repr noise, not a sign inversion.
_TOLERANCE = 1e-6


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def collect_sell_side_rows(db_path: Path) -> list[dict[str, Any]]:
    """Return every SELL-trade reconciliation with stored vs corrected P/L."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT r.reconciliation_id, r.trade_id, r.pnl_estimate,"
            "       r.actual_fill_price, r.actual_quantity, r.outcome_status,"
            "       t.side, t.price AS entry_price, t.ticker"
            " FROM reconciliation_results r"
            " JOIN manual_trades t ON t.trade_id = r.trade_id"
            " WHERE UPPER(TRIM(t.side)) = 'SELL'"
            " ORDER BY r.reconciled_at",
        ).fetchall()
    finally:
        conn.close()

    findings: list[dict[str, Any]] = []
    for r in rows:
        stored = float(r["pnl_estimate"] or 0.0)
        corrected = compute_realized_pnl(
            entry_price=float(r["entry_price"] or 0.0),
            exit_price=float(r["actual_fill_price"] or 0.0),
            exit_quantity=float(r["actual_quantity"] or 0.0),
            side="SELL",
        )
        findings.append(
            {
                "reconciliation_id": r["reconciliation_id"],
                "trade_id": r["trade_id"],
                "ticker": r["ticker"],
                "outcome_status": r["outcome_status"],
                "entry_price": float(r["entry_price"] or 0.0),
                "actual_fill_price": float(r["actual_fill_price"] or 0.0),
                "actual_quantity": float(r["actual_quantity"] or 0.0),
                "stored_pnl": stored,
                "corrected_pnl": corrected,
                "consistent": abs(stored - corrected) <= _TOLERANCE,
            }
        )
    return findings


def apply_corrections(
    db_path: Path, flagged: list[dict[str, Any]]
) -> dict[str, Any]:
    """Backup the DB, then rewrite pnl_estimate for the flagged rows."""
    backup = perform_backup(
        db_path, db_path.parent / "backups", label="pre-f4-pnl-repair"
    )
    if not backup.get("ok"):
        return {
            "applied": 0,
            "error": f"refusing to write without a backup: {backup.get('error')}",
        }
    conn = sqlite3.connect(str(db_path))
    applied = 0
    try:
        for f in flagged:
            cur = conn.execute(
                "UPDATE reconciliation_results SET pnl_estimate=?"
                " WHERE reconciliation_id=?",
                (f["corrected_pnl"], f["reconciliation_id"]),
            )
            applied += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    finally:
        conn.close()
    return {"applied": applied, "backup_path": backup.get("backup_path")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db",
        type=Path,
        default=persistence.DB_PATH,
        help="SQLite DB path (default: canonical runtime DB)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite flagged rows (requires a successful automatic backup). "
        "Default is report-only.",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"[audit_sell_side_pnl] DB not found: {args.db}")
        return 2

    findings = collect_sell_side_rows(args.db)
    flagged = [f for f in findings if not f["consistent"]]

    report = {
        "generated_at": _utc_stamp(),
        "db_path": str(args.db),
        "sell_side_reconciliations": len(findings),
        "flagged_sign_inversions": len(flagged),
        "findings": findings,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }
    report_path = args.db.parent / f"sell_side_pnl_audit_{_utc_stamp()}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(
        f"[audit_sell_side_pnl] {len(findings)} SELL reconciliation(s); "
        f"{len(flagged)} flagged as sign-inverted. Report: {report_path}"
    )
    for f in flagged:
        print(
            f"  {f['reconciliation_id']} {f['ticker']:>8} "
            f"stored={f['stored_pnl']:+.4f} corrected={f['corrected_pnl']:+.4f}"
        )

    if not flagged:
        return 0
    if not args.apply:
        print("[audit_sell_side_pnl] DRY-RUN — nothing rewritten. Use --apply.")
        return 0

    result = apply_corrections(args.db, flagged)
    if result.get("error"):
        print(f"[audit_sell_side_pnl] REFUSED: {result['error']}")
        return 2
    print(
        f"[audit_sell_side_pnl] corrected {result['applied']} row(s); "
        f"backup at {result['backup_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
