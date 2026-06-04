"""Central leverage governance for the advisory MVP.

Single source of truth for the product's leverage doctrine:

* Indian equities (NSE / BSE / IN) may be evaluated up to **4.0x** leverage
  as a CEILING — never a default.
* Rest-of-world equities are **spot-only** (ceiling 1.0x).
* Unknown jurisdiction fails *closed*: it is treated as spot-only (1.0x), and
  any leverage above 1.0x is flagged as a policy breach — never silently
  accepted.

This module is a **journal validation** layer, not an execution blocker.
Recording a historical / manual trade that breached policy is still allowed —
the row is simply stamped ``leverage_breach=True`` with the policy details so
the operator (and later calibration) can see the breach. Nothing here places,
routes, modifies, or cancels any order. There is no broker call. Importing this
module has no side effects (pure functions, constant data).

Contract — pure module
----------------------
No DB, no filesystem, no network, no broker calls, no AI execution.
``advisory_only`` is always True; ``human_execution_required`` is always True;
``broker_api_called`` is always False.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Doctrine constants — mirror scripts/complex_systems_diagnostics.py so the two
# layers can never silently diverge.  The behavioural test
# tests/test_leverage_governance.py asserts they stay equal.
# ---------------------------------------------------------------------------
INDIA_LEVERAGE_CEILING: float = 4.0
ROW_LEVERAGE_CEILING: float = 1.0
DEFAULT_LEVERAGE: float = 1.0

# Float comparison tolerance so 4.0x logged as 4.0000001 is not a "breach",
# but 4.01x clearly is.
_EPSILON: float = 1e-6

# Jurisdiction groups.
INDIA = "INDIA"
REST_OF_WORLD = "REST_OF_WORLD"
UNKNOWN = "UNKNOWN"

# Severities.
SEV_NONE = "NONE"
SEV_WARNING = "WARNING"
SEV_BREACH = "POLICY_BREACH"

# --- India recognisers ------------------------------------------------------
_INDIA_JURISDICTIONS = {"IN", "IND", "INDIA"}
_INDIA_COUNTRIES = {"IN", "IND", "INDIA"}
_INDIA_EXCHANGES = {"NSE", "BSE", "NSEI", "BOM", "BSE_INDIA", "NSE_INDIA"}
# Yahoo / vendor ticker suffixes that imply an Indian listing.
_INDIA_TICKER_SUFFIXES = (".NS", ".BO", ".NSE", ".BSE")
_INDIA_TICKER_PREFIXES = ("NSE:", "BSE:")

# --- Rest-of-world recognisers (known, non-India) ---------------------------
# Anything we positively recognise as a non-India venue resolves to
# REST_OF_WORLD (spot-only).  Unrecognised hints stay UNKNOWN (also spot-only,
# but flagged as unverified).
_ROW_EXCHANGES = {
    "NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "CBOE", "OTC",
    "LSE", "LON", "ETR", "XETRA", "FRA", "EPA", "EURONEXT", "AMS", "EBR",
    "BIT", "BME", "MCE", "SWX", "VTX",
    "TYO", "TSE", "JPX", "OSE",
    "KRX", "KOSPI", "KOSDAQ",
    "TSX", "TSXV", "ASX", "NZX",
    "HKEX", "HKG", "SEHK", "SSE", "SZSE", "SHA", "SHE",
    "SGX", "TADAWUL", "JSE", "B3", "BOVESPA",
}
_ROW_COUNTRIES = {
    "US", "USA", "GB", "UK", "DE", "FR", "NL", "BE", "IT", "ES", "CH",
    "JP", "JPN", "KR", "KOR", "CA", "CAN", "AU", "AUS", "NZ",
    "HK", "CN", "CHN", "SG", "SA", "ZA", "BR", "BRA",
}
_ROW_JURISDICTIONS = {"US", "USA", "EU", "UK", "GB", "JP", "KR", "CA", "AU", "ROW"}
# Yahoo / vendor ticker suffixes that imply a non-India listing.
_ROW_TICKER_SUFFIXES = (
    ".L", ".DE", ".F", ".PA", ".AS", ".BR", ".MI", ".MC", ".SW", ".VX",
    ".T", ".KS", ".KQ", ".TO", ".V", ".AX", ".NZ", ".HK", ".SS", ".SZ",
    ".SI", ".SA",
)


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def resolve_leverage_ceiling(
    ticker: Any = None,
    jurisdiction: Any = None,
    exchange: Any = None,
    country: Any = None,
) -> dict[str, Any]:
    """Resolve the leverage ceiling and jurisdiction group for an instrument.

    Resolution precedence (first positive match wins):
      1. explicit jurisdiction / country / exchange hints
      2. ticker suffix / prefix (e.g. ``RELIANCE.NS`` -> India, ``VOD.L`` -> ROW)

    Returns a dict with ``ceiling``, ``jurisdiction_group`` and ``reason``.
    Unknown instruments fail closed to the rest-of-world spot ceiling (1.0x)
    but are reported as ``UNKNOWN`` so the caller can warn the operator.
    """
    j = _norm(jurisdiction)
    c = _norm(country)
    x = _norm(exchange)
    t = _norm(ticker)

    # --- India (explicit hints) ---
    if j in _INDIA_JURISDICTIONS:
        return _ceiling(INDIA, INDIA_LEVERAGE_CEILING,
                        f"jurisdiction={j} -> India equities, 4.0x ceiling")
    if c in _INDIA_COUNTRIES:
        return _ceiling(INDIA, INDIA_LEVERAGE_CEILING,
                        f"country={c} -> India equities, 4.0x ceiling")
    if x in _INDIA_EXCHANGES:
        return _ceiling(INDIA, INDIA_LEVERAGE_CEILING,
                        f"exchange={x} -> India equities, 4.0x ceiling")

    # --- Rest-of-world (explicit hints) ---
    if j in _ROW_JURISDICTIONS:
        return _ceiling(REST_OF_WORLD, ROW_LEVERAGE_CEILING,
                        f"jurisdiction={j} -> rest-of-world, spot-only (1.0x)")
    if c in _ROW_COUNTRIES:
        return _ceiling(REST_OF_WORLD, ROW_LEVERAGE_CEILING,
                        f"country={c} -> rest-of-world, spot-only (1.0x)")
    if x in _ROW_EXCHANGES:
        return _ceiling(REST_OF_WORLD, ROW_LEVERAGE_CEILING,
                        f"exchange={x} -> rest-of-world, spot-only (1.0x)")

    # --- Ticker suffix / prefix fallback ---
    if t:
        if t.startswith(_INDIA_TICKER_PREFIXES) or t.endswith(_INDIA_TICKER_SUFFIXES):
            return _ceiling(INDIA, INDIA_LEVERAGE_CEILING,
                            f"ticker={t} suffix -> India equities, 4.0x ceiling")
        if t.endswith(_ROW_TICKER_SUFFIXES):
            return _ceiling(REST_OF_WORLD, ROW_LEVERAGE_CEILING,
                            f"ticker={t} suffix -> rest-of-world, spot-only (1.0x)")

    # --- Unknown: fail closed to spot-only, but flag as unverified ---
    return _ceiling(
        UNKNOWN, ROW_LEVERAGE_CEILING,
        "jurisdiction could not be verified from ticker/exchange/country; "
        "failing closed to spot-only (1.0x) — leverage above 1.0x is a breach",
    )


def _ceiling(group: str, ceiling: float, reason: str) -> dict[str, Any]:
    return {"jurisdiction_group": group, "ceiling": float(ceiling), "reason": reason}


def validate_leverage_policy(
    ticker: Any = None,
    leverage: Any = None,
    jurisdiction: Any = None,
    exchange: Any = None,
    country: Any = None,
) -> dict[str, Any]:
    """Validate a (possibly historical) leverage choice against the doctrine.

    This NEVER blocks recording — it classifies. ``allowed`` reflects whether
    the leverage is *within policy*; a journal caller should still persist the
    row even when ``allowed`` is False, carrying ``breach=True`` and the
    severity / reason so the breach is visible rather than silently normalised.

    Severity:
      * ``POLICY_BREACH`` — actual leverage exceeds the resolved ceiling.
      * ``WARNING``       — within ceiling, but jurisdiction is UNKNOWN
                            (accepted at spot-only, jurisdiction unverified).
      * ``NONE``          — within ceiling and jurisdiction recognised.
    """
    try:
        actual = float(leverage) if leverage is not None else DEFAULT_LEVERAGE
    except (TypeError, ValueError):
        actual = DEFAULT_LEVERAGE
    if actual < DEFAULT_LEVERAGE:
        actual = DEFAULT_LEVERAGE

    resolved = resolve_leverage_ceiling(
        ticker=ticker, jurisdiction=jurisdiction, exchange=exchange, country=country
    )
    ceiling = resolved["ceiling"]
    group = resolved["jurisdiction_group"]
    breach = actual > ceiling + _EPSILON

    if breach:
        severity = SEV_BREACH
        if group == UNKNOWN:
            reason = (
                f"{actual:g}x exceeds the spot-only ceiling (1.0x) and the "
                f"jurisdiction is UNVERIFIED — failed closed. {resolved['reason']}"
            )
        else:
            reason = (
                f"{actual:g}x exceeds the {ceiling:g}x ceiling for "
                f"{group}. {resolved['reason']}"
            )
    elif group == UNKNOWN:
        severity = SEV_WARNING
        reason = (
            f"{actual:g}x is within the spot-only ceiling, but the "
            f"jurisdiction is UNVERIFIED. {resolved['reason']}"
        )
    else:
        severity = SEV_NONE
        reason = (
            f"{actual:g}x is within the {ceiling:g}x ceiling for "
            f"{group}. {resolved['reason']}"
        )

    return {
        "allowed": not breach,
        "ceiling": ceiling,
        "actual_leverage": actual,
        "breach": breach,
        "severity": severity,
        "jurisdiction_group": group,
        "reason": reason,
        # Advisory invariants — constant, never granted by this layer.
        "advisory_only": True,
        "human_execution_required": True,
        "broker_api_called": False,
    }


__all__ = [
    "INDIA_LEVERAGE_CEILING",
    "ROW_LEVERAGE_CEILING",
    "DEFAULT_LEVERAGE",
    "INDIA",
    "REST_OF_WORLD",
    "UNKNOWN",
    "SEV_NONE",
    "SEV_WARNING",
    "SEV_BREACH",
    "resolve_leverage_ceiling",
    "validate_leverage_policy",
]
