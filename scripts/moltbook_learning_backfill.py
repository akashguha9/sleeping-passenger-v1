"""
Backfill Moltbook learning entries for already-reconciled trades.

Scans ``reconciliation_results`` + ``manual_trades`` and creates the
Moltbook learning entry that *would* have been written if the new
reconciliation → Moltbook learning bridge had existed when the
reconciliation was first saved.  Safe to re-run: idempotency-keyed on
``trade_id|event_type|exit_price|exit_quantity`` (the same key the live
bridge uses), so a row that already has its Moltbook entry is updated
in place, not duplicated.

What gets backfilled
--------------------
- STOP_HIT / STOPPED_OUT  →  event_type=STOP_LOSS_HIT
- PARTIAL_TP (filled)     →  event_type=PARTIAL_TP_HIT
- PARTIAL_TP (logged)     →  event_type=PARTIAL_TP_LOGGED
- CLOSED_WIN / CLOSED_LOSS / BREAKEVEN / MANUAL_EXIT / TIMEOUT_EXIT
                          →  event_type=CLOSED

The XOM and CVX stop-hits, ANET partial TP, ASML partial-TP-logged, GLD
manual-exit close, and TSM stop-hit that the operator called out land
in Moltbook through the same code path as any other reconciliation.

Safety
------
- No broker calls; no order placement; no executions.
- ``--write`` is required to mutate; default mode is dry-run.
- Reads ``manual_trades`` and ``reconciliation_results`` read-only; only
  the Moltbook insert/update happens through the persistence module.

Usage
-----
    python scripts/moltbook_learning_backfill.py            # dry-run
    python scripts/moltbook_learning_backfill.py --write    # apply
    python scripts/moltbook_learning_backfill.py --tickers XOM,CVX
    python scripts/moltbook_learning_backfill.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

try:
    import scripts.persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]

try:
    import scripts.moltbook_learning_bridge as _learning_bridge
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import moltbook_learning_bridge as _learning_bridge  # type: ignore[no-redef]


_EXTRAS_RE = re.compile(r"\[reconciliation_extras=(\{.*\})\]", re.DOTALL)

# Per the task: these tickers + states must land in the backfill.  The
# scan is broader — any row whose post_trade_outcome (or legacy
# outcome_status) maps to STOP_HIT / PARTIAL_TP_HIT / PARTIAL_TP_LOGGED /
# CLOSED is included.  The named list is just a sanity-check we report.
TARGETED_TICKERS: dict[str, str] = {
    "XOM": "STOP_HIT",
    "CVX": "STOP_HIT",
    "ANET": "PARTIAL_TP_HIT",
    "ASML": "PARTIAL_TP_LOGGED",
    "GLD": "CLOSED",
    "TSM": "CLOSED",
}


def _default_db_path() -> Path:
    try:
        return Path(_persistence.DB_PATH)
    except Exception:  # pragma: no cover
        return Path(__file__).resolve().parents[1] / "runtime" / "mvp_local.db"


def _parse_extras(outcome_notes: str) -> dict[str, Any]:
    if not outcome_notes:
        return {}
    m = _EXTRAS_RE.search(outcome_notes)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(1))
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _read_pairs(db_path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    conn = _readonly_connect(db_path)
    if conn is None:
        return []
    try:
        rec_rows = conn.execute(
            "SELECT * FROM reconciliation_results ORDER BY reconciled_at ASC"
        ).fetchall()
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for rec in rec_rows:
            rec_d = dict(rec)
            trade = conn.execute(
                "SELECT * FROM manual_trades WHERE trade_id=?",
                (rec_d.get("trade_id"),),
            ).fetchone()
            trade_d = dict(trade) if trade else {
                "trade_id": rec_d.get("trade_id"),
                "event_id": rec_d.get("event_id"),
                "ticker": "",
                "side": "",
                "thesis": "",
                "price": 0.0,
                "quantity": 0.0,
            }
            pairs.append((trade_d, rec_d))
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return pairs


def _derive_event_type(
    extras: dict[str, Any],
    rec: dict[str, Any],
) -> str:
    """Reconstruct the event_type the live bridge would have produced."""
    pto = str(extras.get("post_trade_outcome") or "").strip().upper()
    if not pto:
        # Fall back to legacy outcome_status (LOSS / WIN / BREAKEVEN / ...).
        legacy = str(rec.get("outcome_status") or "").strip().upper()
        if legacy == "LOSS":
            pto = "CLOSED_LOSS"
        elif legacy in {"WIN", "PROFIT"}:
            pto = "CLOSED_WIN"
        elif legacy == "BREAKEVEN":
            pto = "BREAKEVEN"
    return _learning_bridge.classify_event_type(
        post_trade_outcome=pto,
        stop_loss_hit=bool(extras.get("stop_loss_hit")),
        actual_exit_price=_coerce_float(
            extras.get("actual_exit_price")
            or extras.get("fill_price")
            or rec.get("actual_fill_price")
        ),
        exit_quantity=_coerce_float(
            extras.get("exit_quantity") or rec.get("actual_quantity")
        ),
        partial_take_profit_price=_coerce_float(extras.get("partial_take_profit_price")),
        partial_take_profit_quantity=_coerce_float(extras.get("partial_take_profit_quantity")),
    )


def backfill(
    db_path: Path | None = None,
    *,
    write: bool = False,
    only_tickers: list[str] | None = None,
    include_demo_fixtures: bool = False,
) -> dict[str, Any]:
    """Backfill missing Moltbook learning entries.

    Returns a report counting candidates / created / updated / skipped
    and listing each affected (trade_id, event_type) tuple.  Backfill is
    dry-run by default (``write=False``); pass ``write=True`` to apply.
    Test/demo fixtures (thesis in {"test", "t", "demo", "probe", ...})
    are skipped unless ``include_demo_fixtures=True``.
    """
    path = Path(db_path) if db_path is not None else _default_db_path()
    report: dict[str, Any] = {
        "operation": "moltbook_learning_backfill",
        "db_path": str(path),
        "db_exists": path.exists(),
        "applied": bool(write),
        "include_demo_fixtures": bool(include_demo_fixtures),
        "scanned_count": 0,
        "eligible_count": 0,
        "candidates": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_not_learning_worthy": 0,
        "skipped_open_trade_count": 0,
        "skipped_signal_only_count": 0,
        "skipped_test_demo_count": 0,
        "skipped_missing_exit_count": 0,
        "skipped_missing_trade_identity_count": 0,
        "skipped_unsupported_event_count": 0,
        "would_create_count": 0,
        "skipped_existing_count": 0,
        "duplicate_candidates_count": 0,
        "test_or_demo_skipped_count": 0,
        "created_count": 0,
        "updated_existing_count": 0,
        "targeted_ticker_status": {},
        "entries": [],
        "advisory_status": "ADVISORY_ONLY",
        "execution_mode": "HUMAN_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "human_review_required": True,
        "generated_at": utc_timestamp(),
    }
    if not path.exists():
        report["warning"] = "db_missing"
        return report

    only_set: set[str] | None = None
    if only_tickers:
        only_set = {t.strip().upper() for t in only_tickers if t.strip()}

    # Pre-compute existing idempotency keys so we can report
    # skipped_existing_count without doing a redundant insert attempt.
    existing_keys: set[str] = set()
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT DISTINCT idempotency_key FROM moltbook_entries WHERE idempotency_key <> ''"
        ).fetchall():
            existing_keys.add(row[0])
        conn.close()
    except sqlite3.Error:
        pass

    pairs = _read_pairs(path)
    for trade, rec in pairs:
        report["scanned_count"] += 1
        ticker = str(trade.get("ticker") or "").upper()
        if only_set is not None and ticker not in only_set:
            continue
        extras = _parse_extras(str(rec.get("outcome_notes") or ""))
        event_type = _derive_event_type(extras, rec)
        if not event_type:
            report["skipped_not_learning_worthy"] += 1
            continue

        entry_price = _coerce_float(extras.get("entry_price")) or _coerce_float(trade.get("price"))
        exit_price = (
            _coerce_float(extras.get("actual_exit_price"))
            or _coerce_float(extras.get("fill_price"))
            or _coerce_float(rec.get("actual_fill_price"))
        )
        exit_quantity = _coerce_float(extras.get("exit_quantity")) or _coerce_float(
            rec.get("actual_quantity")
        )
        entry_quantity = _coerce_float(extras.get("entry_quantity")) or _coerce_float(
            trade.get("quantity")
        )
        realized_pl = _coerce_float(extras.get("realized_pnl")) or _coerce_float(
            rec.get("pnl_estimate")
        )

        # Eligibility gate (single source of truth).  When
        # --include-demo-fixtures is set we strip the thesis from the
        # eligibility candidate so a test/demo thesis no longer triggers
        # SKIP_TEST_DEMO_FIXTURE — the operator has explicitly opted in.
        candidate = {
            "event_type": event_type,
            "status": str(extras.get("post_trade_outcome") or "").strip().upper(),
            "symbol": ticker,
            "trade_id": trade.get("trade_id"),
            "exit_price": exit_price,
            "realized_pl": realized_pl,
            "exit_reason": str(extras.get("exit_reason") or ""),
            "stop_loss_hit": bool(extras.get("stop_loss_hit")),
            "thesis": "" if include_demo_fixtures else str(trade.get("thesis") or ""),
        }
        verdict = _learning_bridge.is_moltbook_eligible_reconciliation_event(candidate)
        if not verdict["eligible"]:
            reason = verdict["reason"]
            if reason == _learning_bridge.SKIP_OPEN_TRADE:
                report["skipped_open_trade_count"] += 1
            elif reason == _learning_bridge.SKIP_SIGNAL_ONLY:
                report["skipped_signal_only_count"] += 1
            elif reason == _learning_bridge.SKIP_MISSING_TRADE_IDENTITY:
                report["skipped_missing_trade_identity_count"] += 1
            elif reason == _learning_bridge.SKIP_MISSING_EXIT_OR_REALIZED_PL:
                report["skipped_missing_exit_count"] += 1
            elif reason == _learning_bridge.SKIP_UNSUPPORTED_EVENT_TYPE:
                report["skipped_unsupported_event_count"] += 1
            elif reason == _learning_bridge.SKIP_TEST_DEMO_FIXTURE:
                report["skipped_test_demo_count"] += 1
                report["test_or_demo_skipped_count"] += 1
            continue

        # Apply the eligibility-normalized event type so backfill writes
        # the same vocabulary the live bridge would.
        event_type = verdict["normalized_event_type"] or event_type
        report["eligible_count"] += 1
        report["candidates"] += 1

        if not write:
            # Dry-run: build the idempotency key + would-be event_type and
            # report without touching SQLite.
            idem = _learning_bridge.compute_idempotency_key(
                trade_id=str(trade.get("trade_id") or ""),
                event_type=event_type,
                exit_price=exit_price,
                exit_quantity=exit_quantity,
            )
            if idem in existing_keys:
                report["skipped_existing_count"] += 1
                report["duplicate_candidates_count"] += 1
                status_label = "exists"
            else:
                report["would_create_count"] += 1
                status_label = "would_write"
            report["entries"].append({
                "status": status_label,
                "trade_id": trade.get("trade_id"),
                "ticker": ticker,
                "event_type": event_type,
                "idempotency_key": idem,
            })
            if ticker in TARGETED_TICKERS:
                report["targeted_ticker_status"][ticker] = status_label
            continue

        result = _learning_bridge.record_reconciliation_learning(
            trade_id=str(trade.get("trade_id") or ""),
            event_id=str(trade.get("event_id") or rec.get("event_id") or ""),
            ticker=ticker,
            side=str(trade.get("side") or "").upper(),
            post_trade_outcome=str(extras.get("post_trade_outcome") or ""),
            reconciliation_status=str(extras.get("reconciliation_status") or ""),
            actual_exit_price=exit_price,
            exit_quantity=exit_quantity,
            entry_price=entry_price,
            entry_quantity=entry_quantity,
            stop_loss_price=_coerce_float(extras.get("stop_loss_price")),
            stop_loss_hit=bool(extras.get("stop_loss_hit")),
            partial_take_profit_price=_coerce_float(extras.get("partial_take_profit_price")),
            partial_take_profit_quantity=_coerce_float(
                extras.get("partial_take_profit_quantity")
            ),
            runner_quantity=_coerce_float(extras.get("runner_quantity")),
            take_profit_plan=str(extras.get("take_profit_plan") or ""),
            realized_pl=realized_pl,
            outcome_quality=str(
                extras.get("outcome_quality") or rec.get("outcome_quality") or ""
            ),
            mistake_tags=extras.get("mistake_tags") or rec.get("mistake_tags") or "",
            lesson=str(
                extras.get("lesson_takeaway")
                or rec.get("lesson")
                or ""
            ),
            notes=str(extras.get("notes") or ""),
            exit_reason=str(extras.get("exit_reason") or ""),
            thesis=str(trade.get("thesis") or ""),
            invalidation_level=str(extras.get("invalidation_level") or ""),
            explicit_event_type=event_type,
            db_path=path,
            admit_demo_fixture=include_demo_fixtures,
        )
        result_status = result.get("status")
        if result_status == "created":
            report["created"] += 1
            report["created_count"] += 1
        elif result_status == "updated":
            report["updated"] += 1
            report["updated_existing_count"] += 1
        else:
            report["skipped"] += 1
        report["entries"].append({
            "status": result_status,
            "trade_id": trade.get("trade_id"),
            "ticker": ticker,
            "event_type": result.get("event_type") or event_type,
            "outcome_quality": result.get("outcome_quality"),
            "learning_direction": result.get("learning_direction"),
            "entry_id": result.get("entry_id"),
            "idempotency_key": result.get("idempotency_key"),
        })
        if ticker in TARGETED_TICKERS:
            report["targeted_ticker_status"][ticker] = result_status

    # Report which named tickers we never saw — useful for the operator
    # to spot if a reconciliation row is missing or filtered out.
    for ticker in TARGETED_TICKERS:
        report["targeted_ticker_status"].setdefault(ticker, "not_found")
    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moltbook_learning_backfill.py",
        description=(
            "Backfill Moltbook learning entries for already-reconciled "
            "trades (idempotent). Never places, modifies, or cancels "
            "broker orders."
        ),
    )
    p.add_argument("--db-path", type=str, default=None)
    p.add_argument("--write", action="store_true",
                   help="Apply writes (default: dry-run).")
    p.add_argument(
        "--tickers", type=str, default=None,
        help="Comma-separated subset of tickers to scan (e.g. XOM,CVX).",
    )
    p.add_argument(
        "--include-demo-fixtures", action="store_true",
        help="Include test/demo theses (thesis in {test, t, demo, probe, ...}).",
    )
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    only = args.tickers.split(",") if args.tickers else None
    report = backfill(
        db_path,
        write=args.write,
        only_tickers=only,
        include_demo_fixtures=args.include_demo_fixtures,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        mode = "WRITE" if report["applied"] else "DRY-RUN"
        print(f"Moltbook learning backfill [{mode}]")
        print(f"  db_path     : {report['db_path']}")
        print(f"  candidates  : {report['candidates']}")
        print(f"  created     : {report['created']}")
        print(f"  updated     : {report['updated']}")
        print(f"  skipped     : {report['skipped']}")
        print(f"  not_worthy  : {report['skipped_not_learning_worthy']}")
        for tkr, status in sorted(report["targeted_ticker_status"].items()):
            print(f"    {tkr:>6}: {status}")
        for entry in report["entries"]:
            print(
                f"    - {entry.get('ticker',''):>6} "
                f"{entry.get('event_type',''):<18} "
                f"{entry.get('status',''):<12} "
                f"trade={entry.get('trade_id')}"
            )
    return 0


__all__ = ["backfill", "TARGETED_TICKERS"]


if __name__ == "__main__":
    raise SystemExit(main())
