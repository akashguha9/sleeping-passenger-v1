"""OHLCV import contract — validation + provenance for historical price bars.

Imported OHLCV is read-only historical data. It never implies broker
connectivity, order placement, or execution. Synthetic price data may be used
ONLY in tests and is rejected from runtime imports.

Pure module (no DB, no network, no broker). Importing has no side effects.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

REQUIRED_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "volume", "source")
OPTIONAL_COLUMNS = (
    "currency", "exchange", "adjusted_close", "data_vendor",
    "downloaded_at", "corporate_action_adjusted",
)

# Price provenance vocabulary.
YFINANCE_IMPORTED = "YFINANCE_IMPORTED"
BROKER_EXPORT = "BROKER_EXPORT"
MANUAL_CSV_IMPORT = "MANUAL_CSV_IMPORT"
VENDOR_CSV_IMPORT = "VENDOR_CSV_IMPORT"
SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"

_RUNTIME_PROVENANCE = {
    YFINANCE_IMPORTED, BROKER_EXPORT, MANUAL_CSV_IMPORT, VENDOR_CSV_IMPORT,
}
_ALL_PROVENANCE = _RUNTIME_PROVENANCE | {SYNTHETIC_FIXTURE}

_ADVISORY_STAMPS = {
    "advisory_only": "ADVISORY_ONLY",
    "human_execution_required": True,
    "broker_api_called": False,
}


def parse_date(raw: Any) -> str | None:
    """Accept ISO (YYYY-MM-DD), full ISO timestamps, or DD-MM-YYYY. Returns
    a normalised YYYY-MM-DD string, or None when unparseable."""
    s = str(raw or "").strip()
    if not s:
        return None
    # Full ISO timestamp -> take the date.
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Last resort: ISO prefix.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_row(row: dict[str, Any], *, runtime_mode: bool = True) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Validate one OHLCV row. Returns (ok, reason, normalised_row).

    In runtime_mode, SYNTHETIC_FIXTURE provenance is rejected. The OHLCV
    geometry (high/low bounds) and positivity are enforced; bad rows never
    reach the store.
    """
    ticker = str(row.get("ticker", "")).strip().upper()
    if not ticker:
        return False, "empty_ticker", None
    source = str(row.get("source", "")).strip()
    if not source:
        return False, "missing_source", None

    provenance = str(row.get("price_provenance", row.get("provenance", source))).strip().upper()
    # If the source itself names a provenance, honour it; else treat source as a label.
    declared = provenance if provenance in _ALL_PROVENANCE else None
    if declared == SYNTHETIC_FIXTURE and runtime_mode:
        return False, "synthetic_fixture_rejected_in_runtime", None

    date = parse_date(row.get("date"))
    if date is None:
        return False, "unparseable_date", None

    o, h, lo, c = _num(row.get("open")), _num(row.get("high")), _num(row.get("low")), _num(row.get("close"))
    if None in (o, h, lo, c):
        return False, "missing_price", None
    if min(o, h, lo, c) <= 0:
        return False, "non_positive_price", None
    if h < max(o, c, lo):
        return False, "high_below_body", None
    if lo > min(o, c, h):
        return False, "low_above_body", None
    vol = _num(row.get("volume"))
    if vol is None or vol < 0:
        return False, "bad_volume", None

    normalised = {
        "ticker": ticker,
        "date": date,
        "open": o, "high": h, "low": lo, "close": c,
        "adjusted_close": _num(row.get("adjusted_close")),
        "volume": vol,
        "source": source,
        "data_vendor": str(row.get("data_vendor", "")).strip(),
        "exchange": str(row.get("exchange", "")).strip(),
        "currency": str(row.get("currency", "")).strip().upper(),
        "corporate_action_adjusted": _truthy(row.get("corporate_action_adjusted")),
        "downloaded_at": str(row.get("downloaded_at", "")).strip(),
    }
    return True, None, normalised


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def validate_rows(rows: list[dict[str, Any]], *, runtime_mode: bool = True) -> dict[str, Any]:
    """Validate a batch; returns accepted rows + per-row rejections."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        ok, reason, norm = validate_row(r, runtime_mode=runtime_mode)
        if ok and norm is not None:
            accepted.append(norm)
        else:
            rejected.append({"row_index": i, "reason": reason, "ticker": r.get("ticker")})
    return {
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        **_ADVISORY_STAMPS,
    }


__all__ = [
    "REQUIRED_COLUMNS", "OPTIONAL_COLUMNS",
    "YFINANCE_IMPORTED", "BROKER_EXPORT", "MANUAL_CSV_IMPORT",
    "VENDOR_CSV_IMPORT", "SYNTHETIC_FIXTURE",
    "parse_date", "validate_row", "validate_rows",
]
