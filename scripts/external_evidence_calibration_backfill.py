"""Batch backfill — link historical closed trades to external-evidence outcomes.

EXTERNAL_EVIDENCE_CALIBRATION_BACKFILL
======================================

:mod:`scripts.external_evidence_moltbook_calibration` learns from ONE closed
trade at a time at outcome-time.  But snapshots persisted before that loop
shipped were never paired with their (already-closed) trades.  This script is
the one-shot batch driver: it scans closed/reconciled manual trades, builds a
``trade_outcome`` for each, and routes it through
:func:`record_external_evidence_outcome_for_trade` so historical evidence gets
its advisory calibration record.

Safety contract (mission P0)
----------------------------
* **Dry-run by default.**  ``run_backfill(apply=False)`` (the default) computes
  the full plan and writes NOTHING.  Real writes require the explicit
  ``--apply`` CLI flag, which routes through the central
  :mod:`scripts.operator_permission_guard` (operator role + audit log) before
  any DB mutation.
* It only ever writes to the advisory ``external_evidence_outcomes`` /
  ``external_evidence_calibration_buckets`` tables (EVIDENCE_ONLY,
  ``real_money_sizing_impact='PROHIBITED'``).  It NEVER mutates trade rows,
  open positions, or execution state.
* No broker order, no order placement, no execution.  ``broker_api_called`` is
  always False and ``ai_execution_count`` is always 0.  Any failure degrades to
  an ``ERROR_SAFE`` per-trade result; the batch never raises.

Usage
-----
    python scripts/external_evidence_calibration_backfill.py            # dry run
    python scripts/external_evidence_calibration_backfill.py --apply    # write
    python scripts/external_evidence_calibration_backfill.py --json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import scripts.persistence as _persistence
    import scripts.external_evidence_persistence as eep
    import scripts.external_evidence_moltbook_calibration as cal
    from scripts import operator_permission_guard as _guard
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]
    import external_evidence_persistence as eep  # type: ignore[no-redef]
    import external_evidence_moltbook_calibration as cal  # type: ignore[no-redef]
    import operator_permission_guard as _guard  # type: ignore[no-redef]
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


# Operation identity for the central permission guard.  Writing advisory
# learning rows is an AUDIT_ONLY_WRITE (OPERATOR+) — never a delete, never a
# schema change, never an execution action.
OPERATION_NAME = "external_evidence_calibration_backfill"
OPERATION_CLASS = _guard.OperationClass.AUDIT_ONLY_WRITE

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
EXECUTION_GATE_LOCKED = "LOCKED"


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _build_closed_trade_outcomes(db_path: Path | None) -> list[dict[str, Any]]:
    """Join manual trades + reconciliations into closed ``trade_outcome`` dicts.

    Read-only: each persistence getter opens and closes its own connection.
    Only reconciliations whose status is a closed/final state AND which have a
    matching entry price + a non-null exit price become a learnable outcome.
    """
    target = db_path if db_path is not None else _persistence.DB_PATH
    trades = {t.get("trade_id"): t for t in _persistence.get_all_manual_trades(target)}
    reconciliations = _persistence.get_all_reconciliations(target)

    outcomes: list[dict[str, Any]] = []
    for rec in reconciliations:
        status = str(rec.get("outcome_status") or "").strip().upper()
        if status in cal._OPEN_STATES or status not in cal._CLOSED_STATES:
            continue
        trade = trades.get(rec.get("trade_id")) or {}
        entry_price = _f(trade.get("price"))
        exit_price = _f(rec.get("actual_fill_price"))
        if entry_price in (None, 0.0) or exit_price is None:
            continue
        outcomes.append(
            {
                "trade_id": rec.get("trade_id"),
                "signal_id": trade.get("event_id") or rec.get("event_id"),
                "ticker": trade.get("ticker"),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_timestamp_utc": trade.get("executed_at"),
                "exit_timestamp_utc": rec.get("reconciled_at"),
                "status": status,
                "closed": True,
                "outcome_event_type": status,
                "realized_r_multiple": None,
                "holding_days": None,
            }
        )
    return outcomes


def run_backfill(
    apply: bool = False,
    db_path: Path | None = None,
    *,
    conn: Any = None,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Backfill external-evidence outcomes for all closed trades.

    ``apply=False`` (default) is a full dry-run: it reports ``records_would_
    create`` without writing.  ``apply=True`` writes idempotently via
    :func:`record_external_evidence_outcome_for_trade`.

    When called as the CLI ``--apply`` path, ``permission_decision`` carries a
    guard-validated operator decision; direct/library callers (and the test
    suite) may invoke ``apply=True`` to drive the advisory-only calibration
    tables, which never touch trades or execution state.
    """
    if apply and permission_decision is not None:
        _guard.assert_guarded_mutation(
            permission_decision,
            operation_name=OPERATION_NAME,
            operation_class=OPERATION_CLASS,
            expected_role_floor=_guard.OperatorRole.OPERATOR,
            require_dry_run=False,
        )

    report: dict[str, Any] = {
        "operation": OPERATION_NAME,
        "dry_run": not apply,
        "applied": bool(apply),
        "scanned_trades": 0,
        "records_would_create": 0,
        "records_created": 0,
        "records_skipped": 0,
        "buckets_updated": 0,
        "trades_no_matching_evidence": 0,
        "generated_at_utc": utc_timestamp(),
        # Hard advisory safety stamps.
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": EXECUTION_GATE_LOCKED,
        "execution_mode": "HUMAN_ONLY",
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "record_keeping_only": True,
    }

    outcomes = _build_closed_trade_outcomes(db_path)

    owned = conn is None
    if conn is None:
        conn = eep._open(db_path)
    try:
        for trade_outcome in outcomes:
            report["scanned_trades"] += 1
            result = cal.record_external_evidence_outcome_for_trade(
                trade_outcome, apply=apply, conn=conn
            )
            if result.get("status") == cal.STATUS_NO_MATCH:
                report["trades_no_matching_evidence"] += 1
            report["records_would_create"] += int(result.get("records_would_create", 0))
            report["records_created"] += int(result.get("records_created", 0))
            report["records_skipped"] += int(result.get("records_skipped", 0))
            report["buckets_updated"] += int(result.get("buckets_updated", 0))
    finally:
        if owned:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive
                pass
    return report


def _emit(report: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(report, sort_keys=True, indent=2, default=str))
        return
    print(f"operation        : {report['operation']}")
    print(f"dry_run          : {report['dry_run']}")
    print(f"scanned_trades   : {report['scanned_trades']}")
    print(f"would_create     : {report['records_would_create']}")
    print(f"records_created  : {report['records_created']}")
    print(f"records_skipped  : {report['records_skipped']}")
    print(f"buckets_updated  : {report['buckets_updated']}")
    print(f"no_evidence      : {report['trades_no_matching_evidence']}")
    print(f"real_money_sizing: {report['real_money_sizing_impact']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="external_evidence_calibration_backfill.py",
        description=(
            "Backfill advisory external-evidence calibration outcomes for "
            "historical closed trades.  Dry-run by default; --apply writes "
            "only the advisory calibration tables and never calls a broker."
        ),
    )
    parser.add_argument("--db-path", type=str, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write outcomes (requires MVP_OPERATOR_ROLE=OPERATOR or ADMIN). "
             "Without this flag, prints the dry-run plan only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (default behaviour). Read-only.",
    )
    parser.add_argument(
        "--operator-role",
        default=None,
        help="VIEWER|OPERATOR|ADMIN (default: MVP_OPERATOR_ROLE env, else VIEWER).",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else None

    if not args.apply:
        report = run_backfill(apply=False, db_path=db_path)
        try:
            _guard.write_dry_run_receipt(
                OPERATION_NAME,
                target_count=report["records_would_create"],
                db_path=str(db_path) if db_path else None,
            )
        except Exception:  # pragma: no cover - receipt is best-effort
            pass
        _emit(report, json_mode=args.json)
        return 0

    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS,
            str(db_path) if db_path else None,
            operator_role=args.operator_role,
        )
    except PermissionError as exc:
        print(f"[backfill] [DENY] {exc}")
        return 2

    report = run_backfill(apply=True, db_path=db_path, permission_decision=decision)
    _emit(report, json_mode=args.json)
    return 0


__all__ = ["OPERATION_NAME", "OPERATION_CLASS", "run_backfill"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
