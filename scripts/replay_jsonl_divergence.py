#!/usr/bin/env python3
"""H5: guarded JSONL→DB divergence replay for the manual trade journal.

Sprint 1 (F10) made JSONL/DB split-brain *visible* on /health/full;
recovery was still manual forensics.  This tool closes the loop:

* **Report (default, read-only):** diffs the provenance-stamped JSONL
  manual-trade log against the ``manual_trades`` table and classifies
  every divergent entry:
    - ``missing_in_db``  — JSONL row whose trade_id has no DB row (the
      F1-era loss mode; replayable);
    - ``mismatched``     — both sides exist but the canonical fields
      (ticker/side/quantity/price) differ (flagged, NEVER auto-repaired);
    - ``db_only``        — DB row with journal provenance but no JSONL
      line (flagged for forensics only).
* **--apply:** replays ``missing_in_db`` rows through
  :func:`scripts.persistence.insert_manual_trade` — the same canonical
  insert the API path uses, so all Decimal normalisation, NaN refusal,
  and stamp behaviour applies — and writes an ``audit_log`` row per
  replayed insert.  Follows the full guarded-mutation doctrine: OPERATOR+
  role, recent dry-run receipt, ``guarded_mutation`` write boundary, and
  an automatic native-API backup before any write.

Idempotent: replayed rows exist afterwards, so a second ``--apply``
finds no ``missing_in_db`` entries and changes nothing.

Record-keeping repair only — never calls a broker, never grants
execution permission.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import persistence  # noqa: E402
from runtime_common import restrict_file_permissions  # noqa: E402
from backup_db import perform_backup  # noqa: E402

try:
    from scripts import operator_permission_guard as _guard  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_permission_guard as _guard  # type: ignore[no-redef]  # noqa: E402

try:
    from scripts.signal_inbox_api import MANUAL_TRADE_LOG  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from signal_inbox_api import MANUAL_TRADE_LOG  # type: ignore[no-redef]  # noqa: E402

OPERATION_NAME = "replay_jsonl_divergence"
OPERATION_CLASS = _guard.OperationClass.REPAIR_WRITE

JOURNAL_PROVENANCE = "manual_trade_log"

# Fields whose disagreement marks a row MISMATCHED (canonical journal
# identity + money values, compared in Decimal where numeric).
_MATCH_MONEY_FIELDS = ("quantity", "price")
_MATCH_TEXT_FIELDS = ("ticker", "side")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _load_jsonl_rows(jsonl_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not jsonl_path.exists():
        return rows
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(parsed, dict)
                and str(parsed.get("created_via") or "") == JOURNAL_PROVENANCE
                and parsed.get("trade_id")
            ):
                rows.append(parsed)
    return rows


def _load_db_rows(db_path: Path) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        if "created_via" not in cols:
            return {}
        rows = conn.execute(
            "SELECT * FROM manual_trades WHERE COALESCE(created_via,'')=?",
            (JOURNAL_PROVENANCE,),
        ).fetchall()
        return {str(r["trade_id"]): dict(r) for r in rows}
    finally:
        conn.close()


def _rows_match(jsonl_row: dict[str, Any], db_row: dict[str, Any]) -> bool:
    for f in _MATCH_TEXT_FIELDS:
        if str(jsonl_row.get(f) or "").upper() != str(db_row.get(f) or "").upper():
            return False
    for f in _MATCH_MONEY_FIELDS:
        a, b = _dec(jsonl_row.get(f)), _dec(db_row.get(f))
        if a is None or b is None or a != b:
            return False
    return True


def collect_divergence(db_path: Path, jsonl_path: Path) -> dict[str, Any]:
    """Read-only diff of the JSONL journal vs the DB journal."""
    jsonl_rows = _load_jsonl_rows(jsonl_path)
    db_rows = _load_db_rows(db_path)
    jsonl_ids = {str(r["trade_id"]) for r in jsonl_rows}

    missing_in_db = [r for r in jsonl_rows if str(r["trade_id"]) not in db_rows]
    mismatched = [
        {
            "trade_id": str(r["trade_id"]),
            "jsonl": {f: r.get(f) for f in _MATCH_TEXT_FIELDS + _MATCH_MONEY_FIELDS},
            "db": {
                f: db_rows[str(r["trade_id"])].get(f)
                for f in _MATCH_TEXT_FIELDS + _MATCH_MONEY_FIELDS
            },
        }
        for r in jsonl_rows
        if str(r["trade_id"]) in db_rows
        and not _rows_match(r, db_rows[str(r["trade_id"])])
    ]
    db_only = sorted(tid for tid in db_rows if tid not in jsonl_ids)

    return {
        "jsonl_rows": len(jsonl_rows),
        "db_rows": len(db_rows),
        "missing_in_db": missing_in_db,
        "mismatched": mismatched,
        "db_only": db_only,
        "divergent": bool(missing_in_db or mismatched or db_only),
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def _replay_one(db_path: Path, row: dict[str, Any]) -> None:
    """Replay one JSONL row through the CANONICAL event-WAL path + audit it.

    S4-A1: routes through write_journal.append_then_apply_event (the same
    lifecycle the live API uses) so the replayed write gets a durable
    event row; the JSONL intent already exists, so that step is a no-op.
    """
    try:
        from scripts.write_journal import append_then_apply_event
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        from write_journal import append_then_apply_event  # type: ignore

    def _apply() -> None:
        _insert_manual_trade_from_row(db_path, row)

    append_then_apply_event(
        event_type="manual_trade",
        idempotency_key=str(row["trade_id"]),
        payload=row,
        jsonl_append=lambda: None,  # the JSONL row is the replay SOURCE
        apply=_apply,
        db_path=db_path,
    )
    _write_replay_audit(db_path, row)


def _insert_manual_trade_from_row(db_path: Path, row: dict[str, Any]) -> None:
    persistence.insert_manual_trade(
        str(row["trade_id"]),
        str(row.get("event_id") or ""),
        str(row.get("ticker") or ""),
        str(row.get("side") or ""),
        row.get("quantity"),
        row.get("price"),
        str(row.get("executed_at") or ""),
        str(row.get("thesis") or ""),
        str(row.get("notes") or ""),
        str(row.get("logged_by") or "human"),
        db_path=db_path,
        leverage=row.get("leverage", 1),
        invalidation_level=str(row.get("invalidation_level") or ""),
        expected_horizon=str(row.get("expected_horizon") or ""),
        risk_reason=str(row.get("risk_reason") or ""),
        entry_reason=str(row.get("entry_reason") or ""),
        exit_plan=str(row.get("exit_plan") or ""),
        confidence_before=row.get("confidence_before"),
        emotional_state=str(row.get("emotional_state") or ""),
        mistake_tags=str(row.get("mistake_tags") or ""),
        lesson=str(row.get("lesson") or ""),
        trade_mode=str(row.get("trade_mode") or "REAL_MANUAL"),
        created_via=JOURNAL_PROVENANCE,
        currency=str(row.get("currency") or ""),
        ai_model_used=str(row.get("ai_model_used") or ""),
    )


def _write_replay_audit(db_path: Path, row: dict[str, Any]) -> None:
    # F13-style audit trail for the replay itself: the "old state" is the
    # JSONL source the row was reconstructed from.
    conn = persistence._get_conn(db_path)
    try:
        persistence._write_audit_row(
            conn,
            "manual_trades",
            str(row["trade_id"]),
            "REPLAY_INSERT",
            {"source": "jsonl_replay", "jsonl_row": row},
        )
        conn.commit()
    finally:
        conn.close()


@_guard.guarded_mutation(
    operation_name=OPERATION_NAME,
    operation_class=OPERATION_CLASS,
    expected_role_floor=_guard.OperatorRole.OPERATOR,
    require_dry_run=True,
)
def apply_replay(
    db_path: Path,
    missing_rows: list[dict[str, Any]],
    *,
    permission_decision: "_guard.PermissionDecision | None" = None,
) -> dict[str, Any]:
    """Replay missing JSONL rows into the DB (guarded write boundary).

    Backup first (refuses to write without one); only ``missing_in_db``
    entries are replayed — mismatched/db_only rows are forensic flags
    that a human must resolve.
    """
    backup = perform_backup(
        db_path, db_path.parent / "backups", label="pre-jsonl-replay"
    )
    if not backup.get("ok"):
        return {
            "applied": 0,
            "error": f"refusing to write without a backup: {backup.get('error')}",
        }
    replayed: list[str] = []
    for row in missing_rows:
        _replay_one(db_path, row)
        replayed.append(str(row["trade_id"]))
    return {
        "applied": len(replayed),
        "replayed_trade_ids": replayed,
        "backup_path": backup.get("backup_path"),
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", type=Path, default=persistence.DB_PATH)
    parser.add_argument("--jsonl", type=Path, default=MANUAL_TRADE_LOG)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Replay missing-in-db rows (OPERATOR/ADMIN + recent dry-run "
        "receipt + automatic backup). Default: report only.",
    )
    parser.add_argument("--operator-role", default=None)
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"[replay_jsonl_divergence] DB not found: {args.db}")
        return 2

    report = collect_divergence(args.db, args.jsonl)
    report["generated_at"] = _utc_stamp()
    report_dir = args.db.parent / "backups"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"jsonl_divergence_report_{_utc_stamp()}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    restrict_file_permissions(report_path)

    print(
        f"[replay_jsonl_divergence] jsonl={report['jsonl_rows']} "
        f"db={report['db_rows']} missing_in_db={len(report['missing_in_db'])} "
        f"mismatched={len(report['mismatched'])} db_only={len(report['db_only'])}"
    )
    print(f"[replay_jsonl_divergence] report: {report_path}")

    if not report["missing_in_db"]:
        if report["mismatched"] or report["db_only"]:
            print(
                "[replay_jsonl_divergence] divergence present but nothing is "
                "auto-replayable (mismatched/db_only need human review)."
            )
        return 0

    if not args.apply:
        try:
            receipt = _guard.write_dry_run_receipt(
                OPERATION_NAME,
                target_count=len(report["missing_in_db"]),
                db_path=str(args.db),
            )
            print(f"[replay_jsonl_divergence] dry-run receipt: {receipt.name}")
        except Exception as exc:  # pragma: no cover - receipt is best-effort
            print(
                f"[replay_jsonl_divergence] WARNING: receipt not written "
                f"({type(exc).__name__}); --apply will be refused"
            )
        print("[replay_jsonl_divergence] DRY-RUN — nothing replayed. Use --apply.")
        return 0

    try:
        decision = _guard.build_apply_decision(
            OPERATION_NAME, OPERATION_CLASS, str(args.db),
            operator_role=args.operator_role,
        )
    except PermissionError as exc:
        print(f"[replay_jsonl_divergence] [DENY] {exc}", file=sys.stderr)
        return 2
    try:
        result = apply_replay(
            args.db, report["missing_in_db"], permission_decision=decision
        )
    except PermissionError as exc:  # defence-in-depth boundary refusal
        print(f"[replay_jsonl_divergence] [DENY] {exc}", file=sys.stderr)
        return 2
    if result.get("error"):
        print(f"[replay_jsonl_divergence] REFUSED: {result['error']}")
        return 2
    print(
        f"[replay_jsonl_divergence] replayed {result['applied']} row(s); "
        f"backup at {result['backup_path']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
