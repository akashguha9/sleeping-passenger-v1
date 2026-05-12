"""
Chart-structure symbol bootstrap — discovery + OHLCV backfill helper.

Used by POST /chart-structure/bootstrap-symbol so the UI can offer a one-click
"download data" action when local OHLCV is missing for a symbol the user
asked Chart Structure to render.

Strictly advisory and read-only with respect to the market:
  - Discovers metadata via yfinance (no broker API, no key)
  - Backfills historical candles via yfinance (no broker API, no key)
  - Writes into the local SQLite `global_securities` + `signal_events` tables only
  - Never places, routes, or submits an order
  - Never connects to any broker, wallet, or signing endpoint
  - Never increments ai_execution_count

Safety invariants in every response:
  advisory_status     = "ADVISORY_ONLY"
  execution_mode      = "HUMAN_ONLY"
  execution_gate      = "LOCKED"
  broker_api_called   = False
  broker_order_id     = "NONE"
  ai_execution_count  = 0
  human_review_required = True
"""
from __future__ import annotations

import re
from typing import Any

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0

# Allowed: A-Z 0-9 . - _ : ^   (covers AAPL, BTC-USD, RELIANCE.NS, ^GSPC, BRK.B)
_SYMBOL_RE = re.compile(r"^[A-Z0-9._\-:\^]{1,30}$")

_ALLOWED_PERIODS = {
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max",
}
_ALLOWED_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m",
    "1h", "1d", "5d", "1wk", "1mo", "3mo",
}


def _safe_base() -> dict[str, Any]:
    return {
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": _EXECUTION_GATE,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
    }


def normalize_symbol(symbol: str) -> str:
    """Trim + uppercase. Does not validate — call validate_symbol after."""
    if symbol is None:
        return ""
    return str(symbol).strip().upper()


def validate_symbol(symbol: str) -> tuple[bool, str]:
    """Return (ok, reason). Reason is empty on success."""
    if not symbol:
        return False, "symbol must be a non-empty string"
    if len(symbol) > 30:
        return False, "symbol is too long"
    if not _SYMBOL_RE.match(symbol):
        return False, "symbol contains invalid characters"
    return True, ""


def _sanitize_error(text: str) -> str:
    """Trim + redact obvious secret-like tokens. Never expose tracebacks raw."""
    if not text:
        return ""
    out = str(text).strip().splitlines()[0]
    if len(out) > 240:
        out = out[:240] + "…"
    out = re.sub(
        r"(?i)(api[_-]?key|token|secret|bearer)\s*[=:\s]\s*\S+",
        r"\1=<redacted>",
        out,
    )
    return out


def bootstrap_symbol(
    symbol: str,
    period: str = "max",
    interval: str = "1d",
    *,
    discovery_fn=None,
    backfill_fn=None,
    db_path=None,
) -> dict[str, Any]:
    """Run discovery + OHLCV backfill for *symbol*.

    Returns a structured advisory dict — never raises to callers.

    Parameters
    ----------
    discovery_fn, backfill_fn : optional injected callables for testing.
        - discovery_fn(symbols, *, write, db_path) -> list[dict]
        - backfill_fn(symbol, *, period, interval, write, db_path) -> (fetched, inserted)
    """
    base = _safe_base()
    sym = normalize_symbol(symbol)

    ok, reason = validate_symbol(sym)
    if not ok:
        return {
            **base,
            "ok": False,
            "symbol": sym,
            "period": period,
            "interval": interval,
            "discovery_status": "SKIPPED",
            "backfill_status": "SKIPPED",
            "candles_written": None,
            "message": f"Invalid symbol: {reason}",
        }

    if period not in _ALLOWED_PERIODS:
        return {
            **base,
            "ok": False,
            "symbol": sym,
            "period": period,
            "interval": interval,
            "discovery_status": "SKIPPED",
            "backfill_status": "SKIPPED",
            "candles_written": None,
            "message": f"Invalid period: {period!r}",
        }
    if interval not in _ALLOWED_INTERVALS:
        return {
            **base,
            "ok": False,
            "symbol": sym,
            "period": period,
            "interval": interval,
            "discovery_status": "SKIPPED",
            "backfill_status": "SKIPPED",
            "candles_written": None,
            "message": f"Invalid interval: {interval!r}",
        }

    # --- 1. Discovery -------------------------------------------------------
    discovery_status = "SKIPPED"
    discovery_msg = ""
    if discovery_fn is None:
        try:
            try:
                from scripts.global_security_master_discovery import discover_and_upsert
            except ModuleNotFoundError:
                from global_security_master_discovery import discover_and_upsert  # type: ignore[no-redef]
            discovery_fn = discover_and_upsert
        except Exception as exc:
            discovery_fn = None
            discovery_status = "ERROR"
            discovery_msg = f"discovery import failed: {_sanitize_error(str(exc))}"

    if discovery_fn is not None:
        try:
            results = discovery_fn([sym], write=True, db_path=db_path)
            if results and isinstance(results, list):
                first = results[0] or {}
                if first.get("db_error"):
                    discovery_status = "ERROR"
                    discovery_msg = _sanitize_error(str(first.get("db_error")))
                else:
                    discovery_status = "OK"
                    discovery_msg = f"discovery: {first.get('db_action', 'ok')}"
            else:
                discovery_status = "OK"
                discovery_msg = "discovery: ok"
        except Exception as exc:
            discovery_status = "ERROR"
            discovery_msg = _sanitize_error(str(exc))

    # --- 2. Backfill --------------------------------------------------------
    backfill_status = "SKIPPED"
    backfill_msg = ""
    fetched = 0
    inserted = 0
    if backfill_fn is None:
        try:
            try:
                from scripts.backfill_global_ohlcv import backfill_symbol as _bf
            except ModuleNotFoundError:
                from backfill_global_ohlcv import backfill_symbol as _bf  # type: ignore[no-redef]
            backfill_fn = _bf
        except Exception as exc:
            backfill_fn = None
            backfill_status = "ERROR"
            backfill_msg = f"backfill import failed: {_sanitize_error(str(exc))}"

    if backfill_fn is not None:
        try:
            result = backfill_fn(
                sym,
                period=period,
                interval=interval,
                write=True,
                db_path=db_path,
                discover=False,  # we already ran discovery above
            )
            if isinstance(result, tuple) and len(result) >= 2:
                fetched = int(result[0] or 0)
                inserted = int(result[1] or 0)
            backfill_status = "OK" if fetched > 0 else "SKIPPED"
            backfill_msg = f"fetched={fetched} inserted={inserted}"
        except TypeError:
            # Older signatures without keyword args — fall back to positional.
            try:
                result = backfill_fn(sym, period, interval, True, db_path)
                if isinstance(result, tuple) and len(result) >= 2:
                    fetched = int(result[0] or 0)
                    inserted = int(result[1] or 0)
                backfill_status = "OK" if fetched > 0 else "SKIPPED"
                backfill_msg = f"fetched={fetched} inserted={inserted}"
            except Exception as exc:
                backfill_status = "ERROR"
                backfill_msg = _sanitize_error(str(exc))
        except Exception as exc:
            backfill_status = "ERROR"
            backfill_msg = _sanitize_error(str(exc))

    overall_ok = (
        discovery_status in {"OK", "SKIPPED"}
        and backfill_status == "OK"
        and fetched > 0
    )

    if overall_ok:
        msg = (
            f"Downloaded {fetched} OHLCV candles for {sym} "
            f"(period={period}, interval={interval}). {inserted} new rows persisted."
        )
    else:
        bits = []
        if discovery_msg:
            bits.append(discovery_msg)
        if backfill_msg:
            bits.append(backfill_msg)
        msg = "; ".join(bits) or (
            f"Could not download OHLCV for {sym}. "
            f"Check the symbol or yfinance availability."
        )

    return {
        **base,
        "ok": bool(overall_ok),
        "symbol": sym,
        "period": period,
        "interval": interval,
        "discovery_status": discovery_status,
        "backfill_status": backfill_status,
        "candles_written": int(inserted),
        "candles_fetched": int(fetched),
        "message": msg,
    }


__all__ = [
    "bootstrap_symbol",
    "normalize_symbol",
    "validate_symbol",
]
