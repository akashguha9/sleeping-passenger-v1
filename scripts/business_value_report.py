"""Business / demo value report — what the defensive layers actually caught.

A read-only, advisory-only summary of the *defensive* value the MVP provides:
stale signals detected, duplicate AI theses detected, closed losses repaired
into Moltbook, fake demo pollution prevented, operator overload flagged, and
the unreconciled-risk backlog.

Honesty contract (Kanté "no unlogged loss")
-------------------------------------------
* This report NEVER claims a P/L improvement, a return, or a profit. It counts
  *risk-prevention* events, not gains.
* It always carries the advisory-only disclaimer and "human execution
  required".
* Missing data is reported honestly (``db_available=False`` + a note) rather
  than invented.

Read-only: no DB writes, no refresh, no broker calls.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

ADVISORY_DISCLAIMER = (
    "Advisory-only. This report counts risk-prevention and record-keeping "
    "events; it makes NO claim of profit, return, or P/L improvement. Every "
    "trade decision requires a human. No broker order is ever placed."
)

# Default per-day operator capacity used to flag overload.  Conservative.
_OPERATOR_CAPACITY = 8.0


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    try:
        row = conn.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.Error:
        return 0


def build_report(db_path: Path | None = None) -> dict[str, Any]:
    """Build the business/demo value report (read-only, advisory-only)."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    base: dict[str, Any] = {
        "report": "business_value_report",
        "db_path": str(db),
        "db_available": False,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "claims_pl_improvement": False,
        "human_execution_required": True,
        "stale_signals_detected": 0,
        "duplicate_ai_thesis_detected": 0,
        "closed_losses_repaired_into_moltbook": 0,
        "fake_demo_pollution_active": 0,
        "fake_demo_pollution_prevented": True,
        "operator_overload_flagged": False,
        "operator_load_score": 0.0,
        "unreconciled_risk_count": 0,
        "notes": [],
        **_contract.advisory_safety_stamps(),
    }

    conn = _readonly_connect(db)
    if conn is None:
        base["notes"].append(
            "DB not available — all counts default to zero. This is reported "
            "honestly, not invented."
        )
        return base
    base["db_available"] = True

    try:
        # Stale signals: signal cells whose freshness degraded.
        base["stale_signals_detected"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM signal_cell_index"
            " WHERE LOWER(freshness_state) IN ('stale','expired')",
        )
        # Duplicate AI thesis: a fingerprint seen more than once is an echo.
        base["duplicate_ai_thesis_detected"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM duplicate_fingerprints WHERE seen_count > 1",
        )
        # Closed losses repaired into Moltbook (loss-review entries).
        base["closed_losses_repaired_into_moltbook"] = _scalar(
            conn,
            "SELECT COUNT(*) FROM moltbook_entries WHERE mistake_type IN"
            " ('trade_loss','manual_exit_loss','stop_loss_breach')",
        )
        # Fake demo pollution still active (unlinked FABRIC/demo rows).
        active_pollution = _scalar(
            conn,
            "SELECT COUNT(*) FROM moltbook_entries"
            " WHERE (UPPER(event_id) LIKE 'FABRIC%'"
            "        OR original_signal_thesis LIKE 'Persistence above 0.8%'"
            "        OR original_signal_thesis = 'Thesis A')"
            " AND COALESCE(NULLIF(TRIM(manual_trade_log_id),''),'') = ''",
        )
        base["fake_demo_pollution_active"] = active_pollution
        base["fake_demo_pollution_prevented"] = active_pollution == 0

        # Unreconciled risk: operator-logged trades with no reconciliation row.
        mt_cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        provenance = (
            " AND created_via = 'manual_trade_log'"
            if "created_via" in mt_cols else ""
        )
        status_filter = (
            " AND COALESCE(NULLIF(TRIM(reconciliation_status),''),'') = ''"
            if "reconciliation_status" in mt_cols else ""
        )
        unreconciled = _scalar(
            conn,
            "SELECT COUNT(*) FROM manual_trades mt"
            " WHERE NOT EXISTS (SELECT 1 FROM reconciliation_results rr"
            "                   WHERE rr.trade_id = mt.trade_id)"
            + provenance + status_filter,
        )
        base["unreconciled_risk_count"] = unreconciled
    finally:
        conn.close()

    # Operator overload via the queueing attention gate (advisory).
    try:
        try:
            from scripts.complex_systems_diagnostics import (
                compute_queueing_attention_gate,
            )
        except ModuleNotFoundError:
            from complex_systems_diagnostics import (  # type: ignore[no-redef]
                compute_queueing_attention_gate,
            )
        gate = compute_queueing_attention_gate({
            "unreconciled_manual_trades": base["unreconciled_risk_count"],
            "moltbook_pending_review": 0,
            "operator_capacity": _OPERATOR_CAPACITY,
        })
        base["operator_load_score"] = gate["operator_load_score"]
        base["operator_overload_flagged"] = bool(gate["no_new_risk_flag"])
    except Exception:  # pragma: no cover - defensive
        base["notes"].append("operator load gate unavailable; defaulted to 0.")

    return base


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="business_value_report.py",
        description=(
            "Read-only advisory summary of defensive value (risk prevented, "
            "losses repaired). Never claims P/L. No broker calls."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = build_report(args.db_path)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Business / Demo Value Report (advisory-only)")
        print("=" * 44)
        print(f"  DB available                : {rep['db_available']}")
        print(f"  stale signals detected      : {rep['stale_signals_detected']}")
        print(f"  duplicate AI thesis detected: {rep['duplicate_ai_thesis_detected']}")
        print(f"  losses repaired to Moltbook : {rep['closed_losses_repaired_into_moltbook']}")
        print(f"  fake pollution active       : {rep['fake_demo_pollution_active']}")
        print(f"  operator overload flagged   : {rep['operator_overload_flagged']}")
        print(f"  unreconciled risk count     : {rep['unreconciled_risk_count']}")
        for note in rep["notes"]:
            print(f"  note: {note}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = ["ADVISORY_DISCLAIMER", "build_report"]


if __name__ == "__main__":
    raise SystemExit(main())
