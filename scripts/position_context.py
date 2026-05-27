"""Position Context loader — merges canonical OPEN holdings with
manual-trade SQLite rows, optional live marks, and release files into
a single deterministic per-position context dict that the Capital
Rotation Engine can grade.

Why this exists
---------------
``verified_current_holdings.json`` is the canonical OPEN list (ticker,
entry_price, leverage, currency, quantity, country) but it does *not*
store ``live_price``, ``stop_loss``, ``tp_price``, ``partial_tp_logged``,
``thesis``, ``entry_reason`` etc.  Those fields live in the
``manual_trades`` SQLite row (``invalidation_level`` ≈ ``stop_loss``,
``expected_horizon``, ``entry_reason``, ``risk_reason``, ``exit_plan``,
``ai_model_used``, ``thesis``) and in transient release artefacts.

Without merging them, the daily lifecycle classifier was forcing many
rows into ``DATA_BLOCKED`` even though the operator had already
recorded the entry, stop, and reasoning in the manual trade log.  The
merge logic here is the plumbing fix; the lifecycle module then grades
each row using the new merged context.

Contract — pure module
----------------------
- Importing has no side effects.
- No broker calls.  No network.  No AI execution.
- The loader reads existing JSON / SQLite artefacts that the operator
  has already approved.  Live marks are passed in or pulled from the
  market snapshot — *never* fetched on demand.
- Every produced PositionContext carries the advisory-only invariant.
"""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from scripts.runtime_common import REPO_ROOT
    from scripts.daily_payload import (
        VERIFIED_HOLDINGS_PATH,
        OPEN_STATUSES,
        CLOSED_STATUSES,
        load_verified_holdings,
        load_market_snapshot,
        load_closed_positions,
        load_sold_positions,
        load_do_not_treat_as_open,
    )
    from scripts.economic_exposure import (
        map_theme_buckets,
        normalize_economic_exposure,
    )
    from scripts.live_price_marks import (
        LiveMark,
        LiveMarkResult,
        fetch_live_marks as _fetch_live_marks,
        REASON_LIVE_MARK_MERGED as _REASON_LIVE_MARK_MERGED,
        REASON_LIVE_MARK_STALE as _REASON_LM_STALE,
        REASON_LIVE_MARK_UNUSABLE as _REASON_LM_UNUSABLE,
        REASON_LIVE_MARK_PROVIDER_DISAGREEMENT as _REASON_LM_DISAGREE,
        REASON_LIVE_MARK_FROM_YFINANCE as _REASON_LM_YF,
        REASON_LIVE_MARK_FROM_SNAPSHOT as _REASON_LM_SNAPSHOT,
        REASON_LIVE_MARK_FROM_DB as _REASON_LM_DB,
        REASON_LIVE_MARK_FROM_RELEASE as _REASON_LM_RELEASE,
    )
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from runtime_common import REPO_ROOT  # type: ignore
    from daily_payload import (  # type: ignore
        VERIFIED_HOLDINGS_PATH,
        OPEN_STATUSES,
        CLOSED_STATUSES,
        load_verified_holdings,
        load_market_snapshot,
        load_closed_positions,
        load_sold_positions,
        load_do_not_treat_as_open,
    )
    from economic_exposure import (  # type: ignore
        map_theme_buckets,
        normalize_economic_exposure,
    )
    from live_price_marks import (  # type: ignore
        LiveMark,
        LiveMarkResult,
        fetch_live_marks as _fetch_live_marks,
        REASON_LIVE_MARK_MERGED as _REASON_LIVE_MARK_MERGED,
        REASON_LIVE_MARK_STALE as _REASON_LM_STALE,
        REASON_LIVE_MARK_UNUSABLE as _REASON_LM_UNUSABLE,
        REASON_LIVE_MARK_PROVIDER_DISAGREEMENT as _REASON_LM_DISAGREE,
        REASON_LIVE_MARK_FROM_YFINANCE as _REASON_LM_YF,
        REASON_LIVE_MARK_FROM_SNAPSHOT as _REASON_LM_SNAPSHOT,
        REASON_LIVE_MARK_FROM_DB as _REASON_LM_DB,
        REASON_LIVE_MARK_FROM_RELEASE as _REASON_LM_RELEASE,
    )


DEFAULT_DB_PATH = REPO_ROOT / "runtime" / "mvp_local.db"

CONTEXT_COMPLETE = "COMPLETE"
CONTEXT_USABLE = "USABLE"
CONTEXT_PARTIAL = "PARTIAL"
CONTEXT_INSUFFICIENT = "INSUFFICIENT"

ALL_CONTEXT_QUALITY: tuple[str, ...] = (
    CONTEXT_COMPLETE,
    CONTEXT_USABLE,
    CONTEXT_PARTIAL,
    CONTEXT_INSUFFICIENT,
)

SOURCE_CANONICAL_DB = "CANONICAL_DB"
SOURCE_MANUAL_LOG = "MANUAL_LOG"
SOURCE_RELEASE_FILE = "RELEASE_FILE"
SOURCE_VERIFIED_HOLDINGS = "VERIFIED_HOLDINGS"
SOURCE_FALLBACK = "FALLBACK"

ALL_SOURCE_HEALTH: tuple[str, ...] = (
    SOURCE_CANONICAL_DB,
    SOURCE_MANUAL_LOG,
    SOURCE_RELEASE_FILE,
    SOURCE_VERIFIED_HOLDINGS,
    SOURCE_FALLBACK,
)


# Reason codes (kept as constants so tests can reference them directly).
REASON_LIVE_MARK_STALE = "LIVE_MARK_STALE"
REASON_LIVE_MARK_MISSING = "LIVE_MARK_MISSING"
REASON_LIVE_MARK_MERGED = "LIVE_MARK_MERGED"
REASON_LIVE_MARK_UNUSABLE = "LIVE_MARK_UNUSABLE"
REASON_LIVE_MARK_PROVIDER_DISAGREEMENT = "LIVE_MARK_PROVIDER_DISAGREEMENT"
REASON_LIVE_MARK_FROM_YFINANCE = "LIVE_MARK_FROM_YFINANCE"
REASON_LIVE_MARK_FROM_SNAPSHOT = "LIVE_MARK_FROM_SNAPSHOT"
REASON_LIVE_MARK_FROM_DB = "LIVE_MARK_FROM_DB"
REASON_LIVE_MARK_FROM_RELEASE = "LIVE_MARK_FROM_RELEASE"
REASON_CONTEXT_FROM_FALLBACK = "CONTEXT_FROM_FALLBACK"
REASON_CONTEXT_FROM_CANONICAL_DB = "CONTEXT_FROM_CANONICAL_DB"
REASON_CONTEXT_FROM_MANUAL_LOG = "CONTEXT_FROM_MANUAL_LOG"
REASON_CONTEXT_FROM_VERIFIED_HOLDINGS = "CONTEXT_FROM_VERIFIED_HOLDINGS"
REASON_CONTEXT_MERGED = "CONTEXT_MERGED"
REASON_THESIS_CONTEXT_MISSING = "THESIS_CONTEXT_MISSING"
REASON_LEVERAGE_DEFAULTED = "LEVERAGE_DEFAULTED"
REASON_CURRENCY_UNKNOWN = "CURRENCY_UNKNOWN"
REASON_HISTORICAL_NOT_OPEN = "HISTORICAL_NOT_OPEN"
REASON_DUPLICATE_LOTS = "DUPLICATE_LOTS"


@dataclass
class PositionContext:
    """One merged, advisory-only position context row.

    Mirrors the Section-2 schema in the sprint brief.  Field defaults
    are conservative — None for unknown, never a fabricated value.
    """

    ticker: str
    raw_ticker: str | None = None
    economic_exposure_key: str = ""
    theme_buckets: list[str] = field(default_factory=list)
    trade_state: str = "OPEN"

    buy_price: float | None = None
    live_price: float | None = None
    stop_loss: float | None = None
    tp_price: float | None = None
    leverage: float = 1.0
    currency: str = "UNKNOWN"
    country: str | None = None

    money_allocated: float | None = None
    quantity: float | None = None

    partial_tp_logged: bool = False
    booked_pct: float = 0.0
    ride_pct: float = 0.0

    last_updated_at: str | None = None
    opened_at: str | None = None
    days_open: float | None = None
    expected_horizon_days: float | None = None

    thesis: str | None = None
    risk_reason: str | None = None
    entry_reason: str | None = None
    exit_plan: str | None = None
    ai_model_used: str | None = None

    source_health: str = SOURCE_VERIFIED_HOLDINGS
    context_quality: str = CONTEXT_INSUFFICIENT
    context_quality_score: float = 0.0
    missing_fields: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    # --- Live mark provenance + mechanical usability --------------------
    # ``live_price`` above is the mechanical price the lifecycle classifier
    # consumes — it is only set when ``mechanical_live_price_usable`` is
    # True.  ``display_live_price`` may still hold a stale/delayed price so
    # the UI can render a number with a clear "delayed" badge.
    display_live_price: float | None = None
    mechanical_live_price_usable: bool = False
    live_mark_quality_score: float | None = None
    live_mark_source: str | None = None
    live_mark_source_health: str | None = None
    live_mark_age_hours: float | None = None
    live_mark_reason_codes: list[str] = field(default_factory=list)

    advisory_only: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    human_execution_required: bool = True
    execution_permission: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PositionContextResult:
    """Bag of PositionContexts plus aggregated diagnostics."""

    contexts: list[PositionContext] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    quality_counts: dict[str, int] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    open_positions_loaded: int = 0
    db_available: bool = False
    holdings_present: bool = False
    live_mark_result: LiveMarkResult | None = None
    advisory_only: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    human_execution_required: bool = True
    execution_permission: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contexts": [c.to_dict() for c in self.contexts],
            "source_counts": dict(self.source_counts),
            "quality_counts": dict(self.quality_counts),
            "reason_codes": list(self.reason_codes),
            "open_positions_loaded": self.open_positions_loaded,
            "db_available": self.db_available,
            "holdings_present": self.holdings_present,
            "live_mark_result": (
                self.live_mark_result.to_dict()
                if self.live_mark_result is not None
                else None
            ),
            "advisory_only": self.advisory_only,
            "broker_api_called": self.broker_api_called,
            "ai_execution_count": self.ai_execution_count,
            "human_execution_required": self.human_execution_required,
            "execution_permission": self.execution_permission,
        }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _truthy_yes(value: Any) -> bool:
    if value is True:
        return True
    if value in (1, "1"):
        return True
    if isinstance(value, str):
        return value.strip().upper() in {"YES", "TRUE", "Y", "T"}
    return False


def normalize_position_ticker(raw_ticker: Any) -> str:
    """Return the canonical ticker form used as the merge key.

    Strips an exchange prefix (``NASDAQ:GOOGL`` → ``GOOGL``) and
    preserves country suffixes that matter for sizing rules
    (``HDFCBANK.NS`` stays ``HDFCBANK.NS``).  Empty in → empty out.
    """
    if raw_ticker is None:
        return ""
    text = str(raw_ticker).strip().upper()
    if not text:
        return ""
    if ":" in text:
        text = text.rsplit(":", 1)[-1].strip()
    return text


def _parse_invalidation_to_stop(invalidation: Any) -> float | None:
    """Extract a numeric stop_loss from the manual_trades.invalidation_level.

    The column is free-form text but operators commonly enter either a
    bare number ("95.0") or a phrase containing a number ("close <
    95").  Anything we can't parse returns ``None`` — never a guess.
    """
    if invalidation is None:
        return None
    text = str(invalidation).strip()
    if not text:
        return None
    direct = _safe_float(text)
    if direct is not None:
        return direct
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match:
        return _safe_float(match.group(0))
    return None


def _parse_expected_horizon_days(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if not text:
        return None
    direct = _safe_float(text)
    if direct is not None:
        return direct
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    num = _safe_float(match.group(0))
    if num is None:
        return None
    if "week" in text:
        return num * 7.0
    if "month" in text:
        return num * 30.0
    if "year" in text:
        return num * 365.0
    return num


def _parse_iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _days_between(now_utc: datetime, opened: datetime | None) -> float | None:
    if opened is None:
        return None
    delta = now_utc - opened
    return max(0.0, delta.total_seconds() / 86400.0)


# ---------------------------------------------------------------------------
# Context quality math (Section 3)
# ---------------------------------------------------------------------------


def compute_context_quality(ctx: PositionContext) -> tuple[float, str, list[str]]:
    """Return ``(score, quality_label, missing_fields)``.

    Pure math; uses the weights from Section 3 of the sprint brief.
    """
    i_buy = 1.0 if ctx.buy_price is not None and ctx.buy_price > 0 else 0.0
    i_live = 1.0 if ctx.live_price is not None and ctx.live_price > 0 else 0.0
    i_stop = 1.0 if ctx.stop_loss is not None and ctx.stop_loss > 0 else 0.0
    i_tp = 1.0 if ctx.tp_price is not None and ctx.tp_price > 0 else 0.0
    i_lev = 1.0 if ctx.leverage is not None and ctx.leverage > 0 else 0.0
    i_cur = 1.0 if ctx.currency and ctx.currency.upper() != "UNKNOWN" else 0.0
    i_state = 1.0 if ctx.trade_state else 0.0
    i_time = 1.0 if (ctx.opened_at or ctx.last_updated_at) else 0.0

    score = (
        0.18 * i_buy
        + 0.22 * i_live
        + 0.18 * i_stop
        + 0.18 * i_tp
        + 0.08 * i_lev
        + 0.06 * i_cur
        + 0.05 * i_state
        + 0.05 * i_time
    )
    score = _clamp(score, 0.0, 1.0)

    if score >= 0.90:
        label = CONTEXT_COMPLETE
    elif score >= 0.70:
        label = CONTEXT_USABLE
    elif score >= 0.45:
        label = CONTEXT_PARTIAL
    else:
        label = CONTEXT_INSUFFICIENT

    missing: list[str] = []
    if not i_buy:
        missing.append("buy_price")
    if not i_live:
        missing.append("live_price")
    if not i_stop:
        missing.append("stop_loss")
    if not i_tp:
        missing.append("tp_price")
    if not i_lev:
        missing.append("leverage")
    if not i_cur:
        missing.append("currency")
    if not i_state:
        missing.append("trade_state")
    if not i_time:
        missing.append("last_updated_at")

    return score, label, missing


# ---------------------------------------------------------------------------
# Per-source readers
# ---------------------------------------------------------------------------


def _read_manual_trade_rows(db_path: Path) -> list[dict[str, Any]]:
    """Read every manual_trades row that is not cancelled.

    Returns plain dicts.  Empty list if the DB / table is missing — the
    function never raises for "database not present".
    """
    if not db_path or not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ticker, side, quantity, price, leverage, executed_at,
                   thesis, notes, entry_reason, risk_reason, exit_plan,
                   invalidation_level, expected_horizon, currency,
                   ai_model_used, logged_by, execution_mode,
                   reconciliation_status, cancelled_at, cancel_reason,
                   trade_mode, created_via
              FROM manual_trades
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except sqlite3.DatabaseError:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("cancelled_at"):
            continue
        out.append(row)
    return out


def _build_manual_trade_state(
    rows: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate manual_trades rows into per-ticker net state.

    BUY rows add to net quantity at the row's price; SELL rows subtract
    (but we don't recompute the cost basis here — the canonical
    ``verified_current_holdings.json`` is the truth for entry_price).

    For each ticker we keep the *latest non-empty* value of every
    context field (thesis, invalidation_level, etc.) so we don't lose
    information when an operator updates a thesis without re-entering
    the trade.

    ``partial_tp_logged`` is set when at least one SELL row exists for
    a ticker that still has net open quantity.
    """
    state: dict[str, dict[str, Any]] = {}
    sorted_rows = sorted(
        rows,
        key=lambda r: str(r.get("executed_at") or ""),
    )
    for row in sorted_rows:
        ticker = normalize_position_ticker(row.get("ticker"))
        if not ticker:
            continue
        bucket = state.setdefault(
            ticker,
            {
                "ticker": ticker,
                "net_quantity": 0.0,
                "buy_quantity": 0.0,
                "sell_quantity": 0.0,
                "last_buy_price": None,
                "leverage": None,
                "currency": None,
                "thesis": None,
                "entry_reason": None,
                "risk_reason": None,
                "exit_plan": None,
                "invalidation_level": None,
                "stop_loss": None,
                "tp_price": None,
                "expected_horizon_days": None,
                "ai_model_used": None,
                "last_executed_at": None,
                "first_executed_at": None,
                "sell_count": 0,
                "buy_count": 0,
            },
        )
        side = str(row.get("side") or "").strip().upper()
        qty = _safe_float(row.get("quantity")) or 0.0
        price = _safe_float(row.get("price"))
        if side == "BUY":
            bucket["net_quantity"] = bucket["net_quantity"] + qty
            bucket["buy_quantity"] = bucket["buy_quantity"] + qty
            bucket["buy_count"] += 1
            if price is not None:
                bucket["last_buy_price"] = price
        elif side == "SELL":
            bucket["net_quantity"] = bucket["net_quantity"] - qty
            bucket["sell_quantity"] = bucket["sell_quantity"] + qty
            bucket["sell_count"] += 1
        # Update soft/latest fields if non-empty.
        for src_key, dst_key in (
            ("leverage", "leverage"),
            ("currency", "currency"),
            ("thesis", "thesis"),
            ("entry_reason", "entry_reason"),
            ("risk_reason", "risk_reason"),
            ("exit_plan", "exit_plan"),
            ("invalidation_level", "invalidation_level"),
            ("ai_model_used", "ai_model_used"),
        ):
            value = row.get(src_key)
            if value not in (None, "", 0):
                bucket[dst_key] = value
        horizon = _parse_expected_horizon_days(row.get("expected_horizon"))
        if horizon is not None:
            bucket["expected_horizon_days"] = horizon
        stop = _parse_invalidation_to_stop(row.get("invalidation_level"))
        if stop is not None:
            bucket["stop_loss"] = stop
        tp = _safe_float(
            row.get("tp_price")
            or row.get("take_profit_price")
            or row.get("take_profit")
        )
        if tp is not None and tp > 0:
            bucket["tp_price"] = tp
        executed_at = row.get("executed_at")
        if executed_at:
            bucket["last_executed_at"] = executed_at
            if bucket.get("first_executed_at") is None:
                bucket["first_executed_at"] = executed_at
    return state


def _build_live_marks(
    *,
    holdings_rows: Sequence[dict[str, Any]],
    market_snapshot: dict[str, Any] | None,
    explicit_live_marks: dict[str, float] | None,
) -> dict[str, float]:
    """Best-effort live-price lookup (float-only fast path).

    Priority: explicit caller marks → ``live_price`` field on a
    holdings row (if the operator pre-populated it) → ``current_price``
    on a holdings row → empty.  We never hit the network.

    NOTE: this is the legacy float-only merge path.  The new
    ``LiveMarkResult`` integration goes via
    ``_marks_from_live_mark_result`` and lets the caller flow richer
    provenance into the PositionContext.
    """
    marks: dict[str, float] = {}
    if market_snapshot:
        # The market snapshot can carry an "indices"/"commodities" array
        # but it generally does NOT carry per-position live marks.  We
        # still scan a few common shapes defensively.
        for collection_key in ("live_marks", "prices", "tickers"):
            collection = market_snapshot.get(collection_key)
            if isinstance(collection, dict):
                for k, v in collection.items():
                    price = _safe_float(v)
                    if price is not None:
                        marks[normalize_position_ticker(k)] = price
            elif isinstance(collection, list):
                for row in collection:
                    if not isinstance(row, dict):
                        continue
                    key = (
                        row.get("ticker")
                        or row.get("symbol")
                        or row.get("normalized_ticker")
                    )
                    price = _safe_float(
                        row.get("live_price")
                        or row.get("current_price")
                        or row.get("price")
                    )
                    if key and price is not None:
                        marks[normalize_position_ticker(key)] = price
    for row in holdings_rows or []:
        key = (
            row.get("normalized_ticker")
            or row.get("ticker")
            or row.get("symbol")
        )
        price = _safe_float(
            row.get("live_price") or row.get("current_price")
        )
        if key and price is not None:
            marks.setdefault(normalize_position_ticker(key), price)
    if explicit_live_marks:
        for k, v in explicit_live_marks.items():
            price = _safe_float(v)
            if price is not None:
                marks[normalize_position_ticker(k)] = price
    return marks


def _normalize_live_marks_input(
    live_marks: Any,
) -> tuple[dict[str, float], dict[str, LiveMark]]:
    """Coerce caller-supplied live marks into two parallel views.

    Returns:
      * ``floats_by_ticker``  — ticker → numeric price (legacy view)
      * ``rich_by_ticker``    — ticker → :class:`LiveMark` instance

    Accepts: plain ``{ticker: price}`` floats, a list of LiveMark
    dataclasses, a list of raw dicts, or a mix.  Unknown shapes are
    silently dropped (never raises).
    """
    floats: dict[str, float] = {}
    rich: dict[str, LiveMark] = {}
    if not live_marks:
        return floats, rich
    if isinstance(live_marks, dict):
        for key, value in live_marks.items():
            ticker_key = normalize_position_ticker(key)
            if not ticker_key:
                continue
            if isinstance(value, LiveMark):
                rich[ticker_key] = value
                if value.live_price is not None:
                    floats[ticker_key] = float(value.live_price)
                continue
            if isinstance(value, dict):
                price = _safe_float(value.get("live_price") or value.get("price"))
                if price is not None:
                    floats[ticker_key] = price
                continue
            price = _safe_float(value)
            if price is not None:
                floats[ticker_key] = price
        return floats, rich
    if isinstance(live_marks, list):
        for entry in live_marks:
            if isinstance(entry, LiveMark):
                key = normalize_position_ticker(entry.ticker)
                if not key:
                    continue
                rich[key] = entry
                if entry.live_price is not None:
                    floats[key] = float(entry.live_price)
                continue
            if isinstance(entry, dict):
                key = normalize_position_ticker(
                    entry.get("ticker")
                    or entry.get("symbol")
                    or entry.get("normalized_ticker")
                )
                if not key:
                    continue
                price = _safe_float(entry.get("live_price") or entry.get("price"))
                if price is not None:
                    floats[key] = price
        return floats, rich
    return floats, rich


def _marks_from_live_mark_result(
    result: LiveMarkResult | None,
) -> dict[str, LiveMark]:
    if result is None:
        return {}
    return {normalize_position_ticker(k): v for k, v in result.marks.items()}


# ---------------------------------------------------------------------------
# Merge logic — public API
# ---------------------------------------------------------------------------


def position_context_to_lifecycle_input(ctx: PositionContext) -> dict[str, Any]:
    """Adapt a PositionContext to the dict shape the lifecycle classifier
    consumes.  Lossless — keeps every numeric so the classifier can
    derive its own metrics.
    """
    return {
        "ticker": ctx.ticker,
        "normalized_ticker": ctx.ticker,
        "buy_price": ctx.buy_price,
        "live_price": ctx.live_price,
        "display_live_price": ctx.display_live_price,
        "mechanical_live_price_usable": ctx.mechanical_live_price_usable,
        "live_mark_quality_score": ctx.live_mark_quality_score,
        "live_mark_source": ctx.live_mark_source,
        "live_mark_source_health": ctx.live_mark_source_health,
        "live_mark_age_hours": ctx.live_mark_age_hours,
        "live_mark_reason_codes": list(ctx.live_mark_reason_codes),
        "stop_loss": ctx.stop_loss,
        "tp_price": ctx.tp_price,
        "leverage": ctx.leverage,
        "currency": ctx.currency,
        "country": ctx.country,
        "status": ctx.trade_state,
        "trade_state": ctx.trade_state,
        "partial_tp_logged": ctx.partial_tp_logged,
        "booked_pct": ctx.booked_pct,
        "ride_pct": ctx.ride_pct,
        "money_allocated": ctx.money_allocated,
        "quantity": ctx.quantity,
        "age_days": ctx.days_open,
        "days_open": ctx.days_open,
        "expected_horizon_days": ctx.expected_horizon_days,
        "expected_horizon": ctx.expected_horizon_days,
        "source_health": _lifecycle_source_health(ctx.source_health),
        "opened_at": ctx.opened_at,
        "last_updated_at": ctx.last_updated_at,
        "thesis": ctx.thesis,
        "entry_reason": ctx.entry_reason,
        "risk_reason": ctx.risk_reason,
        "exit_plan": ctx.exit_plan,
        "ai_model_used": ctx.ai_model_used,
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def _lifecycle_source_health(label: str) -> str:
    """Map our PositionContext source label onto the source_health
    values the lifecycle classifier already understands.

    The classifier blocks on UNVERIFIED / STATIC_FALLBACK / MISSING.
    DB / manual log / verified holdings are operator-verified inputs,
    so they map to LIVE_VERIFIED.  Fallback maps to STATIC_FALLBACK.
    """
    if label in {SOURCE_CANONICAL_DB, SOURCE_MANUAL_LOG, SOURCE_VERIFIED_HOLDINGS}:
        return "LIVE_VERIFIED"
    if label == SOURCE_RELEASE_FILE:
        return "LIVE_VERIFIED"
    if label == SOURCE_FALLBACK:
        return "STATIC_FALLBACK"
    return "LIVE_VERIFIED"


def merge_position_context(
    holdings: Iterable[dict[str, Any]],
    trade_rows: Iterable[dict[str, Any]],
    live_marks: dict[str, float] | dict[str, LiveMark] | list | None = None,
    *,
    closed_tickers: Iterable[str] | None = None,
    sold_tickers: Iterable[str] | None = None,
    do_not_manage_tickers: Iterable[str] | None = None,
    now_utc: datetime | None = None,
    live_mark_objects: dict[str, LiveMark] | None = None,
) -> list[PositionContext]:
    """Build one PositionContext per OPEN holding row, enriched from
    manual-trade aggregated state and any provided live marks.

    ``live_marks`` may be a legacy ``{ticker: price}`` float map *or* a
    map of LiveMark objects / dicts.  When it carries rich LiveMark
    objects, mechanical usability flows into the position context via
    ``mechanical_live_price_usable`` and ``live_mark_*`` fields.

    Closed / sold / do-not-manage tickers are excluded — they may still
    appear in the canonical OPEN list during a stale transition but the
    closed list wins.
    """
    now = now_utc or datetime.now(timezone.utc)
    aggregated = _build_manual_trade_state(list(trade_rows or []))
    floats_view, rich_view = _normalize_live_marks_input(live_marks)
    if live_mark_objects:
        for key, mark in live_mark_objects.items():
            rich_view[normalize_position_ticker(key)] = mark
            if mark.live_price is not None and key not in floats_view:
                floats_view[normalize_position_ticker(key)] = float(mark.live_price)
    marks = dict(floats_view)
    closed = {normalize_position_ticker(t) for t in (closed_tickers or []) if t}
    sold = {normalize_position_ticker(t) for t in (sold_tickers or []) if t}
    do_not_manage = {
        normalize_position_ticker(t) for t in (do_not_manage_tickers or []) if t
    }

    contexts: list[PositionContext] = []
    seen: set[str] = set()
    for row in holdings or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().upper()
        if status and status not in OPEN_STATUSES:
            continue
        raw_ticker = row.get("ticker") or row.get("symbol")
        normalized = normalize_position_ticker(
            row.get("normalized_ticker") or raw_ticker
        )
        if not normalized:
            continue
        if normalized in seen:
            # Two lots of the same ticker — keep the first as the
            # authoritative row and flag a DUPLICATE_LOTS reason on it.
            for existing in contexts:
                if existing.ticker == normalized:
                    if REASON_DUPLICATE_LOTS not in existing.reason_codes:
                        existing.reason_codes.append(REASON_DUPLICATE_LOTS)
                    extra_qty = _safe_float(row.get("quantity")) or 0.0
                    existing_qty = existing.quantity or 0.0
                    existing.quantity = existing_qty + extra_qty
                    break
            continue
        seen.add(normalized)

        if normalized in closed or normalized in sold or normalized in do_not_manage:
            ctx = _build_closed_context(row, normalized, raw_ticker)
            contexts.append(ctx)
            continue

        ctx = _build_open_context(
            row=row,
            normalized=normalized,
            raw_ticker=raw_ticker,
            manual_state=aggregated.get(normalized),
            live_price=marks.get(normalized),
            live_mark=rich_view.get(normalized),
            now_utc=now,
        )
        contexts.append(ctx)

    return contexts


def _build_closed_context(
    row: dict[str, Any], normalized: str, raw_ticker: Any
) -> PositionContext:
    """Build a context flagged as historical so the lifecycle board
    excludes it from open classification but the operator can still see
    that the row appeared on a stale OPEN list.
    """
    ctx = PositionContext(
        ticker=normalized,
        raw_ticker=str(raw_ticker) if raw_ticker is not None else None,
        economic_exposure_key=normalize_economic_exposure(raw_ticker or normalized),
        theme_buckets=map_theme_buckets(
            raw_ticker or normalized,
            {"country": row.get("country"), "leverage": row.get("leverage")},
        ),
        trade_state="CLOSED",
        source_health=SOURCE_VERIFIED_HOLDINGS,
    )
    ctx.reason_codes.append(REASON_HISTORICAL_NOT_OPEN)
    score, label, missing = compute_context_quality(ctx)
    ctx.context_quality_score = round(score, 4)
    ctx.context_quality = label
    ctx.missing_fields = missing
    return ctx


def _build_open_context(
    *,
    row: dict[str, Any],
    normalized: str,
    raw_ticker: Any,
    manual_state: dict[str, Any] | None,
    live_price: float | None,
    now_utc: datetime,
    live_mark: LiveMark | None = None,
) -> PositionContext:
    raw_ticker_str = str(raw_ticker) if raw_ticker is not None else None
    metadata = {
        "country": row.get("country"),
        "leverage": row.get("leverage"),
        "sector": row.get("sector"),
    }
    ctx = PositionContext(
        ticker=normalized,
        raw_ticker=raw_ticker_str,
        economic_exposure_key=normalize_economic_exposure(raw_ticker_str or normalized),
        theme_buckets=map_theme_buckets(raw_ticker_str or normalized, metadata),
    )

    holdings_source = SOURCE_VERIFIED_HOLDINGS
    manual_source_present = False

    # 1. Take everything we can from the canonical OPEN row.
    ctx.trade_state = str(row.get("status") or "OPEN").upper() or "OPEN"
    ctx.buy_price = _safe_float(row.get("entry_price") or row.get("buy_price"))
    ctx.quantity = _safe_float(row.get("quantity"))
    leverage_value = _safe_float(row.get("leverage"))
    currency_value = row.get("currency")
    ctx.country = row.get("country")
    ctx.opened_at = row.get("opened_at") or row.get("entry_date")
    ctx.last_updated_at = row.get("last_updated_at") or ctx.opened_at
    # The holdings dict may carry pre-populated stop / tp / live values
    # (operator may maintain them outside the SQLite trade log) — pick
    # them up so the merge does not blindly null them out.
    holding_stop = _safe_float(row.get("stop_loss"))
    if holding_stop is not None:
        ctx.stop_loss = holding_stop
    holding_tp = _safe_float(
        row.get("tp_price") or row.get("take_profit_price") or row.get("take_profit")
    )
    if holding_tp is not None:
        ctx.tp_price = holding_tp
    holding_live = _safe_float(row.get("live_price") or row.get("current_price"))
    if holding_live is not None:
        ctx.live_price = holding_live

    # 2. Layer in manual-trade aggregated state.
    if manual_state:
        manual_source_present = True
        if ctx.buy_price is None and manual_state.get("last_buy_price") is not None:
            ctx.buy_price = manual_state["last_buy_price"]
        if leverage_value is None and manual_state.get("leverage") is not None:
            leverage_value = _safe_float(manual_state.get("leverage"))
        if not currency_value and manual_state.get("currency"):
            currency_value = manual_state.get("currency")
        ctx.thesis = manual_state.get("thesis")
        ctx.entry_reason = manual_state.get("entry_reason")
        ctx.risk_reason = manual_state.get("risk_reason")
        ctx.exit_plan = manual_state.get("exit_plan")
        ctx.ai_model_used = manual_state.get("ai_model_used")
        if manual_state.get("stop_loss") is not None:
            ctx.stop_loss = float(manual_state["stop_loss"])
        if manual_state.get("tp_price") is not None:
            ctx.tp_price = float(manual_state["tp_price"])
        if manual_state.get("expected_horizon_days") is not None:
            ctx.expected_horizon_days = float(manual_state["expected_horizon_days"])
        if manual_state.get("last_executed_at"):
            ctx.last_updated_at = manual_state["last_executed_at"]
        if manual_state.get("first_executed_at") and not ctx.opened_at:
            ctx.opened_at = manual_state["first_executed_at"]
        if manual_state.get("sell_count", 0) > 0 and manual_state.get(
            "net_quantity", 0.0
        ) > 0:
            ctx.partial_tp_logged = True
            try:
                booked = float(manual_state.get("sell_quantity") or 0.0)
                bought = float(manual_state.get("buy_quantity") or 0.0)
                if bought > 0:
                    ctx.booked_pct = round(_clamp(booked / bought * 100.0, 0.0, 100.0), 2)
                    ctx.ride_pct = round(max(0.0, 100.0 - ctx.booked_pct), 2)
            except (TypeError, ValueError):
                pass

    # 3. Live mark, if any.
    legacy_live = _safe_float(live_price) if live_price is not None else None
    if live_mark is not None:
        # Rich LiveMark — flow mechanical usability and provenance.
        ctx.display_live_price = _safe_float(live_mark.live_price)
        ctx.mechanical_live_price_usable = bool(live_mark.is_usable)
        if live_mark.is_usable and live_mark.live_price is not None:
            ctx.live_price = float(live_mark.live_price)
        else:
            ctx.live_price = None
        ctx.live_mark_quality_score = (
            round(float(live_mark.live_mark_quality_score), 4)
            if live_mark.live_mark_quality_score is not None
            else None
        )
        ctx.live_mark_source = live_mark.provider or None
        ctx.live_mark_source_health = live_mark.source_health or None
        ctx.live_mark_age_hours = (
            float(live_mark.age_hours)
            if live_mark.age_hours is not None
            else None
        )
        ctx.live_mark_reason_codes = list(live_mark.reason_codes)
    else:
        # Legacy float-only mark — treat as usable when present
        # (callers that don't know about LiveMark stay backwards
        # compatible).
        ctx.live_price = legacy_live
        ctx.display_live_price = legacy_live
        ctx.mechanical_live_price_usable = legacy_live is not None
        ctx.live_mark_quality_score = None
        ctx.live_mark_source = None
        ctx.live_mark_source_health = None
        ctx.live_mark_age_hours = None
        ctx.live_mark_reason_codes = []

    # 4. money_allocated = buy_price × quantity (when both known).
    if ctx.buy_price is not None and ctx.quantity is not None:
        ctx.money_allocated = round(ctx.buy_price * ctx.quantity, 4)

    # 5. Leverage / currency normalisation + reason codes.
    if leverage_value is None or leverage_value <= 0:
        ctx.leverage = 1.0
        ctx.reason_codes.append(REASON_LEVERAGE_DEFAULTED)
    else:
        ctx.leverage = float(leverage_value)

    if currency_value:
        currency_text = str(currency_value).strip().upper()
        if currency_text in {"", "UNKNOWN", "NONE"}:
            ctx.currency = "UNKNOWN"
            ctx.reason_codes.append(REASON_CURRENCY_UNKNOWN)
        else:
            ctx.currency = currency_text
    else:
        ctx.currency = "UNKNOWN"
        ctx.reason_codes.append(REASON_CURRENCY_UNKNOWN)

    # 6. days_open.
    opened_dt = _parse_iso_dt(ctx.opened_at)
    ctx.days_open = _days_between(now_utc, opened_dt)

    # 7. Source provenance reason codes (one per contributing source).
    ctx.reason_codes.append(REASON_CONTEXT_FROM_VERIFIED_HOLDINGS)
    if manual_source_present:
        ctx.source_health = SOURCE_MANUAL_LOG
        ctx.reason_codes.append(REASON_CONTEXT_FROM_MANUAL_LOG)
        ctx.reason_codes.append(REASON_CONTEXT_MERGED)
    else:
        ctx.source_health = holdings_source

    # 8. Live mark provenance.
    if live_mark is not None:
        if live_mark.is_usable:
            ctx.reason_codes.append(REASON_LIVE_MARK_MERGED)
            if live_mark.provider == "existing_yfinance_provider":
                ctx.reason_codes.append(REASON_LIVE_MARK_FROM_YFINANCE)
            elif live_mark.provider == "today_market_snapshot":
                ctx.reason_codes.append(REASON_LIVE_MARK_FROM_SNAPSHOT)
            elif live_mark.provider == "canonical_db_live_mark":
                ctx.reason_codes.append(REASON_LIVE_MARK_FROM_DB)
            elif live_mark.provider == "release_summary":
                ctx.reason_codes.append(REASON_LIVE_MARK_FROM_RELEASE)
        else:
            if live_mark.live_price is None:
                ctx.reason_codes.append(REASON_LIVE_MARK_MISSING)
            elif live_mark.is_stale:
                ctx.reason_codes.append(REASON_LIVE_MARK_STALE)
            else:
                ctx.reason_codes.append(REASON_LIVE_MARK_UNUSABLE)
    elif ctx.live_price is None:
        ctx.reason_codes.append(REASON_LIVE_MARK_MISSING)

    # 9. Soft thesis-context missing → reason code only (does NOT block).
    if not (ctx.thesis or ctx.entry_reason or ctx.risk_reason):
        ctx.reason_codes.append(REASON_THESIS_CONTEXT_MISSING)

    # 10. Quality math.
    score, label, missing = compute_context_quality(ctx)
    ctx.context_quality_score = round(score, 4)
    ctx.context_quality = label
    ctx.missing_fields = missing

    return ctx


def load_position_context(
    *,
    db_path: Path | None = None,
    holdings_path: Path | None = None,
    manual_trade_path: Path | None = None,
    release_dir: Path | None = None,
    live_marks: dict | list | None = None,
    live_mark_result: LiveMarkResult | None = None,
    fetch_live_marks_if_missing: bool = True,
    allow_network: bool = True,
    live_mark_fetcher: Any = None,
    now_utc: datetime | None = None,
) -> PositionContextResult:
    """Top-level loader.

    Pulls verified_current_holdings.json + the manual_trades SQLite
    table + any live marks we can find, merges them via
    ``merge_position_context``, and returns a result bag plus
    aggregated diagnostics for the summary writer.

    Live mark behaviour:
      * If ``live_marks`` / ``live_mark_result`` are explicitly passed,
        they win and no auto-fetch is attempted.
      * Else if ``fetch_live_marks_if_missing`` is true, the loader calls
        :func:`scripts.live_price_marks.fetch_live_marks` to resolve
        open-position tickers.  Tests should pass
        ``allow_network=False`` and an explicit ``live_mark_fetcher`` or
        rely on cached snapshot/release/DB sources.
    """
    holdings_payload = load_verified_holdings(holdings_path)
    holdings_rows = list(holdings_payload.get("positions") or [])

    closed_payload = load_closed_positions()
    sold_payload = load_sold_positions()
    dnm_payload = load_do_not_treat_as_open()

    market_snapshot = load_market_snapshot()

    db_path_resolved = Path(db_path) if db_path else DEFAULT_DB_PATH
    trade_path_resolved = (
        Path(manual_trade_path) if manual_trade_path else db_path_resolved
    )
    trade_rows = _read_manual_trade_rows(trade_path_resolved)

    # Build legacy float view from explicit caller marks + holdings + snapshot.
    explicit_floats: dict[str, float] = {}
    explicit_rich: dict[str, LiveMark] = {}
    if live_marks is not None:
        explicit_floats, explicit_rich = _normalize_live_marks_input(live_marks)
    legacy_marks = _build_live_marks(
        holdings_rows=holdings_rows,
        market_snapshot=market_snapshot,
        explicit_live_marks=explicit_floats,
    )

    lm_result: LiveMarkResult | None = live_mark_result
    rich_view: dict[str, LiveMark] = dict(explicit_rich)
    if (
        lm_result is None
        and not explicit_rich
        and fetch_live_marks_if_missing
    ):
        open_keys: list[str] = []
        ticker_meta: dict[str, dict[str, Any]] = {}
        closed_set = {normalize_position_ticker(t) for t in (closed_payload.get("closed_tickers") or []) if t}
        sold_set = {normalize_position_ticker(t) for t in (sold_payload.get("tickers") or []) if t}
        dnm_set = {normalize_position_ticker(t) for t in (dnm_payload.get("all_tickers") or []) if t}
        for row in holdings_rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().upper()
            if status and status not in OPEN_STATUSES:
                continue
            raw_ticker = (
                row.get("ticker")
                or row.get("symbol")
                or row.get("normalized_ticker")
            )
            key = normalize_position_ticker(
                row.get("normalized_ticker") or raw_ticker
            )
            if not key:
                continue
            if key in closed_set or key in sold_set or key in dnm_set:
                continue
            if key not in open_keys:
                open_keys.append(key)
                ticker_meta[key] = {
                    "country": row.get("country"),
                    "currency": row.get("currency"),
                    "raw_ticker": str(raw_ticker) if raw_ticker is not None else key,
                }
        if open_keys:
            try:
                lm_result = _fetch_live_marks(
                    open_keys,
                    db_path=db_path_resolved,
                    release_dir=release_dir,
                    market_snapshot=market_snapshot,
                    now_utc=now_utc,
                    allow_network=allow_network,
                    fetcher=live_mark_fetcher,
                    ticker_metadata=ticker_meta,
                )
            except Exception:  # pragma: no cover — defensive
                lm_result = None

    if lm_result is not None:
        rich_from_result = _marks_from_live_mark_result(lm_result)
        for key, mark in rich_from_result.items():
            rich_view.setdefault(key, mark)

    contexts = merge_position_context(
        holdings=holdings_rows,
        trade_rows=trade_rows,
        live_marks=legacy_marks,
        live_mark_objects=rich_view,
        closed_tickers=closed_payload.get("closed_tickers"),
        sold_tickers=sold_payload.get("tickers"),
        do_not_manage_tickers=dnm_payload.get("all_tickers"),
        now_utc=now_utc,
    )

    source_counts: dict[str, int] = {label: 0 for label in ALL_SOURCE_HEALTH}
    quality_counts: dict[str, int] = {label: 0 for label in ALL_CONTEXT_QUALITY}
    aggregated_reasons: set[str] = set()
    open_count = 0
    for ctx in contexts:
        source_counts[ctx.source_health] = source_counts.get(ctx.source_health, 0) + 1
        quality_counts[ctx.context_quality] = (
            quality_counts.get(ctx.context_quality, 0) + 1
        )
        aggregated_reasons.update(ctx.reason_codes)
        if ctx.trade_state in OPEN_STATUSES or ctx.trade_state == "OPEN":
            open_count += 1

    return PositionContextResult(
        contexts=contexts,
        source_counts=source_counts,
        quality_counts=quality_counts,
        reason_codes=sorted(aggregated_reasons),
        open_positions_loaded=open_count,
        db_available=trade_path_resolved.exists(),
        holdings_present=bool(holdings_payload.get("present")),
        live_mark_result=lm_result,
    )


__all__ = [
    "CONTEXT_COMPLETE",
    "CONTEXT_USABLE",
    "CONTEXT_PARTIAL",
    "CONTEXT_INSUFFICIENT",
    "ALL_CONTEXT_QUALITY",
    "SOURCE_CANONICAL_DB",
    "SOURCE_MANUAL_LOG",
    "SOURCE_RELEASE_FILE",
    "SOURCE_VERIFIED_HOLDINGS",
    "SOURCE_FALLBACK",
    "ALL_SOURCE_HEALTH",
    "REASON_LIVE_MARK_STALE",
    "REASON_LIVE_MARK_MISSING",
    "REASON_LIVE_MARK_MERGED",
    "REASON_LIVE_MARK_UNUSABLE",
    "REASON_LIVE_MARK_PROVIDER_DISAGREEMENT",
    "REASON_LIVE_MARK_FROM_YFINANCE",
    "REASON_LIVE_MARK_FROM_SNAPSHOT",
    "REASON_LIVE_MARK_FROM_DB",
    "REASON_LIVE_MARK_FROM_RELEASE",
    "REASON_CONTEXT_FROM_FALLBACK",
    "REASON_CONTEXT_FROM_CANONICAL_DB",
    "REASON_CONTEXT_FROM_MANUAL_LOG",
    "REASON_CONTEXT_FROM_VERIFIED_HOLDINGS",
    "REASON_CONTEXT_MERGED",
    "REASON_THESIS_CONTEXT_MISSING",
    "REASON_LEVERAGE_DEFAULTED",
    "REASON_CURRENCY_UNKNOWN",
    "REASON_HISTORICAL_NOT_OPEN",
    "REASON_DUPLICATE_LOTS",
    "PositionContext",
    "PositionContextResult",
    "normalize_position_ticker",
    "compute_context_quality",
    "merge_position_context",
    "position_context_to_lifecycle_input",
    "load_position_context",
]
