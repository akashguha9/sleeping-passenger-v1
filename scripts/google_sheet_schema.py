"""Typed, defensive normalization of Google-Sheet trade-log CSV exports.

The operator's paper-trade log lives in a Google Sheet with ~40 human-edited
columns and messy, mixed value formats: ``"1,883.50"`` for numbers, ``"80%"``
*or* ``"0.8"`` for the same percent column, ``"14-05-2026"`` day-first dates,
and free-text status cells such as ``"OPEN | Cum P/L: 29.76"``.  This module
turns one raw export into a list of strongly-typed :class:`TradeLogRow` records
plus a list of structured :class:`SheetValidationIssue` findings — *without*
silently discarding or guessing data, and without any network / broker / AI
execution surface.

Contract — pure module
----------------------
No DB, no network, no broker calls, no AI execution.  Deterministic: the same
CSV text always yields the same rows and issues.  It only *reads* a file path
(or accepts already-parsed dict rows) and returns dataclasses.

Critical invariant carried through to downstream metrics: ``CAPITAL AFTER ROW``
is *free / unallocated* cash, NOT total equity.  This module records that fact
as an :data:`CAPITAL_AFTER_ROW_NOT_EQUITY` INFO issue so no consumer can quietly
treat it as equity.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Literal

# --------------------------------------------------------------------------- #
# Issue model
# --------------------------------------------------------------------------- #
Severity = Literal["INFO", "WARNING", "ERROR"]

# Stable issue codes (documented in docs/TRADE_LOG_DISCOVERY_METRICS.md).
MISSING_TICKER = "MISSING_TICKER"
INVALID_DATE = "INVALID_DATE"
INVALID_PERCENT = "INVALID_PERCENT"
INVALID_NUMBER = "INVALID_NUMBER"
CLOSED_WITHOUT_EXIT_VALUE = "CLOSED_WITHOUT_EXIT_VALUE"
OPEN_WITH_SELL_PRICE = "OPEN_WITH_SELL_PRICE"
CAPITAL_AFTER_ROW_NOT_EQUITY = "CAPITAL_AFTER_ROW_NOT_EQUITY"
CUMULATIVE_PL_PARSE_FAILED = "CUMULATIVE_PL_PARSE_FAILED"
NEGATIVE_ALLOCATION = "NEGATIVE_ALLOCATION"
DUPLICATE_DATE_TICKER = "DUPLICATE_DATE_TICKER"
MODEL_VERSION_MISSING = "MODEL_VERSION_MISSING"
UNKNOWN_TRADE_STATE = "UNKNOWN_TRADE_STATE"


@dataclass(frozen=True)
class SheetValidationIssue:
    """A single structured finding about one row (or the dataset, row 0)."""

    row_number: int
    severity: Severity
    code: str
    message: str


@dataclass(frozen=True)
class TradeLogRow:
    """One typed trade-log row.  ``None`` means *absent*, not zero."""

    row_number: int
    date: date | None
    ticker: str
    buy_price: float | None
    sell_price: float | None
    leverage: float
    country: str
    currency: str
    model_used: str
    money_allocated: float
    capital_pre_trade: float | None
    profit_loss: float
    live_price: float | None
    cumulative_pl: float | None
    trade_state: str
    exit_stage_v2: str
    action_required_v2: str
    booked_pct: float
    remaining_pct: float
    cash_released: float
    capital_after_row: float | None
    # Extra fields needed by the metrics layer (not in the minimal brief spec
    # but present in the operator sheet) — kept optional so a thinner export
    # still parses.
    r_multiple: float | None = None
    signal_class: str = ""
    tp1_price: float | None = None
    tp2_price: float | None = None
    hard_stop_price: float | None = None
    model_version: str = ""
    raw: dict[str, str] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class SheetParseResult:
    rows: list[TradeLogRow]
    issues: list[SheetValidationIssue]

    def errors(self) -> list[SheetValidationIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    def warnings(self) -> list[SheetValidationIssue]:
        return [i for i in self.issues if i.severity == "WARNING"]


# --------------------------------------------------------------------------- #
# Header mapping
# --------------------------------------------------------------------------- #
def normalize_header(header: str) -> str:
    """Upper-case alphanumeric-only key: ``"CAPITAL PRE-TRADE" -> "CAPITALPRETRADE"``."""
    return re.sub(r"[^A-Z0-9]", "", str(header or "").upper())


# canonical field -> accepted normalized header variants (first match wins).
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "row_number": ("SLNO", "SLNUMBER", "SL", "NO", "ROW", "ROWNUMBER"),
    "date": ("DATE", "TRADEDATE", "ENTRYDATE"),
    "ticker": ("TICKER", "SYMBOL"),
    "buy_price": ("BUYPRICE", "ENTRYPRICE"),
    "sell_price": ("SELLPRICE", "EXITPRICE"),
    "leverage": ("LEVERAGE",),
    "country": ("COUNTRY",),
    "currency": ("CURRENCY",),
    "model_used": ("AIMODELUSED", "MODELUSED", "MODEL"),
    "model_version": ("MODELVERSION",),
    "money_allocated": ("MONEYALLOCATED", "ALLOCATED", "ALLOCATION"),
    "capital_pre_trade": ("CAPITALPRETRADE",),
    "profit_loss": ("PROFITLOSS", "PL", "PNL"),
    "live_price": ("LIVEPRICE", "CURRENTPRICE"),
    "cumulative_pl": ("CUMULATIVEPL", "CUMPL", "CUMULATIVEPROFITLOSS"),
    "trade_state": ("TRADESTATE", "STATE"),
    "exit_stage_v2": ("EXITSTAGEV2", "EXITSTAGE"),
    "action_required_v2": ("ACTIONREQUIREDV2", "ACTIONREQUIRED"),
    "booked_pct": ("TOTALBOOKED", "BOOKEDNUM", "BOOKED", "TOTALBOOKEDPCT"),
    "remaining_pct": ("REMAINING", "REMAININGAFTERACTION", "REMAININGPCT"),
    "cash_released": ("CASHRELEASEDFROMROW", "CASHRELEASED"),
    "capital_after_row": ("CAPITALAFTERROW",),
    "r_multiple": ("RMULTIPLE", "R"),
    "signal_class": ("SIGNALCLASS",),
    "tp1_price": ("TP1PRICE",),
    "tp2_price": ("TP2PRICE",),
    "hard_stop_price": ("HARDSTOPPRICE", "PROTECTEDSTOPPRICE"),
}


def map_headers(headers: Iterable[str]) -> dict[str, str]:
    """Map canonical field -> the original header string present in the export."""
    norm_to_original: dict[str, str] = {}
    for h in headers:
        norm_to_original.setdefault(normalize_header(h), h)
    mapping: dict[str, str] = {}
    for field_name, variants in _HEADER_ALIASES.items():
        for v in variants:
            if v in norm_to_original:
                mapping[field_name] = norm_to_original[v]
                break
    return mapping


# --------------------------------------------------------------------------- #
# Scalar parsers (raise ValueError on genuinely un-parseable non-empty input;
# return None on empty/absent).
# --------------------------------------------------------------------------- #
_CURRENCY_CHARS = "€$£₹¥₩"
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def is_blank(raw: Any) -> bool:
    return raw is None or str(raw).strip() == ""


def parse_number(raw: Any) -> float | None:
    """Parse ``"1,883.50"`` / ``"€1.234,5"``-free numbers.  ``""`` -> ``None``.

    Handles thousands commas and a leading/trailing currency symbol.  Raises
    ``ValueError`` for non-empty input that holds no number.
    """
    if is_blank(raw):
        return None
    s = str(raw).strip()
    for ch in _CURRENCY_CHARS:
        s = s.replace(ch, "")
    s = s.replace(",", "").replace(" ", "")
    # Parentheses as accounting negatives: "(12.5)" -> -12.5
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        val = float(s)
    except ValueError as exc:
        raise ValueError(f"not a number: {raw!r}") from exc
    return -val if neg else val


def parse_percent(raw: Any) -> float | None:
    """Normalize mixed percent formats to a [0,1]-style fraction.  ``""`` -> ``None``.

    ``"80%" -> 0.8``, ``"80.00%" -> 0.8``, ``"0.8" -> 0.8``, ``"1" -> 1.0``,
    ``"100.00%" -> 1.0``, bare ``"80" -> 0.8``.  Rule: an explicit ``%`` divides
    by 100; otherwise a bare value ``> 1.0`` is treated as a percent figure and
    divided by 100, while ``<= 1.0`` is already a fraction.
    """
    if is_blank(raw):
        return None
    s = str(raw).strip()
    has_pct = "%" in s
    s = s.replace("%", "").replace(",", "").strip()
    try:
        val = float(s)
    except ValueError as exc:
        raise ValueError(f"not a percent: {raw!r}") from exc
    if has_pct:
        return val / 100.0
    return val / 100.0 if val > 1.0 else val


_DATE_FORMATS = (
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
)


def parse_date(raw: Any) -> date | None:
    """Parse day-first or ISO dates.  ``""`` -> ``None``; raises on garbage.

    Also tolerates an ISO timestamp (``"2026-05-14T09:30:00Z"``) by taking the
    leading date component.
    """
    if is_blank(raw):
        return None
    s = str(raw).strip()
    # ISO timestamp -> take date part.
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})[T ]", s)
    if iso_match:
        s = iso_match.group(1)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {raw!r}")


_CUM_PL_LABEL_RE = re.compile(r"cum(?:ulative)?\s*p\s*/?\s*l\s*:?\s*", re.IGNORECASE)


def parse_cumulative_pl(raw: Any) -> float | None:
    """Extract the cumulative P/L number even from text like
    ``"OPEN | Cum P/L: 29.76"``.  ``""`` -> ``None``; raises if no number.
    """
    if is_blank(raw):
        return None
    s = str(raw).strip()
    label = _CUM_PL_LABEL_RE.search(s)
    if label:
        s = s[label.end():]
    # Strip thousands commas before scanning for a number.
    s_clean = s.replace(",", "")
    m = _NUMBER_RE.search(s_clean)
    if not m:
        raise ValueError(f"no cumulative P/L number in {raw!r}")
    return float(m.group(0))


# --------------------------------------------------------------------------- #
# State vocabulary
# --------------------------------------------------------------------------- #
KNOWN_TRADE_STATES: frozenset[str] = frozenset(
    {
        "OPEN",
        "CLOSED",
        "STOP_CLOSED",
        "CLOSE_TRADE_SYNCED",
        "PARTIAL_TP_LOGGED",
        "PENDING",
        "PENDING_HORIZON",
        "NEW",
        "FLAT",
        "QUARANTINED",
        "WATCH",
        "WAIT",
    }
)


def _norm_state(value: str) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().upper())


def _looks_closed(trade_state: str, exit_stage: str) -> bool:
    ts, es = _norm_state(trade_state), _norm_state(exit_stage)
    return (
        ts in {"CLOSED", "STOP_CLOSED", "CLOSE_TRADE_SYNCED"}
        or "CLOSED" in es
    )


def _looks_open(trade_state: str) -> bool:
    return _norm_state(trade_state).startswith("OPEN")


# --------------------------------------------------------------------------- #
# Row construction
# --------------------------------------------------------------------------- #
def _get(raw_row: dict[str, str], mapping: dict[str, str], field_name: str) -> str:
    col = mapping.get(field_name)
    if col is None:
        return ""
    return str(raw_row.get(col, "") or "")


def build_row(
    row_number: int,
    raw_row: dict[str, str],
    mapping: dict[str, str],
) -> tuple[TradeLogRow, list[SheetValidationIssue]]:
    """Build one typed row + its per-row issues."""
    issues: list[SheetValidationIssue] = []

    def num(field_name: str, *, code: str = INVALID_NUMBER) -> float | None:
        try:
            return parse_number(_get(raw_row, mapping, field_name))
        except ValueError:
            issues.append(
                SheetValidationIssue(
                    row_number, "WARNING", code,
                    f"{field_name}={_get(raw_row, mapping, field_name)!r} not numeric",
                )
            )
            return None

    def pct(field_name: str) -> float | None:
        try:
            return parse_percent(_get(raw_row, mapping, field_name))
        except ValueError:
            issues.append(
                SheetValidationIssue(
                    row_number, "WARNING", INVALID_PERCENT,
                    f"{field_name}={_get(raw_row, mapping, field_name)!r} not a percent",
                )
            )
            return None

    ticker = _get(raw_row, mapping, "ticker").strip().upper()
    if not ticker:
        issues.append(
            SheetValidationIssue(row_number, "ERROR", MISSING_TICKER, "ticker is empty")
        )

    parsed_date: date | None = None
    raw_date = _get(raw_row, mapping, "date")
    try:
        parsed_date = parse_date(raw_date)
    except ValueError:
        issues.append(
            SheetValidationIssue(
                row_number, "ERROR", INVALID_DATE, f"unparseable date {raw_date!r}"
            )
        )

    cumulative_pl: float | None = None
    raw_cum = _get(raw_row, mapping, "cumulative_pl")
    try:
        cumulative_pl = parse_cumulative_pl(raw_cum)
    except ValueError:
        issues.append(
            SheetValidationIssue(
                row_number, "WARNING", CUMULATIVE_PL_PARSE_FAILED,
                f"could not parse cumulative P/L from {raw_cum!r}",
            )
        )

    buy_price = num("buy_price")
    sell_price = num("sell_price")
    leverage = num("leverage")
    money_allocated = num("money_allocated") or 0.0
    profit_loss = num("profit_loss") or 0.0
    booked = pct("booked_pct") or 0.0
    remaining = pct("remaining_pct")
    cash_released = num("cash_released") or 0.0

    trade_state = _get(raw_row, mapping, "trade_state").strip()
    exit_stage = _get(raw_row, mapping, "exit_stage_v2").strip()
    model_used = _get(raw_row, mapping, "model_used").strip()

    if money_allocated < 0:
        issues.append(
            SheetValidationIssue(
                row_number, "ERROR", NEGATIVE_ALLOCATION,
                f"money_allocated is negative ({money_allocated})",
            )
        )

    if not model_used and not _get(raw_row, mapping, "model_version").strip():
        issues.append(
            SheetValidationIssue(
                row_number, "INFO", MODEL_VERSION_MISSING,
                "no AI MODEL USED / model_version recorded",
            )
        )

    closed = _looks_closed(trade_state, exit_stage)
    if closed and sell_price is None and cash_released == 0.0 and not exit_stage:
        issues.append(
            SheetValidationIssue(
                row_number, "WARNING", CLOSED_WITHOUT_EXIT_VALUE,
                "closed row has no sell price, cash released, or exit note",
            )
        )
    if _looks_open(trade_state) and not closed and sell_price is not None:
        issues.append(
            SheetValidationIssue(
                row_number, "WARNING", OPEN_WITH_SELL_PRICE,
                "open row carries a sell price",
            )
        )

    norm_ts = _norm_state(trade_state)
    if norm_ts and norm_ts not in KNOWN_TRADE_STATES:
        issues.append(
            SheetValidationIssue(
                row_number, "WARNING", UNKNOWN_TRADE_STATE,
                f"unrecognized trade state {trade_state!r}",
            )
        )

    row = TradeLogRow(
        row_number=row_number,
        date=parsed_date,
        ticker=ticker,
        buy_price=buy_price,
        sell_price=sell_price,
        leverage=leverage if leverage is not None else 1.0,
        country=_get(raw_row, mapping, "country").strip(),
        currency=_get(raw_row, mapping, "currency").strip().upper(),
        model_used=model_used,
        money_allocated=money_allocated,
        capital_pre_trade=num("capital_pre_trade"),
        profit_loss=profit_loss,
        live_price=num("live_price"),
        cumulative_pl=cumulative_pl,
        trade_state=trade_state,
        exit_stage_v2=exit_stage,
        action_required_v2=_get(raw_row, mapping, "action_required_v2").strip(),
        booked_pct=booked,
        remaining_pct=remaining if remaining is not None else _infer_remaining(
            trade_state, exit_stage, booked
        ),
        cash_released=cash_released,
        capital_after_row=num("capital_after_row"),
        r_multiple=num("r_multiple"),
        signal_class=_get(raw_row, mapping, "signal_class").strip(),
        tp1_price=num("tp1_price"),
        tp2_price=num("tp2_price"),
        hard_stop_price=num("hard_stop_price"),
        model_version=_get(raw_row, mapping, "model_version").strip(),
        raw=dict(raw_row),
    )
    return row, issues


def _infer_remaining(trade_state: str, exit_stage: str, booked: float) -> float:
    """Fallback remaining-fraction when the column is missing (brief spec)."""
    if _looks_closed(trade_state, exit_stage):
        return 0.0
    if _norm_state(trade_state) == "PARTIAL_TP_LOGGED" or "PARTIAL_TP" in _norm_state(exit_stage):
        if booked >= 0.8:
            return 0.2
        if booked >= 0.5:
            return 0.5
        return max(0.0, 1.0 - booked)
    if _looks_open(trade_state):
        return 1.0
    return 1.0


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def normalize_rows(raw_rows: list[dict[str, str]]) -> SheetParseResult:
    """Normalize already-parsed dict rows (keys = original headers)."""
    issues: list[SheetValidationIssue] = []
    if not raw_rows:
        return SheetParseResult([], issues)

    mapping = map_headers(raw_rows[0].keys())
    # Dataset-level honesty stamp: capital-after-row is free cash, not equity.
    issues.append(
        SheetValidationIssue(
            0, "INFO", CAPITAL_AFTER_ROW_NOT_EQUITY,
            "CAPITAL AFTER ROW is free/unallocated cash, not total equity; "
            "marked equity = starting_capital + latest cumulative P/L.",
        )
    )

    rows: list[TradeLogRow] = []
    seen: dict[tuple[str, str], int] = {}
    for idx, raw_row in enumerate(raw_rows, start=1):
        row_num = _row_number_for(raw_row, mapping, idx)
        row, row_issues = build_row(row_num, raw_row, mapping)
        issues.extend(row_issues)
        key = (row.ticker, row.date.isoformat() if row.date else "")
        if row.ticker and key in seen:
            issues.append(
                SheetValidationIssue(
                    row_num, "WARNING", DUPLICATE_DATE_TICKER,
                    f"duplicate (date, ticker) of row {seen[key]}: {key}",
                )
            )
        elif row.ticker:
            seen[key] = row_num
        rows.append(row)
    return SheetParseResult(rows, issues)


def _row_number_for(raw_row: dict[str, str], mapping: dict[str, str], fallback: int) -> int:
    raw = _get(raw_row, mapping, "row_number")
    try:
        v = parse_number(raw)
        return int(v) if v is not None else fallback
    except ValueError:
        return fallback


def load_trade_log_csv(path: str | Path) -> SheetParseResult:
    """Read a CSV export and normalize it.  Tolerant of a BOM (utf-8-sig)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    raw_rows = [dict(r) for r in reader]
    return normalize_rows(raw_rows)


__all__ = [
    "Severity",
    "SheetValidationIssue",
    "TradeLogRow",
    "SheetParseResult",
    "normalize_header",
    "map_headers",
    "parse_number",
    "parse_percent",
    "parse_date",
    "parse_cumulative_pl",
    "KNOWN_TRADE_STATES",
    "normalize_rows",
    "load_trade_log_csv",
    # issue codes
    "MISSING_TICKER",
    "INVALID_DATE",
    "INVALID_PERCENT",
    "INVALID_NUMBER",
    "CLOSED_WITHOUT_EXIT_VALUE",
    "OPEN_WITH_SELL_PRICE",
    "CAPITAL_AFTER_ROW_NOT_EQUITY",
    "CUMULATIVE_PL_PARSE_FAILED",
    "NEGATIVE_ALLOCATION",
    "DUPLICATE_DATE_TICKER",
    "MODEL_VERSION_MISSING",
    "UNKNOWN_TRADE_STATE",
]
