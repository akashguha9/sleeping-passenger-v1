"""
Narrow, idempotent backfill that stamps ``created_via='manual_trade_log'``
on the exact set of legitimate Manual Trade Log rows the operator
entered before the provenance column existed.

Why a backfill is needed
------------------------
The provenance contract (see ``scripts/reconciliation_queue.py`` and
``scripts/learning_completeness_report.py``) excludes rows whose
``created_via`` is empty / unknown.  That is the correct safe default —
seed/demo/import scripts that called ``persistence.insert_manual_trade``
directly never set this column, so hundreds of SPY/QQQ rows from
``scripts/local_mvp_smoke_test.py`` and the gsheet-export fixture are
correctly excluded going forward.

But the operator's own legitimate rows, logged through the Manual Trade
Log UI before this sprint shipped, ALSO have an empty provenance.  This
script marks only those exact rows (matched by ``trade_id``) so they
re-appear in Reconciliation without re-entry.

Hard rules
----------
* NEVER calls a broker.
* NEVER places, modifies, or cancels any order.
* NEVER touches ``ai_execution_count`` or ``broker_api_called``.
* NEVER fabricates provenance: only the exact ``trade_id`` values
  listed in ``LEGITIMATE_TRADE_IDS`` are touched.
* NEVER cascades: refuses to run if a listed row's ticker/quantity does
  not match the expected fingerprint (defends against accidental
  re-targeting if trade_ids were ever recycled).

Usage
-----
    python scripts/backfill_manual_trade_log_provenance.py            # dry run
    python scripts/backfill_manual_trade_log_provenance.py --apply    # write
    python scripts/backfill_manual_trade_log_provenance.py --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts.persistence import DB_PATH as _DEFAULT_DB_PATH
except ModuleNotFoundError:
    from persistence import DB_PATH as _DEFAULT_DB_PATH  # type: ignore[no-redef]

try:
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]

# Operation identity for the central permission guard.  Stamping provenance on
# a fixed, fingerprinted set of operator rows is a REPAIR_WRITE (OPERATOR+) —
# never a delete, never schema change, never an execution action.
OPERATION_NAME = "backfill_manual_trade_log_provenance"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE


# Each entry is a fingerprint of one legitimate row.  All four fields
# must match the DB row exactly (within the price tolerance) before this
# script will stamp it; mismatch aborts.  This is deliberately
# narrow — broad backfill is what created the original mess.
LEGITIMATE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "trade_id": "MT_2043e9eae023",
        "ticker": "BHARTIARTL.NS",
        "expected_qty": 2.583,
        "expected_price": 61.9474,
    },
    {
        "trade_id": "MT_175a9e9b05e0",
        "ticker": "ICICIBANK.NS",
        "expected_qty": 3.8908,
        "expected_price": 40.722,
    },
    {
        "trade_id": "MT_0ec688be891c",
        "ticker": "ICICIBANK.NS",
        "expected_qty": 3.8908,
        "expected_price": 40.722,
    },
    {
        "trade_id": "MT_125d162fee8d",
        "ticker": "SAP.DE",
        "expected_qty": 4.2917,
        "expected_price": 91.348,
    },
)

_PRICE_TOLERANCE = 1e-4
_QTY_TOLERANCE = 1e-6


def _matches(row: sqlite3.Row, fp: dict[str, Any]) -> bool:
    if row["ticker"] != fp["ticker"]:
        return False
    try:
        qty = float(row["quantity"])
        price = float(row["price"])
    except (TypeError, ValueError):
        return False
    if abs(qty - float(fp["expected_qty"])) > _QTY_TOLERANCE:
        return False
    if abs(price - float(fp["expected_price"])) > _PRICE_TOLERANCE:
        return False
    return True


def run(
    db_path: Path,
    apply: bool,
    *,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Scan (and, when ``apply``, stamp) the fixed legitimate-row set.

    Function-level guard (Kanté Task 4 / collapsed Task B): the ``apply`` write
    branch calls the shared :func:`operator_permission_guard.assert_guarded_mutation`
    helper (the same enforcement the decorator/context manager use).  A direct
    importer that calls ``run(db, apply=True)`` without a guard-validated decision
    raises ``PermissionError`` before any UPDATE.  This dual-mode function calls
    the helper directly because its scan/write logic is interleaved in one loop
    and does not fit a single ``with`` block.  The dry-run (``apply=False``) scan
    needs no decision.
    """
    if apply:
        _guard.assert_guarded_mutation(
            permission_decision,
            operation_name=OPERATION_NAME,
            operation_class=OPERATION_CLASS,
            expected_role_floor=_guard.OperatorRole.OPERATOR,
            require_dry_run=True,
        )
    report: dict[str, Any] = {
        "operation": "backfill_manual_trade_log_provenance",
        "db_path": str(db_path),
        "applied": apply,
        "matched": [],
        "mismatched": [],
        "missing": [],
        "already_stamped": [],
        "stamped_count": 0,
        # Safety stamps mirror the rest of the codebase.
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "execution_mode": "HUMAN_ONLY",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "record_keeping_only": True,
    }
    if not db_path.exists():
        report["error"] = f"db_missing: {db_path}"
        return report

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        if "created_via" not in cols:
            report["error"] = (
                "created_via column missing — initialize schema first by "
                "importing scripts.persistence (init_schema)."
            )
            return report

        for fp in LEGITIMATE_ROWS:
            row = conn.execute(
                "SELECT trade_id, ticker, quantity, price,"
                " COALESCE(created_via,'') AS created_via,"
                " COALESCE(broker_api_called,0) AS broker_api_called,"
                " COALESCE(ai_execution_count,0) AS ai_execution_count"
                " FROM manual_trades WHERE trade_id=? LIMIT 1",
                (fp["trade_id"],),
            ).fetchone()
            if row is None:
                report["missing"].append(fp["trade_id"])
                continue
            if not _matches(row, fp):
                report["mismatched"].append(
                    {
                        "trade_id": fp["trade_id"],
                        "expected": {
                            "ticker": fp["ticker"],
                            "quantity": fp["expected_qty"],
                            "price": fp["expected_price"],
                        },
                        "found": {
                            "ticker": row["ticker"],
                            "quantity": row["quantity"],
                            "price": row["price"],
                        },
                    }
                )
                continue
            # Defence in depth: never touch a row that claims broker
            # involvement.
            if int(row["broker_api_called"] or 0) != 0:
                report["mismatched"].append(
                    {
                        "trade_id": fp["trade_id"],
                        "reason": "row has broker_api_called=1; refusing to stamp",
                    }
                )
                continue
            if int(row["ai_execution_count"] or 0) != 0:
                report["mismatched"].append(
                    {
                        "trade_id": fp["trade_id"],
                        "reason": "row has ai_execution_count!=0; refusing to stamp",
                    }
                )
                continue
            if str(row["created_via"] or "").strip() == "manual_trade_log":
                report["already_stamped"].append(fp["trade_id"])
                continue
            report["matched"].append(fp["trade_id"])
            if apply:
                conn.execute(
                    "UPDATE manual_trades SET created_via=?"
                    " WHERE trade_id=? AND COALESCE(created_via,'')=''"
                    " AND COALESCE(broker_api_called,0)=0"
                    " AND COALESCE(ai_execution_count,0)=0",
                    ("manual_trade_log", fp["trade_id"]),
                )
                report["stamped_count"] += 1
        if apply:
            conn.commit()
    finally:
        conn.close()
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="backfill_manual_trade_log_provenance.py",
        description=(
            "Stamp created_via='manual_trade_log' on the exact set of "
            "operator-entered manual trades that pre-date the provenance "
            "column.  Narrow and idempotent; never calls a broker."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the change (requires MVP_OPERATOR_ROLE=OPERATOR "
             "or ADMIN and a recent dry-run receipt).  Without this flag, "
             "prints the plan.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (default behaviour); writes a permission "
             "dry-run receipt so a subsequent --apply can proceed. Read-only.",
    )
    p.add_argument(
        "--operator-role",
        default=None,
        help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env, else "
             "VIEWER).  --apply requires OPERATOR or ADMIN.",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else Path(_DEFAULT_DB_PATH)

    if not args.apply:
        # Dry-run: read-only scan, open to any role.  Record a receipt so a
        # later --apply (by an authorized role) can prove a dry-run happened.
        report = run(db_path, apply=False)
        try:
            matched = len(report.get("matched", []))
            receipt = _guard.write_dry_run_receipt(
                OPERATION_NAME, target_count=matched, db_path=str(db_path))
            report["dry_run_receipt"] = receipt.name
        except Exception:  # pragma: no cover - receipt is best-effort
            pass
        _emit(report, json_mode=args.json, applied=False)
        return 0 if "error" not in report else 1

    # --apply path: central permission guard (fails closed; audits allow/deny).
    # CLI request/role/receipt boilerplate collapsed into build_apply_decision.
    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(db_path),
            operator_role=args.operator_role)
    except PermissionError as exc:
        print(f"[backfill] [DENY] {exc}")
        return 2

    report = run(db_path, apply=True, permission_decision=decision)
    _emit(report, json_mode=args.json, applied=True)
    return 0 if "error" not in report else 1


def _emit(report: dict[str, Any], *, json_mode: bool, applied: bool) -> None:
    if json_mode:
        print(json.dumps(report, sort_keys=True, indent=2, default=str))
    else:
        print(f"db_path: {report['db_path']}")
        print(f"applied: {report['applied']}")
        print(f"matched: {report['matched']}")
        print(f"already_stamped: {report['already_stamped']}")
        print(f"missing: {report['missing']}")
        print(f"mismatched: {report['mismatched']}")
        print(f"stamped_count: {report['stamped_count']}")
        if "error" in report:
            print(f"error: {report['error']}")


if __name__ == "__main__":
    raise SystemExit(main())
