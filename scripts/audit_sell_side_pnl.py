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
from decimal import Decimal
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import persistence  # noqa: E402
from runtime_common import restrict_file_permissions  # noqa: E402
from backup_db import perform_backup  # noqa: E402
from money import money_to_str  # noqa: E402
from reconciliation_extras import compute_realized_pnl  # noqa: E402

try:
    from scripts import operator_permission_guard as _guard  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]  # noqa: E402

# Central permission-guard identity: rewriting stored P/L rows is a
# destructive-but-record-keeping REPAIR_WRITE (OPERATOR+), same class as
# reset_local_logs.  Report-only mode is open to any role.
OPERATION_NAME = "audit_sell_side_pnl"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE

# Stored vs corrected differences below one basis point of a cent are
# float-repr noise, not a sign inversion.
_TOLERANCE = Decimal("0.000001")


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(0)


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
        stored = _dec(r["pnl_estimate"] or 0)
        corrected = compute_realized_pnl(
            entry_price=_dec(r["entry_price"] or 0),
            exit_price=_dec(r["actual_fill_price"] or 0),
            exit_quantity=_dec(r["actual_quantity"] or 0),
            side="SELL",
        )
        findings.append(
            {
                "reconciliation_id": r["reconciliation_id"],
                "trade_id": r["trade_id"],
                "ticker": r["ticker"],
                "outcome_status": r["outcome_status"],
                "entry_price": money_to_str(_dec(r["entry_price"] or 0)),
                "actual_fill_price": money_to_str(_dec(r["actual_fill_price"] or 0)),
                "actual_quantity": money_to_str(_dec(r["actual_quantity"] or 0)),
                "stored_pnl": money_to_str(stored),
                "corrected_pnl": money_to_str(corrected),
                "consistent": abs(stored - corrected) <= _TOLERANCE,
            }
        )
    return findings


@_guard.guarded_mutation(
    operation_name=OPERATION_NAME,
    operation_class=OPERATION_CLASS,
    expected_role_floor=_guard.OperatorRole.OPERATOR,
    require_dry_run=True,
)
def apply_corrections(
    db_path: Path,
    flagged: list[dict[str, Any]],
    *,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Backup the DB, then rewrite pnl_estimate for the flagged rows.

    Write-boundary guarded (audit F4 + Kanté write doctrine): callers must
    supply a guard-validated OPERATOR+ REPAIR_WRITE decision with a recent
    dry-run receipt; the decorator raises PermissionError otherwise.
    """
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
        help="Rewrite flagged rows (requires OPERATOR/ADMIN role, a recent "
        "dry-run receipt, and a successful automatic backup). Default is "
        "report-only.",
    )
    parser.add_argument(
        "--operator-role",
        default=None,
        help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env, else "
        "VIEWER). --apply requires OPERATOR or ADMIN.",
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
    restrict_file_permissions(report_path)

    print(
        f"[audit_sell_side_pnl] {len(findings)} SELL reconciliation(s); "
        f"{len(flagged)} flagged as sign-inverted. Report: {report_path}"
    )
    for f in flagged:
        print(
            f"  {f['reconciliation_id']} {f['ticker']:>8} "
            f"stored={f['stored_pnl']} corrected={f['corrected_pnl']}"
        )

    if not flagged:
        return 0
    if not args.apply:
        # Record a dry-run receipt so a later --apply (OPERATOR+) can prove
        # a dry-run happened — same contract as reset_local_logs.
        try:
            receipt = _guard.write_dry_run_receipt(
                OPERATION_NAME, target_count=len(flagged), db_path=str(args.db)
            )
            print(f"[audit_sell_side_pnl] dry-run receipt written: {receipt.name}")
        except Exception as exc:  # pragma: no cover - receipt is best-effort
            # Failure here is fail-CLOSED (a later --apply is refused
            # without a receipt), but it must still be visible.
            print(
                f"[audit_sell_side_pnl] WARNING: dry-run receipt not "
                f"written ({type(exc).__name__}); --apply will be refused"
            )
        print("[audit_sell_side_pnl] DRY-RUN — nothing rewritten. Use --apply.")
        return 0

    # --apply: central permission guard (fails closed; audits allow/deny).
    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(args.db),
            operator_role=args.operator_role,
        )
    except PermissionError as exc:
        print(f"[audit_sell_side_pnl] [DENY] {exc}", file=sys.stderr)
        return 2

    try:
        result = apply_corrections(
            args.db, flagged, permission_decision=decision
        )
    except PermissionError as exc:  # defence-in-depth boundary refusal
        print(f"[audit_sell_side_pnl] [DENY] {exc}", file=sys.stderr)
        return 2
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
