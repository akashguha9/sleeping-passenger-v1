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


# Jurisdiction-resolution provenance — how we decided the jurisdiction group.
SRC_EXPLICIT = "EXPLICIT"
SRC_SECURITIES_MASTER = "SECURITIES_MASTER"
SRC_TICKER_HEURISTIC = "TICKER_HEURISTIC"
SRC_UNKNOWN_FAIL_CLOSED = "UNKNOWN_FAIL_CLOSED"


def _classify_hints(jurisdiction: str, exchange: str, country: str) -> tuple[str, str] | None:
    """Classify explicit jurisdiction/exchange/country hints to a group.

    Returns ``(group, human_reason_fragment)`` or None if the hints recognise
    nothing. Pure string logic; reused for both explicit input and
    securities-master rows.
    """
    j, x, c = _norm(jurisdiction), _norm(exchange), _norm(country)
    if j in _INDIA_JURISDICTIONS:
        return INDIA, f"jurisdiction={j}"
    if c in _INDIA_COUNTRIES:
        return INDIA, f"country={c}"
    if x in _INDIA_EXCHANGES:
        return INDIA, f"exchange={x}"
    if j in _ROW_JURISDICTIONS:
        return REST_OF_WORLD, f"jurisdiction={j}"
    if c in _ROW_COUNTRIES:
        return REST_OF_WORLD, f"country={c}"
    if x in _ROW_EXCHANGES:
        return REST_OF_WORLD, f"exchange={x}"
    return None


def _classify_ticker(ticker: str) -> tuple[str, str] | None:
    """Classify a ticker by suffix/prefix heuristic. Pure string logic."""
    t = _norm(ticker)
    if not t:
        return None
    if t.startswith(_INDIA_TICKER_PREFIXES) or t.endswith(_INDIA_TICKER_SUFFIXES):
        return INDIA, f"ticker={t} suffix"
    if t.endswith(_ROW_TICKER_SUFFIXES):
        return REST_OF_WORLD, f"ticker={t} suffix"
    return None


def _ceiling_for(group: str) -> float:
    return INDIA_LEVERAGE_CEILING if group == INDIA else ROW_LEVERAGE_CEILING


def resolve_leverage_ceiling(
    ticker: Any = None,
    jurisdiction: Any = None,
    exchange: Any = None,
    country: Any = None,
    *,
    securities_lookup: Any = None,
) -> dict[str, Any]:
    """Resolve the leverage ceiling, jurisdiction group, and how it was decided.

    Resolution precedence (first positive match wins):
      1. EXPLICIT          — caller-supplied jurisdiction / country / exchange
      2. SECURITIES_MASTER — ``securities_lookup(ticker)`` row's exchange/country
      3. TICKER_HEURISTIC  — ticker suffix/prefix (``RELIANCE.NS`` -> India)
      4. UNKNOWN_FAIL_CLOSED — spot-only (1.0x); leverage above 1.0x is a breach

    ``securities_lookup`` is an optional callable ``ticker -> dict | None`` with
    ``exchange_code`` / ``country`` keys (e.g. persistence.get_global_security).
    Injecting it keeps this module pure (no DB import) and fully testable.

    Returns ``{jurisdiction_group, ceiling, reason, resolution_source}``.
    """
    # 1. EXPLICIT hints
    hit = _classify_hints(jurisdiction, exchange, country)
    if hit is not None:
        group, frag = hit
        return _resolved(group, frag, SRC_EXPLICIT)

    # 2. SECURITIES MASTER
    if securities_lookup is not None:
        row = _safe_lookup(securities_lookup, ticker)
        if row:
            hit = _classify_hints(
                jurisdiction=None,
                exchange=row.get("exchange_code"),
                country=row.get("country"),
            )
            if hit is not None:
                group, frag = hit
                return _resolved(
                    group, f"securities master ({frag})", SRC_SECURITIES_MASTER
                )

    # 3. TICKER HEURISTIC
    hit = _classify_ticker(ticker)
    if hit is not None:
        group, frag = hit
        return _resolved(group, frag, SRC_TICKER_HEURISTIC)

    # 4. UNKNOWN — fail closed to spot-only
    return {
        "jurisdiction_group": UNKNOWN,
        "ceiling": ROW_LEVERAGE_CEILING,
        "reason": (
            "jurisdiction could not be verified from explicit input, securities "
            "master, or ticker; failing closed to spot-only (1.0x) — leverage "
            "above 1.0x is a breach"
        ),
        "resolution_source": SRC_UNKNOWN_FAIL_CLOSED,
    }


def _safe_lookup(securities_lookup: Any, ticker: Any) -> dict[str, Any] | None:
    """Call the injected lookup defensively; never raise into the policy path."""
    sym = _norm(ticker)
    if not sym:
        return None
    try:
        row = securities_lookup(sym)
    except Exception:  # pragma: no cover - defensive
        return None
    return row if isinstance(row, dict) else None


def _resolved(group: str, frag: str, source: str) -> dict[str, Any]:
    ceiling = _ceiling_for(group)
    if group == INDIA:
        reason = f"{frag} -> India equities, {ceiling:g}x ceiling [{source}]"
    else:
        reason = f"{frag} -> rest-of-world, spot-only ({ceiling:g}x) [{source}]"
    return {
        "jurisdiction_group": group,
        "ceiling": float(ceiling),
        "reason": reason,
        "resolution_source": source,
    }


def _ceiling(group: str, ceiling: float, reason: str) -> dict[str, Any]:
    return {"jurisdiction_group": group, "ceiling": float(ceiling), "reason": reason}


def validate_leverage_policy(
    ticker: Any = None,
    leverage: Any = None,
    jurisdiction: Any = None,
    exchange: Any = None,
    country: Any = None,
    *,
    securities_lookup: Any = None,
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
        ticker=ticker, jurisdiction=jurisdiction, exchange=exchange,
        country=country, securities_lookup=securities_lookup,
    )
    ceiling = resolved["ceiling"]
    group = resolved["jurisdiction_group"]
    resolution_source = resolved["resolution_source"]
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
        "jurisdiction_resolution_source": resolution_source,
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
    "SRC_EXPLICIT",
    "SRC_SECURITIES_MASTER",
    "SRC_TICKER_HEURISTIC",
    "SRC_UNKNOWN_FAIL_CLOSED",
    "INDIA",
    "REST_OF_WORLD",
    "UNKNOWN",
    "SEV_NONE",
    "SEV_WARNING",
    "SEV_BREACH",
    "resolve_leverage_ceiling",
    "validate_leverage_policy",
]
