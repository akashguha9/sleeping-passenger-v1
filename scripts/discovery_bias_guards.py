"""DISC-B2: look-ahead and survivorship guards for the discovery backtest.

Bias sources found in the existing tooling (scripts/run_imported_backtest.py)
and how each is handled now:

1. **Look-ahead at entry** — the runner's convention (entry = first bar
   with date >= signal date, close prices only) was correct but
   unasserted.  :func:`assert_entry_no_lookahead` makes it a hard
   invariant that raises instead of silently trusting bar ordering.
2. **Survivorship via silent OPEN-exclusion** — a symbol that DELISTS
   inside the horizon has no exit bar, the outcome stays OPEN, and the
   (usually losing) trade silently vanishes from the result set —
   inflating returns.  :func:`check_series_quality` flags series that
   end before the evaluation window closes (``delisting_suspected``) so
   the report counts them instead of forgetting them.
3. **Gaps and splits** — missing trading days and unadjusted split jumps
   are FLAGGED, never interpolated; a flagged symbol's results carry the
   flag in the report.

Everything here is pure (no network, no DB writes).  RESULTS FIREWALL:
tooling correctness only — nothing in this module is evidence of edge.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}

# A close-to-close move beyond this ratio in one bar is treated as a
# suspected unadjusted split/corporate action (0.5 == ±50%).
SPLIT_JUMP_RATIO = Decimal("0.5")
# Calendar-day gap (excluding weekends ~2 days) that flags missing data.
MAX_GAP_CALENDAR_DAYS = 7


class LookaheadError(AssertionError):
    """A backtest decision used data from after the decision date."""


def assert_entry_no_lookahead(signal_date: datetime, entry_date: datetime) -> None:
    """Hard guard: the entry bar may never precede the signal date."""
    if entry_date < signal_date:
        raise LookaheadError(
            f"look-ahead: entry bar {entry_date.date()} precedes signal "
            f"date {signal_date.date()}"
        )


def _parse_date(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def check_series_quality(
    bars: Sequence[dict[str, Any]],
    *,
    window_end: datetime,
    max_gap_days: int = MAX_GAP_CALENDAR_DAYS,
    split_jump_ratio: Decimal = SPLIT_JUMP_RATIO,
) -> dict[str, Any]:
    """Flag gaps, suspected splits, and delisting-truncated series.

    Never interpolates, never repairs — flags only.  ``window_end`` is
    the last date the backtest needs data for; a series ending earlier
    is delisting-suspected and its excluded trades must be REPORTED, not
    forgotten (survivorship guard).
    """
    parsed: list[tuple[datetime, Decimal | None]] = []
    for b in bars:
        dt = _parse_date(b.get("date"))
        if dt is not None:
            parsed.append((dt, _dec(b.get("close"))))
    parsed.sort(key=lambda x: x[0])

    gaps: list[dict[str, str]] = []
    suspected_splits: list[dict[str, str]] = []
    prev_dt: datetime | None = None
    prev_close: Decimal | None = None
    for dt, close in parsed:
        if prev_dt is not None and (dt - prev_dt) > timedelta(days=max_gap_days):
            gaps.append(
                {"from": prev_dt.strftime("%Y-%m-%d"), "to": dt.strftime("%Y-%m-%d")}
            )
        if (
            prev_close is not None
            and close is not None
            and prev_close > 0
            and abs(close - prev_close) / prev_close > split_jump_ratio
        ):
            suspected_splits.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "prev_close": str(prev_close),
                    "close": str(close),
                }
            )
        prev_dt, prev_close = dt, close if close is not None else prev_close

    last_bar = parsed[-1][0] if parsed else None
    delisting_suspected = bool(parsed) and last_bar is not None and last_bar < window_end
    flags: list[str] = []
    if not parsed:
        flags.append("no_data")
    if gaps:
        flags.append("gaps")
    if suspected_splits:
        flags.append("suspected_splits")
    if delisting_suspected:
        flags.append("delisting_suspected")

    return {
        **_STAMPS,
        "bar_count": len(parsed),
        "first_bar": parsed[0][0].strftime("%Y-%m-%d") if parsed else None,
        "last_bar": last_bar.strftime("%Y-%m-%d") if last_bar else None,
        "window_end": window_end.strftime("%Y-%m-%d"),
        "gaps": gaps,
        "suspected_splits": suspected_splits,
        "delisting_suspected": delisting_suspected,
        "clean": not flags,
        "flags": flags,
    }
