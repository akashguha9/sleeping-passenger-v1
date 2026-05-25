"""Daily payload loader for the five-model synthesis pipeline.

This module is the single, schema-aware entry point for the expanded daily
payload that feeds the five-model synthesis. It loads the nine payload files
under ``data/daily_payload/`` and exposes them as normalized Python objects.

Design rules (mirrors ``position_truth_resolver`` conventions):
    * Never mutate any payload file.
    * Never fabricate data — missing files degrade to safe empty defaults.
    * Ticker normalization is centralized here so every downstream gate
      compares the same canonical symbol (``NYSE:ZIM`` -> ``ZIM``).
    * Pure module: importing has no side effects beyond reading JSON.

The payload is the *input* to the Portfolio Truth Gate, Fresh Market
Discovery Gate, Candidate/Executable split, and Anti-staleness layers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT, repo_relative
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT, repo_relative


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"

VERIFIED_HOLDINGS_PATH = DAILY_PAYLOAD_DIR / "verified_current_holdings.json"
CLOSED_POSITIONS_PATH = DAILY_PAYLOAD_DIR / "closed_positions.json"
SOLD_POSITIONS_PATH = DAILY_PAYLOAD_DIR / "sold_positions.json"
DO_NOT_TREAT_AS_OPEN_PATH = DAILY_PAYLOAD_DIR / "do_not_treat_as_open.json"
MARKET_SNAPSHOT_PATH = DAILY_PAYLOAD_DIR / "today_market_snapshot.json"
PRICE_MOVERS_PATH = DAILY_PAYLOAD_DIR / "today_price_movers.json"
NEWS_EVENTS_PATH = DAILY_PAYLOAD_DIR / "today_news_events.json"
FILINGS_EVENTS_PATH = DAILY_PAYLOAD_DIR / "today_filings_events.json"
YESTERDAY_CANDIDATES_PATH = DAILY_PAYLOAD_DIR / "yesterday_final_candidates.json"

# The nine canonical payload files, in the order the pipeline reads them.
DAILY_PAYLOAD_FILES: tuple[str, ...] = (
    "verified_current_holdings.json",
    "closed_positions.json",
    "sold_positions.json",
    "do_not_treat_as_open.json",
    "today_market_snapshot.json",
    "today_price_movers.json",
    "today_news_events.json",
    "today_filings_events.json",
    "yesterday_final_candidates.json",
)

OPEN_STATUSES = {"OPEN", "REDUCED", "ADD", "PARTIAL_OPEN"}
CLOSED_STATUSES = {"CLOSED", "EXITED", "SOLD"}


def normalize_ticker(value: Any) -> str:
    """Return the canonical comparison form of a ticker.

    Rules:
        * uppercase + strip whitespace
        * drop an exchange prefix before a colon (``NYSE:ZIM`` -> ``ZIM``)
        * preserve country suffixes such as ``.NS`` (Indian equities) because
          they distinguish venues that matter for sizing/leverage policy.
    """
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if ":" in text:
        text = text.rsplit(":", 1)[-1].strip()
    return text


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return default
    if not raw.strip():
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _normalized_holding_ticker(row: dict[str, Any]) -> str:
    explicit = str(row.get("normalized_ticker") or "").strip().upper()
    if explicit:
        return explicit
    return normalize_ticker(row.get("ticker") or row.get("symbol"))


def load_verified_holdings(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or VERIFIED_HOLDINGS_PATH, default={})
    positions = payload.get("positions") if isinstance(payload, dict) else None
    rows = [row for row in positions or [] if isinstance(row, dict)]
    open_tickers: list[str] = []
    for row in rows:
        if str(row.get("status") or "").strip().upper() in OPEN_STATUSES:
            ticker = _normalized_holding_ticker(row)
            if ticker and ticker not in open_tickers:
                open_tickers.append(ticker)
    return {
        "present": (path or VERIFIED_HOLDINGS_PATH).exists(),
        "run_date": payload.get("run_date") if isinstance(payload, dict) else None,
        "positions": rows,
        "open_tickers": open_tickers,
    }


def load_closed_positions(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or CLOSED_POSITIONS_PATH, default={})
    positions = payload.get("positions") if isinstance(payload, dict) else None
    rows = [row for row in positions or [] if isinstance(row, dict)]
    closed_tickers: list[str] = []
    for row in rows:
        status = str(row.get("status") or "").strip().upper()
        if status in CLOSED_STATUSES or not status:
            ticker = _normalized_holding_ticker(row)
            if ticker and ticker not in closed_tickers:
                closed_tickers.append(ticker)
    return {
        "present": (path or CLOSED_POSITIONS_PATH).exists(),
        "positions": rows,
        "closed_tickers": closed_tickers,
    }


def load_sold_positions(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or SOLD_POSITIONS_PATH, default={})
    tickers_raw = payload.get("tickers") if isinstance(payload, dict) else None
    sold_tickers: list[str] = []
    for value in tickers_raw or []:
        ticker = normalize_ticker(value)
        if ticker and ticker not in sold_tickers:
            sold_tickers.append(ticker)
    return {
        "present": (path or SOLD_POSITIONS_PATH).exists(),
        "tickers": sold_tickers,
    }


def load_do_not_treat_as_open(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or DO_NOT_TREAT_AS_OPEN_PATH, default={})
    payload = payload if isinstance(payload, dict) else {}

    def _norm_list(key: str) -> list[str]:
        out: list[str] = []
        for value in payload.get(key) or []:
            ticker = normalize_ticker(value)
            if ticker and ticker not in out:
                out.append(ticker)
        return out

    not_owned = _norm_list("not_owned_do_not_manage")
    closed_or_sold = _norm_list("closed_or_sold_positions")
    union: list[str] = []
    for ticker in not_owned + closed_or_sold:
        if ticker not in union:
            union.append(ticker)
    return {
        "present": (path or DO_NOT_TREAT_AS_OPEN_PATH).exists(),
        "not_owned_do_not_manage": not_owned,
        "closed_or_sold_positions": closed_or_sold,
        "all_tickers": union,
        "operator_note": str(payload.get("operator_note") or ""),
    }


def _tickers_from_rows(rows: Any, keys: tuple[str, ...] = ("ticker", "symbol")) -> list[str]:
    out: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in keys:
            ticker = normalize_ticker(row.get(key))
            if ticker:
                if ticker not in out:
                    out.append(ticker)
                break
    return out


def load_price_movers(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or PRICE_MOVERS_PATH, default={})
    movers = payload.get("movers") if isinstance(payload, dict) else None
    rows = [row for row in movers or [] if isinstance(row, dict)]
    return {"present": (path or PRICE_MOVERS_PATH).exists(), "movers": rows, "tickers": _tickers_from_rows(rows)}


def load_news_events(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or NEWS_EVENTS_PATH, default={})
    events = payload.get("events") if isinstance(payload, dict) else None
    rows = [row for row in events or [] if isinstance(row, dict)]
    return {"present": (path or NEWS_EVENTS_PATH).exists(), "events": rows, "tickers": _tickers_from_rows(rows)}


def load_filings_events(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or FILINGS_EVENTS_PATH, default={})
    events = payload.get("events") if isinstance(payload, dict) else None
    rows = [row for row in events or [] if isinstance(row, dict)]
    return {"present": (path or FILINGS_EVENTS_PATH).exists(), "events": rows, "tickers": _tickers_from_rows(rows)}


def load_market_snapshot(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or MARKET_SNAPSHOT_PATH, default={})
    payload = payload if isinstance(payload, dict) else {}
    return {
        "present": (path or MARKET_SNAPSHOT_PATH).exists(),
        "source_health": str(payload.get("source_health") or "MISSING_OR_UNVERIFIED"),
        "snapshot_timestamp_utc": payload.get("snapshot_timestamp_utc"),
        "indices": payload.get("indices") or [],
        "rates": payload.get("rates") or [],
        "commodities": payload.get("commodities") or [],
        "fx": payload.get("fx") or [],
        "regime_notes": payload.get("regime_notes") or [],
    }


def load_yesterday_candidates(path: Path | None = None) -> dict[str, Any]:
    payload = _load(path or YESTERDAY_CANDIDATES_PATH, default={})
    payload = payload if isinstance(payload, dict) else {}

    def _norm_list(key: str) -> list[str]:
        out: list[str] = []
        for value in payload.get(key) or []:
            ticker = normalize_ticker(value)
            if ticker and ticker not in out:
                out.append(ticker)
        return out

    return {
        "present": (path or YESTERDAY_CANDIDATES_PATH).exists(),
        "final_candidates": _norm_list("final_candidates"),
        "watchlist": _norm_list("watchlist"),
        "avoids": _norm_list("avoids"),
    }


def load_daily_payload(payload_dir: Path | None = None) -> dict[str, Any]:
    """Load the full daily payload as a single normalized dict.

    When ``payload_dir`` is supplied (tests), every file path is rebased onto
    it so the loaders read the test fixture instead of the committed payload.
    """
    base = payload_dir or DAILY_PAYLOAD_DIR

    def p(name: str) -> Path:
        return base / name

    payload = {
        "payload_dir": repo_relative(base) if base == DAILY_PAYLOAD_DIR else str(base),
        "verified_holdings": load_verified_holdings(p("verified_current_holdings.json")),
        "closed_positions": load_closed_positions(p("closed_positions.json")),
        "sold_positions": load_sold_positions(p("sold_positions.json")),
        "do_not_treat_as_open": load_do_not_treat_as_open(p("do_not_treat_as_open.json")),
        "market_snapshot": load_market_snapshot(p("today_market_snapshot.json")),
        "price_movers": load_price_movers(p("today_price_movers.json")),
        "news_events": load_news_events(p("today_news_events.json")),
        "filings_events": load_filings_events(p("today_filings_events.json")),
        "yesterday_candidates": load_yesterday_candidates(p("yesterday_final_candidates.json")),
    }
    payload["missing_files"] = [
        name for name in DAILY_PAYLOAD_FILES if not (base / name).exists()
    ]
    return payload


__all__ = [
    "DAILY_PAYLOAD_DIR",
    "DAILY_PAYLOAD_FILES",
    "VERIFIED_HOLDINGS_PATH",
    "CLOSED_POSITIONS_PATH",
    "SOLD_POSITIONS_PATH",
    "DO_NOT_TREAT_AS_OPEN_PATH",
    "MARKET_SNAPSHOT_PATH",
    "PRICE_MOVERS_PATH",
    "NEWS_EVENTS_PATH",
    "FILINGS_EVENTS_PATH",
    "YESTERDAY_CANDIDATES_PATH",
    "normalize_ticker",
    "load_verified_holdings",
    "load_closed_positions",
    "load_sold_positions",
    "load_do_not_treat_as_open",
    "load_price_movers",
    "load_news_events",
    "load_filings_events",
    "load_market_snapshot",
    "load_yesterday_candidates",
    "load_daily_payload",
]
