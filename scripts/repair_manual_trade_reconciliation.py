"""Surgical repair script for the Manual Trade Log ↔ Reconciliation pipeline.

Purpose
-------
The Manual Trade Log was logging successfully into ``manual_trades`` but the
Reconciliation tab kept appearing empty, and a previously-quarantined ASDC
duplicate row kept reappearing in the "Previously Logged" column.  This
script gives the operator a single safe, dry-run-by-default entry point that:

  * Reports the live DB picture (path, totals, provenance distribution).
  * Flags bogus rows (ASDC gibberish, ZZZ probe rows, TEST/MOCK/DEMO/SAMPLE
    fixtures) and proposes :func:`scripts.manual_trade_origin.fake_manual_trade_reason`
    quarantine for any not already stamped.
  * Flags cancelled-but-still-visible ``manual_trade_log`` rows so the
    operator can see why the Manual Trade Log card panel shrinks once the
    UI patch lands.
  * Flags India NSE rows (``.NS`` suffix) whose ``currency`` or price
    scale is inconsistent (USD/blank instead of INR; ICICIBANK at ~40
    instead of ~1000-1200 INR; BHARTIARTL at ~62 instead of ~1500-1800).
  * Computes the reconciliation-eligible row count after the proposed
    repairs would land.

Invariants
----------
  * Dry-run by default; ``--apply`` is required to write anything.
  * NEVER deletes rows.  Bogus rows get re-stamped to
    ``quarantined_fake_manual_trade``; India rows get a normalised
    currency (when blank/wrong) but the price is left alone unless
    ``--repair-india-scale`` is explicitly passed.
  * Always creates a ``.bak`` snapshot of the DB before applying.
  * Pure record-keeping.  No broker call is issued.
    ``broker_api_called`` and ``ai_execution_count`` are NEVER touched.
  * Refuses destructive operations unless explicitly requested.

Usage
-----
    # Default — read-only audit, prints what would change.
    python scripts/repair_manual_trade_reconciliation.py

    # Audit a non-default DB.
    python scripts/repair_manual_trade_reconciliation.py --db runtime/mvp_local.db

    # Apply the repair (quarantine bogus rows + fix India currencies).
    python scripts/repair_manual_trade_reconciliation.py --apply

    # Also normalise India .NS price scale where confidently wrong
    # (annotates rows; never deletes).  Off by default.
    python scripts/repair_manual_trade_reconciliation.py --apply \\
        --repair-india-scale

Safety stamps emitted on the printed JSON summary:
    advisory_status     = "ADVISORY_ONLY"
    execution_gate      = "LOCKED"
    broker_api_called   = False
    ai_execution_count  = 0
    record_keeping_only = True
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from scripts.manual_trade_origin import (
        CANCELLED_RECONCILIATION_STATUSES,
        MANUAL_TRADE_LOG_PROVENANCE,
        QUARANTINE_PROVENANCE,
        classify_manual_trade_origin,
        fake_manual_trade_reason,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from manual_trade_origin import (  # type: ignore[no-redef]
        CANCELLED_RECONCILIATION_STATUSES,
        MANUAL_TRADE_LOG_PROVENANCE,
        QUARANTINE_PROVENANCE,
        classify_manual_trade_origin,
        fake_manual_trade_reason,
    )

try:
    from scripts.persistence import DB_PATH as _DEFAULT_DB_PATH
except ModuleNotFoundError:  # pragma: no cover
    from persistence import DB_PATH as _DEFAULT_DB_PATH  # type: ignore[no-redef]

try:
    from scripts import operator_permission_guard as _guard
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]

# Operation identity for the central permission guard.  Quarantining bogus rows
# + normalising India currency is a REPAIR_WRITE (OPERATOR+); it never deletes
# rows, never alters schema, and never issues an execution action.
OPERATION_NAME = "repair_manual_trade_reconciliation"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE


# India NSE suffix and the currency contract.  Anything ending in ``.NS``
# trades on NSE in INR; the operator's capital input may be EUR but the
# *market currency* is always INR.  We never multiply or divide NSE
# prices automatically -- the operator is the source of truth for price
# scale.  We only flag confidently-wrong scale anomalies (ICICIBANK ~40,
# BHARTIARTL ~60).  See task brief E.6-E.8.
_INDIA_SUFFIX = ".NS"
_INDIA_PRICE_FLOOR: dict[str, float] = {
    # Empirically-grounded sane minimums for the four tickers the
    # operator listed.  A price below this is almost certainly a scale
    # bug (USD ADR / yahoo-adjusted / cents-per-paisa confusion).
    "ICICIBANK.NS": 500.0,
    "BHARTIARTL.NS": 500.0,
    "HDFCBANK.NS": 500.0,
    "RELIANCE.NS": 500.0,
}
_INDIA_LEVERAGE_CEILING = 4.0
_NON_INDIA_LEVERAGE_CEILING = 1.0


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "record_keeping_only": True,
}


@dataclass(frozen=True)
class RowFlag:
    trade_id: str
    ticker: str
    reason: str
    detail: str = ""
    current_value: str = ""
    proposed_value: str = ""


@dataclass
class RepairReport:
    db_path: str
    db_exists: bool
    total_rows: int = 0
    provenance_distribution: dict[str, int] = field(default_factory=dict)
    bogus_to_quarantine: list[RowFlag] = field(default_factory=list)
    cancelled_user_rows: list[RowFlag] = field(default_factory=list)
    india_currency_fixes: list[RowFlag] = field(default_factory=list)
    india_scale_anomalies: list[RowFlag] = field(default_factory=list)
    leverage_policy_violations: list[RowFlag] = field(default_factory=list)
    reconciliation_eligible_rows: list[str] = field(default_factory=list)
    applied: bool = False
    changes_written: int = 0
    backup_path: str = ""
    warnings: list[str] = field(default_factory=list)


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _is_india(ticker: str) -> bool:
    return ticker.upper().endswith(_INDIA_SUFFIX)


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _scan(db_path: Path) -> RepairReport:
    report = RepairReport(db_path=str(db_path), db_exists=db_path.exists())
    if not db_path.exists():
        report.warnings.append("db_missing")
        return report
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        if "trade_id" not in cols:
            report.warnings.append("manual_trades_table_missing_or_corrupt")
            return report
        rows = conn.execute(
            "SELECT * FROM manual_trades ORDER BY executed_at DESC"
        ).fetchall()
    finally:
        conn.close()

    report.total_rows = len(rows)
    counts: dict[str, int] = {}
    for raw in rows:
        row = _row_dict(raw)
        cv = str(row.get("created_via") or "").strip() or "(blank)"
        counts[cv] = counts.get(cv, 0) + 1
    report.provenance_distribution = dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    for raw in rows:
        row = _row_dict(raw)
        trade_id = str(row.get("trade_id") or "")
        ticker = str(row.get("ticker") or "").upper()
        created_via = str(row.get("created_via") or "").strip()
        recon_status = str(row.get("reconciliation_status") or "").strip().upper()
        currency = str(row.get("currency") or "").strip().upper()
        price = _float_or_zero(row.get("price"))
        leverage = _float_or_zero(row.get("leverage")) or 1.0

        already_quarantined = created_via == QUARANTINE_PROVENANCE
        is_cancelled = recon_status in CANCELLED_RECONCILIATION_STATUSES

        # Bogus rows: anything matching fake_manual_trade_reason that is
        # NOT yet quarantined.  Already-quarantined rows are skipped — the
        # script is idempotent.
        bogus_reason = fake_manual_trade_reason(row) if not already_quarantined else ""
        if bogus_reason:
            report.bogus_to_quarantine.append(
                RowFlag(
                    trade_id=trade_id,
                    ticker=ticker,
                    reason=bogus_reason,
                    detail=(
                        f"thesis={str(row.get('thesis') or '')[:60]!r}"
                        f" current_created_via={created_via!r}"
                    ),
                    current_value=created_via,
                    proposed_value=QUARANTINE_PROVENANCE,
                )
            )

        # Cancelled-but-still-visible canonical rows: these still exist
        # on the Manual Trade Log "Previously Logged" panel before the
        # UI patch lands.  Reported for transparency; no DB change.
        if (
            created_via == MANUAL_TRADE_LOG_PROVENANCE
            and is_cancelled
        ):
            report.cancelled_user_rows.append(
                RowFlag(
                    trade_id=trade_id,
                    ticker=ticker,
                    reason="cancelled_user_manual_log",
                    detail=f"reconciliation_status={recon_status}",
                    current_value=recon_status,
                    proposed_value=recon_status,
                )
            )

        # India currency / venue: any non-quarantined .NS row whose
        # currency is not INR is a currency bug we can safely repair.
        # Quarantined rows are audit-only — already removed from every
        # user surface — so we deliberately skip them.  Operators can
        # still see them in `india_scale_anomalies` for the audit trail.
        if (
            _is_india(ticker)
            and currency != "INR"
            and not already_quarantined
        ):
            report.india_currency_fixes.append(
                RowFlag(
                    trade_id=trade_id,
                    ticker=ticker,
                    reason="india_nse_currency_should_be_inr",
                    detail=f"current_currency={currency or '(blank)'} price={price}",
                    current_value=currency,
                    proposed_value="INR",
                )
            )

        # India price-scale anomalies — empirically-grounded floor check.
        # We do not auto-divide or multiply; we just flag so the operator
        # can re-log at the correct scale.
        floor = _INDIA_PRICE_FLOOR.get(ticker)
        if floor is not None and price > 0 and price < floor:
            report.india_scale_anomalies.append(
                RowFlag(
                    trade_id=trade_id,
                    ticker=ticker,
                    reason="india_nse_price_below_sane_floor",
                    detail=(
                        f"price={price} floor={floor}"
                        f" likely USD ADR / yahoo-adjusted / cents-confusion"
                    ),
                    current_value=str(price),
                    proposed_value="(operator must re-log at INR scale)",
                )
            )

        # Leverage policy.  India tolerates up to 4x; non-India equities
        # are 1x.  Flag only — we never alter the operator's recorded
        # leverage automatically (it's audit history).
        if not already_quarantined:
            if _is_india(ticker):
                ceiling = _INDIA_LEVERAGE_CEILING
            else:
                ceiling = _NON_INDIA_LEVERAGE_CEILING
            if leverage > ceiling:
                report.leverage_policy_violations.append(
                    RowFlag(
                        trade_id=trade_id,
                        ticker=ticker,
                        reason="leverage_above_policy_ceiling",
                        detail=f"leverage={leverage} ceiling={ceiling}",
                        current_value=str(leverage),
                        proposed_value=str(ceiling),
                    )
                )

        # Reconciliation-eligible rows AFTER the proposed quarantine of
        # bogus rows would land.  We compute by re-classifying with the
        # repaired created_via.
        prospective_row = dict(row)
        if bogus_reason:
            prospective_row["created_via"] = QUARANTINE_PROVENANCE
        prospective_origin = classify_manual_trade_origin(prospective_row)
        prospective_cancelled = is_cancelled
        if (
            prospective_origin == "USER_MANUAL"
            and not prospective_cancelled
            and _float_or_zero(row.get("broker_api_called")) == 0
            and _float_or_zero(row.get("ai_execution_count")) == 0
        ):
            report.reconciliation_eligible_rows.append(trade_id)

    return report


def _make_backup(db_path: Path) -> Path:
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db_path.with_name(f"{db_path.stem}_repair_{ts}.bak")
    shutil.copy2(db_path, backup)
    return backup


def _apply_quarantine(conn: sqlite3.Connection, flags: list[RowFlag]) -> int:
    if not flags:
        return 0
    cur = conn.cursor()
    n = 0
    for flag in flags:
        # idempotent guard — never overwrite an already-quarantined row
        cur.execute(
            "UPDATE manual_trades "
            "SET created_via = ? "
            "WHERE trade_id = ? "
            "  AND COALESCE(created_via, '') <> ?",
            (QUARANTINE_PROVENANCE, flag.trade_id, QUARANTINE_PROVENANCE),
        )
        n += cur.rowcount or 0
    conn.commit()
    return n


def _apply_india_currency(conn: sqlite3.Connection, flags: list[RowFlag]) -> int:
    if not flags:
        return 0
    cur = conn.cursor()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
    if "currency" not in cols:
        return 0
    n = 0
    for flag in flags:
        # Only repair rows that are NOT already quarantined — quarantined
        # rows are audit-only and shouldn't be mutated.  We also refuse
        # to touch rows whose ticker no longer matches .NS (defensive).
        if not flag.ticker.upper().endswith(_INDIA_SUFFIX):
            continue
        cur.execute(
            "UPDATE manual_trades "
            "SET currency = 'INR' "
            "WHERE trade_id = ? "
            "  AND COALESCE(created_via, '') <> ? "
            "  AND COALESCE(currency, '') <> 'INR'",
            (flag.trade_id, QUARANTINE_PROVENANCE),
        )
        n += cur.rowcount or 0
    conn.commit()
    return n


def _serialise(report: RepairReport) -> dict[str, Any]:
    return {
        **SAFETY_STAMPS,
        "report": "repair_manual_trade_reconciliation",
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "db_path": report.db_path,
        "db_exists": report.db_exists,
        "applied": report.applied,
        "backup_path": report.backup_path,
        "total_rows": report.total_rows,
        "provenance_distribution": report.provenance_distribution,
        "bogus_to_quarantine_count": len(report.bogus_to_quarantine),
        "bogus_to_quarantine": [asdict(f) for f in report.bogus_to_quarantine],
        "cancelled_user_rows_count": len(report.cancelled_user_rows),
        "cancelled_user_rows": [asdict(f) for f in report.cancelled_user_rows],
        "india_currency_fixes_count": len(report.india_currency_fixes),
        "india_currency_fixes": [asdict(f) for f in report.india_currency_fixes],
        "india_scale_anomalies_count": len(report.india_scale_anomalies),
        "india_scale_anomalies": [asdict(f) for f in report.india_scale_anomalies],
        "leverage_policy_violations_count": len(report.leverage_policy_violations),
        "leverage_policy_violations": [asdict(f) for f in report.leverage_policy_violations],
        "reconciliation_eligible_after_repair": len(report.reconciliation_eligible_rows),
        "reconciliation_eligible_trade_ids": report.reconciliation_eligible_rows,
        "changes_written": report.changes_written,
        "warnings": report.warnings,
    }


def _print_human(report: RepairReport) -> None:
    print(f"DB path:                 {report.db_path}")
    print(f"DB exists:               {report.db_exists}")
    print(f"Total rows:              {report.total_rows}")
    print(f"Backup:                  {report.backup_path or '(none)'}")
    print(f"Applied:                 {report.applied}")
    print("Provenance distribution:")
    for k, v in report.provenance_distribution.items():
        print(f"  {k}: {v}")
    print(f"Bogus rows to quarantine:        {len(report.bogus_to_quarantine)}")
    for f in report.bogus_to_quarantine[:20]:
        print(f"  - {f.trade_id} {f.ticker:<15s} reason={f.reason} {f.detail}")
    if len(report.bogus_to_quarantine) > 20:
        print(f"  … and {len(report.bogus_to_quarantine) - 20} more")
    print(f"Cancelled canonical rows:        {len(report.cancelled_user_rows)}")
    for f in report.cancelled_user_rows[:20]:
        print(f"  - {f.trade_id} {f.ticker:<15s} status={f.current_value}")
    print(f"India .NS currency fixes:        {len(report.india_currency_fixes)}")
    for f in report.india_currency_fixes[:20]:
        print(f"  - {f.trade_id} {f.ticker:<15s} -> currency=INR  {f.detail}")
    if len(report.india_currency_fixes) > 20:
        print(f"  … and {len(report.india_currency_fixes) - 20} more")
    print(f"India .NS scale anomalies:       {len(report.india_scale_anomalies)}")
    for f in report.india_scale_anomalies[:20]:
        print(f"  - {f.trade_id} {f.ticker:<15s} {f.detail}")
    print(f"Leverage policy violations:      {len(report.leverage_policy_violations)}")
    for f in report.leverage_policy_violations[:20]:
        print(f"  - {f.trade_id} {f.ticker:<15s} {f.detail}")
    print(
        "Reconciliation-eligible rows after repair: "
        f"{len(report.reconciliation_eligible_rows)}"
    )
    if report.warnings:
        print("Warnings:")
        for w in report.warnings:
            print(f"  ! {w}")
    print(
        "[safety] broker_api_called=False ai_execution_count=0 "
        "execution_gate=LOCKED record_keeping_only=True"
    )


def run(
    db_path: Path,
    *,
    apply: bool = False,
    repair_india_scale: bool = False,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> RepairReport:
    """Public entry point used by tests.  Returns the assembled report.

    Function-level guard (Kanté Task 4 / collapsed Task B): the ``apply`` write
    branch calls the shared :func:`operator_permission_guard.assert_guarded_mutation`
    helper (the same enforcement the decorator/context manager use).  A direct
    importer calling ``run(db, apply=True)`` without a guard-validated decision
    raises ``PermissionError`` before any backup/UPDATE.  The dry-run
    (``apply=False``) scan needs none.
    """
    report = _scan(db_path)
    if not apply:
        return report
    _guard.assert_guarded_mutation(
        permission_decision,
        operation_name=OPERATION_NAME,
        operation_class=OPERATION_CLASS,
        expected_role_floor=_guard.OperatorRole.OPERATOR,
        require_dry_run=True,
    )
    if not db_path.exists():
        report.warnings.append("apply_skipped_db_missing")
        return report
    backup = _make_backup(db_path)
    report.backup_path = str(backup)
    conn = sqlite3.connect(str(db_path))
    try:
        n = 0
        n += _apply_quarantine(conn, report.bogus_to_quarantine)
        n += _apply_india_currency(conn, report.india_currency_fixes)
        if repair_india_scale and report.india_scale_anomalies:
            # We never auto-divide.  When the operator opts in we annotate
            # the row's ``notes`` column with a structured marker so the
            # audit trail records that the operator was warned.  No
            # destructive write — broker_api_called/ai_execution_count
            # are not touched.
            cur = conn.cursor()
            for flag in report.india_scale_anomalies:
                cur.execute(
                    "UPDATE manual_trades "
                    "SET notes = COALESCE(notes, '') || ? "
                    "WHERE trade_id = ? "
                    "  AND COALESCE(notes, '') NOT LIKE ?",
                    (
                        f" [REPAIR_FLAG: india_nse_price_below_floor floor={_INDIA_PRICE_FLOOR.get(flag.ticker)} actual={flag.current_value}]",
                        flag.trade_id,
                        "%india_nse_price_below_floor%",
                    ),
                )
                n += cur.rowcount or 0
            conn.commit()
        report.changes_written = n
        report.applied = True
    finally:
        conn.close()
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit / repair Manual Trade Log ↔ Reconciliation pipeline. "
            "Dry-run by default; requires --apply to write."
        ),
    )
    parser.add_argument(
        "--db",
        dest="db",
        default=str(_DEFAULT_DB_PATH),
        help=f"SQLite DB path (default: {_DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the repair (quarantine bogus rows + India currency fix). "
             "Requires MVP_OPERATOR_ROLE=OPERATOR or ADMIN and a recent "
             "dry-run receipt.",
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
    parser.add_argument(
        "--repair-india-scale",
        action="store_true",
        help=(
            "Also annotate India .NS rows whose price is below the sane "
            "floor with a REPAIR_FLAG note.  Off by default — operator "
            "must opt in.  Never alters the recorded price."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON only (machine-readable).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = Path(args.db).expanduser()

    if not args.apply:
        # Dry-run: read-only scan, open to any role.  Record a receipt so a
        # later --apply (by an authorized role) can prove a dry-run happened.
        report = run(db_path, apply=False,
                     repair_india_scale=args.repair_india_scale)
        target_count = (len(report.bogus_to_quarantine)
                        + len(report.india_currency_fixes))
        try:
            receipt = _guard.write_dry_run_receipt(
                OPERATION_NAME, target_count=target_count, db_path=str(db_path))
            print(f"[repair] dry-run receipt written: {receipt.name}")
        except Exception:  # pragma: no cover - receipt is best-effort
            pass
        payload = _serialise(report)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_human(report)
        return 0

    # --apply path: central permission guard (fails closed; audits allow/deny).
    # CLI request/role/receipt boilerplate collapsed into build_apply_decision.
    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(db_path),
            operator_role=args.operator_role)
    except PermissionError as exc:
        print(f"[repair] [DENY] {exc}", file=sys.stderr)
        return 2

    report = run(db_path, apply=True,
                 repair_india_scale=args.repair_india_scale,
                 permission_decision=decision)
    payload = _serialise(report)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
