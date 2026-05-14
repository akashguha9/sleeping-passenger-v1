"""
Local reconciliation queue — surfaces unreconciled manual trades.

Purpose
-------
A manual trade that is never reconciled does not produce a learning event.
The self-test report counts unreconciled trades; this helper turns that
count into an inspectable *queue* the operator can iterate through.

Read-only.  No DB writes.  No broker calls.  No execution permission.

Definition of "unreconciled"
----------------------------
A row in ``manual_trades`` is unreconciled if no row exists in
``reconciliation_results`` with the same ``trade_id``.

Output shape
------------
Per item: the trade fields plus journal-quality metadata (completeness
score, learning-ready flag, missing fields) plus ``age_days`` since the
trade's ``executed_at``.

Summary: unreconciled_count, oldest_unreconciled_age_days,
average_journal_completeness, learning_ready_count, missing_field
distribution, plus by_ticker / by_emotional_state / by_expected_horizon
break-downs.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

Usage
-----
    python scripts/reconciliation_queue.py
    python scripts/reconciliation_queue.py --json
    python scripts/reconciliation_queue.py --limit 50 --json
    python scripts/reconciliation_queue.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
from pathlib import Path
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

ADVISORY_DISCLAIMER = (
    "Reconciliation queue is advisory-only. Listing a trade here does not "
    "place, modify, or cancel any broker order. Reconciliation is operator-"
    "entered record keeping."
)

OPERATOR_ACTION = (
    "Reconcile each listed trade by recording actual fill price, quantity, "
    "outcome status, outcome quality, process error (if any), and a one-line "
    "lesson. Do this within 1-3 trading days of the trade to keep learning value high."
)

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


_JOURNAL_FIELDS: tuple[str, ...] = (
    "invalidation_level",
    "expected_horizon",
    "risk_reason",
    "entry_reason",
    "exit_plan",
    "confidence_before",
    "emotional_state",
    "mistake_tags",
    "lesson",
)


def _default_db_path() -> Path:
    try:
        try:
            from scripts.persistence import DB_PATH  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from persistence import DB_PATH  # type: ignore[no-redef]
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _columns_present(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {r[1] for r in rows}


def _parse_iso8601(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _age_days(executed_at: Any, now: _dt.datetime) -> float | None:
    dt = _parse_iso8601(executed_at)
    if dt is None:
        return None
    delta = now - dt
    return round(delta.total_seconds() / 86400.0, 4)


def _empty_summary() -> dict[str, Any]:
    return {
        "unreconciled_count": 0,
        "oldest_unreconciled_age_days": None,
        "average_journal_completeness": 0.0,
        "average_learning_readiness": 0.0,
        "learning_ready_count": 0,
        "missing_field_distribution": {},
        "by_ticker": {},
        "by_emotional_state": {},
        "by_expected_horizon": {},
    }


def _build_journal_entry(row: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    """Shape one trade row into the dict expected by score_journal_entry()."""
    return {
        "signal_id": str(row.get("event_id") or ""),
        "thesis": str(row.get("thesis") or ""),
        "invalidation_level": str(row.get("invalidation_level") or ""),
        "expected_horizon": str(row.get("expected_horizon") or ""),
        "position_size": float(row.get("quantity") or 0.0),
        "risk_reason": str(row.get("risk_reason") or ""),
        "entry_reason": str(row.get("entry_reason") or ""),
        "exit_plan": str(row.get("exit_plan") or ""),
        "confidence_before": row.get("confidence_before"),
        "emotional_state": str(row.get("emotional_state") or ""),
        "post_trade_outcome": outcome.get("outcome_notes") or "",
        "reconciliation_status": outcome.get("outcome_status") or "",
        "mistake_tags": [
            t.strip()
            for t in str(row.get("mistake_tags") or "").split(",")
            if t.strip()
        ],
        "lesson": str(row.get("lesson") or ""),
    }


def build_queue(
    db_path: Path | None = None,
    *,
    limit: int | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Return the unreconciled-trade queue + summary, plus safety stamps.

    Parameters
    ----------
    db_path : Path | None
        Defaults to the persistence module's DB_PATH.
    limit : int | None
        Cap the number of items returned. ``None`` returns all.  The
        summary is always computed across the full unreconciled set
        regardless of limit, so the operator never gets a misleadingly
        small ``oldest_unreconciled_age_days``.
    now : datetime | None
        Override the current time for deterministic tests.

    Read-only.  Never raises on a missing/unopenable DB; instead returns
    an empty queue and a ``warnings`` list explaining why.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    path = Path(db_path) if db_path else _default_db_path()
    warnings: list[str] = []
    base: dict[str, Any] = {
        "report": "reconciliation_queue",
        "db_path": str(path),
        "db_available": False,
        "items": [],
        "summary": _empty_summary(),
        "warnings": warnings,
        "operator_action": OPERATOR_ACTION,
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    base.update(_SAFETY_STAMPS)

    if not path.exists():
        warnings.append("db_missing")
        return base

    conn = _readonly_connect(path)
    if conn is None:
        warnings.append("db_open_failed")
        return base

    try:
        if not _table_exists(conn, "manual_trades"):
            warnings.append("manual_trades_table_missing")
            return base
        if not _table_exists(conn, "reconciliation_results"):
            warnings.append("reconciliation_results_table_missing")
            # Continue anyway — every trade is unreconciled in this case.

        cols = _columns_present(conn, "manual_trades")
        select_cols = [c for c in (
            "trade_id", "event_id", "ticker", "side", "quantity", "price",
            "executed_at", "thesis", *_JOURNAL_FIELDS,
        ) if c in cols]
        if "trade_id" not in select_cols:
            warnings.append("manual_trades_missing_trade_id_column")
            return base

        select_clause = ", ".join(select_cols)
        try:
            rows = conn.execute(
                f"SELECT {select_clause} FROM manual_trades mt"  # noqa: S608
                " WHERE NOT EXISTS ("
                "   SELECT 1 FROM reconciliation_results rr"
                "   WHERE rr.trade_id = mt.trade_id"
                " ) ORDER BY mt.executed_at ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            warnings.append(f"query_failed:{type(exc).__name__}")
            return base

        try:
            from scripts.self_test_journal_quality import (  # type: ignore[import-not-found]
                score_journal_entry,
            )
        except ModuleNotFoundError:
            try:
                from self_test_journal_quality import (  # type: ignore[no-redef]
                    score_journal_entry,
                )
            except ImportError:
                score_journal_entry = None  # type: ignore[assignment]
                warnings.append("journal_quality_helper_unavailable")

        base["db_available"] = True

        items: list[dict[str, Any]] = []
        for row in rows:
            row_dict = {k: row[k] for k in row.keys()}
            outcome = {"outcome_status": "", "outcome_notes": ""}
            entry = _build_journal_entry(row_dict, outcome)
            if score_journal_entry is not None:
                quality = score_journal_entry(entry)
                completeness = float(quality.get("journal_completeness_score") or 0.0)
                readiness = float(quality.get("learning_readiness_score") or 0.0)
                learning_ready = bool(quality.get("learning_ready"))
                missing = list(quality.get("missing_fields") or [])
            else:
                completeness = 0.0
                readiness = 0.0
                learning_ready = False
                missing = list(_JOURNAL_FIELDS)

            item: dict[str, Any] = {
                "trade_id": str(row_dict.get("trade_id") or ""),
                "event_id": str(row_dict.get("event_id") or ""),
                "ticker": str(row_dict.get("ticker") or ""),
                "side": str(row_dict.get("side") or ""),
                "quantity": float(row_dict.get("quantity") or 0.0),
                "price": float(row_dict.get("price") or 0.0),
                "executed_at": str(row_dict.get("executed_at") or ""),
                "age_days": _age_days(row_dict.get("executed_at"), now),
                "thesis": str(row_dict.get("thesis") or ""),
                "invalidation_level": str(row_dict.get("invalidation_level") or ""),
                "expected_horizon": str(row_dict.get("expected_horizon") or ""),
                "risk_reason": str(row_dict.get("risk_reason") or ""),
                "entry_reason": str(row_dict.get("entry_reason") or ""),
                "exit_plan": str(row_dict.get("exit_plan") or ""),
                "confidence_before": row_dict.get("confidence_before"),
                "emotional_state": str(row_dict.get("emotional_state") or ""),
                "mistake_tags": str(row_dict.get("mistake_tags") or ""),
                "lesson": str(row_dict.get("lesson") or ""),
                "journal_completeness_score": round(completeness, 6),
                "learning_readiness_score": round(readiness, 6),
                "learning_ready": learning_ready,
                "missing_journal_fields": missing,
                "needs_reconciliation": True,
            }
            item.update(_SAFETY_STAMPS)
            items.append(item)

        # Build summary over the FULL unreconciled set, not the limited view.
        oldest_age: float | None = None
        completeness_sum = 0.0
        readiness_sum = 0.0
        learning_ready_count = 0
        missing_dist: dict[str, int] = {}
        by_ticker: dict[str, int] = {}
        by_emotional_state: dict[str, int] = {}
        by_expected_horizon: dict[str, int] = {}

        for it in items:
            age = it.get("age_days")
            if isinstance(age, (int, float)):
                if oldest_age is None or age > oldest_age:
                    oldest_age = float(age)
            completeness_sum += float(it.get("journal_completeness_score") or 0.0)
            readiness_sum += float(it.get("learning_readiness_score") or 0.0)
            if it.get("learning_ready"):
                learning_ready_count += 1
            for field in it.get("missing_journal_fields") or []:
                missing_dist[field] = missing_dist.get(field, 0) + 1
            tkr = it["ticker"] or "UNKNOWN"
            by_ticker[tkr] = by_ticker.get(tkr, 0) + 1
            em = it["emotional_state"] or "UNRECORDED"
            by_emotional_state[em] = by_emotional_state.get(em, 0) + 1
            hz = it["expected_horizon"] or "UNRECORDED"
            by_expected_horizon[hz] = by_expected_horizon.get(hz, 0) + 1

        n = len(items)
        avg_completeness = (completeness_sum / n) if n else 0.0
        avg_readiness = (readiness_sum / n) if n else 0.0

        summary = {
            "unreconciled_count": n,
            "oldest_unreconciled_age_days": (
                round(oldest_age, 4) if oldest_age is not None else None
            ),
            "average_journal_completeness": round(avg_completeness, 6),
            "average_learning_readiness": round(avg_readiness, 6),
            "learning_ready_count": learning_ready_count,
            "missing_field_distribution": missing_dist,
            "by_ticker": by_ticker,
            "by_emotional_state": by_emotional_state,
            "by_expected_horizon": by_expected_horizon,
        }
        base["summary"] = summary

        if isinstance(limit, int) and limit >= 0:
            base["items"] = items[:limit]
            if limit < n:
                base["truncated"] = True
                base["truncated_to"] = limit
        else:
            base["items"] = items

        return base
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Reconciliation Queue")
    lines.append("=" * 24)
    summary = payload["summary"]
    lines.append(f"Unreconciled: {summary['unreconciled_count']}")
    age = summary["oldest_unreconciled_age_days"]
    lines.append(f"Oldest age days: {age if age is not None else '-'}")
    lines.append(
        f"Avg journal completeness: {summary['average_journal_completeness']:.3f}"
    )
    lines.append(
        f"Avg learning readiness:  {summary['average_learning_readiness']:.3f}"
    )
    lines.append(f"Learning-ready: {summary['learning_ready_count']}")
    if payload.get("warnings"):
        lines.append("Warnings: " + ", ".join(payload["warnings"]))
    lines.append("")
    lines.append("Operator action:")
    lines.append(f"  {payload['operator_action']}")
    lines.append("")
    lines.append(payload["advisory_disclaimer"])
    items = payload["items"]
    if items:
        lines.append("")
        lines.append("Items:")
        for it in items:
            lines.append(
                f"  - {it['trade_id']:>14} {it['ticker']:>6} {it['side']:<4} "
                f"qty={it['quantity']} age={it['age_days']} "
                f"complete={it['journal_completeness_score']:.2f} "
                f"ready={it['learning_ready']}"
            )
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reconciliation_queue.py",
        description=(
            "Read-only local queue of unreconciled manual trades. Never "
            "places, modifies, or cancels broker orders."
        ),
    )
    p.add_argument("--db-path", type=str, default=None,
                   help="Path to runtime/mvp_local.db (default: persistence module).")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of items in the listing (summary still global).")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    payload = build_queue(db_path, limit=args.limit)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2, default=str))
    else:
        print(_render_text(payload))
    return 0 if payload.get("db_available", False) else 1


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "ADVISORY_DISCLAIMER",
    "OPERATOR_ACTION",
    "build_queue",
]


if __name__ == "__main__":
    raise SystemExit(main())
