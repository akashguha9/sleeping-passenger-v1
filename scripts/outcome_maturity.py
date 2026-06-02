"""Sheet-row outcome maturity — do not judge a young trade as a model failure.

This is the *trade-log* maturity surface: given a typed trade-log row and a
report date, it says whether the row is old/closed enough that its outcome may
be scored, or whether it is still inside its observation horizon and must NOT
count for or against the model yet.

It is deliberately distinct from ``scripts/forward_outcome_maturity_scanner.py``,
which classifies *decision-probability DB snapshots* (DUE_FORWARD / ATTACHED /
…).  This module classifies *manual trade-log rows* parsed from the operator's
Google Sheet, using a trading-day (weekday-only) age.

Contract — pure module
----------------------
No DB, no network, no broker calls, no AI execution.  Deterministic given the
input rows and report date.  Never emits a BUY/SELL/EXECUTE instruction.

Maturity states (a partition)::

    CLOSED_SCORE_ELIGIBLE       trade is closed / stop-closed / synced-closed
    EVENT_SCORE_ELIGIBLE        a TP1/TP2/stop event fired (partial or full)
    MATURE_OPEN_SCORE_ELIGIBLE  still open but age >= HORIZON_TRADING_DAYS
    PENDING_HORIZON             open and younger than the horizon -> not judged
    UNKNOWN                     entry date missing / unparseable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

HORIZON_TRADING_DAYS = 5

MATURITY_CLOSED = "CLOSED_SCORE_ELIGIBLE"
MATURITY_EVENT = "EVENT_SCORE_ELIGIBLE"
MATURITY_MATURE_OPEN = "MATURE_OPEN_SCORE_ELIGIBLE"
MATURITY_PENDING = "PENDING_HORIZON"
MATURITY_UNKNOWN = "UNKNOWN"

SCORE_ELIGIBLE_STATES: frozenset[str] = frozenset(
    {MATURITY_CLOSED, MATURITY_EVENT, MATURITY_MATURE_OPEN}
)

BUCKET_TOO_EARLY = "TOO_EARLY"
BUCKET_FORMING = "FORMING"
BUCKET_FIRST_HORIZON = "FIRST_HORIZON"
BUCKET_EXTENDED_HORIZON = "EXTENDED_HORIZON"


# --------------------------------------------------------------------------- #
# Trading-day age (weekday-only approximation).
# --------------------------------------------------------------------------- #
def trading_days_between(start: date, end: date) -> int:
    """Count weekdays (Mon-Fri) in the half-open interval ``(start, end]``.

    Same-day -> 0.  A Friday entry observed the following Monday -> 1.  This is
    a deterministic calendar approximation (it does not consult an exchange
    holiday calendar — see the module docstring / docs).
    """
    if end <= start:
        return 0
    days = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:  # Mon..Fri
            days += 1
        cursor += timedelta(days=1)
    return days


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().upper())


def _attr(row: Any, name: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _is_closed(trade_state: str, exit_stage: str) -> bool:
    ts, es = _norm(trade_state), _norm(exit_stage)
    return ts in {"CLOSED", "STOP_CLOSED", "CLOSE_TRADE_SYNCED"} or "CLOSED" in es


def _is_event(trade_state: str, exit_stage: str) -> bool:
    ts, es = _norm(trade_state), _norm(exit_stage)
    tokens = (ts, es)
    return any(
        marker in joined
        for joined in tokens
        for marker in ("PARTIAL_TP", "TP1", "TP2", "STOP")
    )


def horizon_bucket(age: int) -> str:
    if age < 2:
        return BUCKET_TOO_EARLY
    if age < HORIZON_TRADING_DAYS:
        return BUCKET_FORMING
    if age < 2 * HORIZON_TRADING_DAYS:
        return BUCKET_FIRST_HORIZON
    return BUCKET_EXTENDED_HORIZON


def classify_maturity(row: Any, report_date: date) -> dict[str, Any]:
    """Classify one trade-log row's maturity relative to ``report_date``."""
    trade_state = _attr(row, "trade_state", "")
    exit_stage = _attr(row, "exit_stage_v2", "")
    entry_date = _attr(row, "date", None)

    closed = _is_closed(trade_state, exit_stage)
    event = _is_event(trade_state, exit_stage)

    age: int | None
    if isinstance(entry_date, date):
        age = trading_days_between(entry_date, report_date)
    else:
        age = None

    if closed:
        maturity = MATURITY_CLOSED
    elif event:
        maturity = MATURITY_EVENT
    elif age is None:
        maturity = MATURITY_UNKNOWN
    elif age >= HORIZON_TRADING_DAYS:
        maturity = MATURITY_MATURE_OPEN
    else:
        maturity = MATURITY_PENDING

    return {
        "ticker": _attr(row, "ticker", ""),
        "entry_date": entry_date.isoformat() if isinstance(entry_date, date) else None,
        "age_trading_days": age,
        "maturity": maturity,
        "horizon_bucket": horizon_bucket(age) if age is not None else None,
        "score_eligible": maturity in SCORE_ELIGIBLE_STATES,
    }


def summarize_maturity(rows: Iterable[Any], report_date: date) -> dict[str, Any]:
    """Aggregate maturity counts across rows (advisory-only)."""
    per_row = [classify_maturity(r, report_date) for r in rows]
    counts: dict[str, int] = {
        MATURITY_CLOSED: 0,
        MATURITY_EVENT: 0,
        MATURITY_MATURE_OPEN: 0,
        MATURITY_PENDING: 0,
        MATURITY_UNKNOWN: 0,
    }
    buckets: dict[str, int] = {}
    for entry in per_row:
        counts[entry["maturity"]] = counts.get(entry["maturity"], 0) + 1
        b = entry["horizon_bucket"]
        if b:
            buckets[b] = buckets.get(b, 0) + 1

    score_eligible = sum(counts[s] for s in SCORE_ELIGIBLE_STATES)
    out: dict[str, Any] = {
        "report_date": report_date.isoformat(),
        "horizon_trading_days": HORIZON_TRADING_DAYS,
        "total_rows": len(per_row),
        "maturity_counts": counts,
        "horizon_bucket_counts": buckets,
        "score_eligible": score_eligible,
        "pending_horizon": counts[MATURITY_PENDING],
        "closed": counts[MATURITY_CLOSED],
        "rows": per_row,
    }
    out.update(advisory_safety_stamps())
    out["human_execution_required"] = True
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(
        description="Classify trade-log row outcome maturity (advisory-only)."
    )
    parser.add_argument("--input", required=True, type=Path, help="trade-log CSV export")
    parser.add_argument(
        "--report-date", default=None, help="report date YYYY-MM-DD (default: today)"
    )
    args = parser.parse_args(argv)

    try:
        from scripts.google_sheet_schema import load_trade_log_csv
    except ModuleNotFoundError:
        from google_sheet_schema import load_trade_log_csv  # type: ignore[no-redef]

    report_date = (
        date.fromisoformat(args.report_date) if args.report_date else date.today()
    )
    rows = load_trade_log_csv(args.input).rows
    summary = summarize_maturity(rows, report_date)
    print(json.dumps(summary, indent=2, default=str))
    return 0


__all__ = [
    "HORIZON_TRADING_DAYS",
    "MATURITY_CLOSED",
    "MATURITY_EVENT",
    "MATURITY_MATURE_OPEN",
    "MATURITY_PENDING",
    "MATURITY_UNKNOWN",
    "SCORE_ELIGIBLE_STATES",
    "trading_days_between",
    "horizon_bucket",
    "classify_maturity",
    "summarize_maturity",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
