"""Leverage policy — risk-control validation (advisory-only, no execution).

Operating-philosophy invariant (Year 1):

    L_max(ticker, country) = 4  if the instrument is Indian equity
                           = 1  otherwise (rest-of-world: spot-only)

    ValidLeverage(ticker, country, L) = I(1 <= L <= L_max(ticker, country))

This module is **pure**: no DB, no filesystem, no network, no broker calls.
Rejecting an out-of-policy leverage is *risk control*, not execution — it
prevents a record being written, it never places, routes, or sizes an order.
Every result carries the advisory-only safety stamps so a rejection can never
be mistaken for an execution decision.

India detection is deliberately robust (the manual-trade path has no reliable
``country`` field, only a ticker):

    India if any of:
      * country normalised == "india" / "in" / "ind"
      * ticker starts with "NSE:" or "BSE:"
      * ticker ends with ".NS" or ".BO"

Anything else is treated as rest-of-world, spot-only (max 1x).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:  # canonical safety stamps (pure module)
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

INDIA_MAX_LEVERAGE: float = 4.0
ROW_MAX_LEVERAGE: float = 1.0  # rest-of-world: spot-only
LEVERAGE_MIN: float = 1.0

_INDIA_COUNTRY_TOKENS: frozenset[str] = frozenset({"india", "in", "ind"})
_INDIA_TICKER_PREFIXES: tuple[str, ...] = ("NSE:", "BSE:")
_INDIA_TICKER_SUFFIXES: tuple[str, ...] = (".NS", ".BO")

LEVERAGE_POLICY_VIOLATION = "LEVERAGE_POLICY_VIOLATION"
LEVERAGE_NOT_A_NUMBER = "LEVERAGE_NOT_A_NUMBER"


def is_india_instrument(ticker: str | None, country: str | None = None) -> bool:
    """True iff the instrument is an Indian equity by ticker or country."""
    if country is not None:
        if str(country).strip().lower() in _INDIA_COUNTRY_TOKENS:
            return True
    t = (ticker or "").strip().upper()
    if t.startswith(_INDIA_TICKER_PREFIXES):
        return True
    if t.endswith(_INDIA_TICKER_SUFFIXES):
        return True
    return False


def get_max_allowed_leverage(ticker: str | None, country: str | None = None) -> float:
    """Return the policy ceiling for the instrument.

    4x for Indian equity, 1x (spot-only) for everything else.
    """
    return INDIA_MAX_LEVERAGE if is_india_instrument(ticker, country) else ROW_MAX_LEVERAGE


@dataclass(frozen=True)
class LeverageValidationResult:
    """Outcome of a leverage-policy check.  Always advisory-only."""

    valid: bool
    ticker: str
    country: str | None
    is_india: bool
    requested_leverage: float | None
    allowed_max_leverage: float
    reason: str | None = None
    detail: str | None = None
    # Safety stamps spliced from the canonical contract so a REJECTION can
    # never read as an execution grant.
    stamps: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "leverage_policy_valid": self.valid,
            "ticker": self.ticker,
            "country": self.country,
            "is_india_instrument": self.is_india,
            "requested_leverage": self.requested_leverage,
            "allowed_max_leverage": self.allowed_max_leverage,
            "reason": self.reason,
            "detail": self.detail,
        }
        # Advisory-only invariants — present on accept AND reject.
        out.update(self.stamps)
        out["execution_permission"] = "ADVISORY_ONLY"
        out["human_execution_required"] = True
        return out


def validate_leverage_policy(
    ticker: str | None,
    country: str | None,
    leverage: Any,
) -> LeverageValidationResult:
    """Validate ``leverage`` against the per-instrument policy ceiling.

    Does NOT clamp — an out-of-policy value is rejected with an explanation so
    the operator must consciously re-enter a compliant number.
    """
    stamps = advisory_safety_stamps()
    is_india = is_india_instrument(ticker, country)
    allowed_max = INDIA_MAX_LEVERAGE if is_india else ROW_MAX_LEVERAGE
    t = (ticker or "").strip()

    # Type guard — booleans are not valid numeric leverage.
    if isinstance(leverage, bool) or not isinstance(leverage, (int, float)):
        return LeverageValidationResult(
            valid=False,
            ticker=t,
            country=country,
            is_india=is_india,
            requested_leverage=None,
            allowed_max_leverage=allowed_max,
            reason=LEVERAGE_NOT_A_NUMBER,
            detail="leverage must be a number (e.g. 1.0, 2.5)",
            stamps=stamps,
        )

    lev = float(leverage)
    if lev < LEVERAGE_MIN or lev > allowed_max:
        jurisdiction = "India (max 4x long)" if is_india else "rest-of-world (spot-only, max 1x)"
        return LeverageValidationResult(
            valid=False,
            ticker=t,
            country=country,
            is_india=is_india,
            requested_leverage=lev,
            allowed_max_leverage=allowed_max,
            reason=LEVERAGE_POLICY_VIOLATION,
            detail=(
                f"leverage {lev:g}x violates policy for {t or 'instrument'} "
                f"[{jurisdiction}]: allowed range is "
                f"{LEVERAGE_MIN:g}x..{allowed_max:g}x"
            ),
            stamps=stamps,
        )

    return LeverageValidationResult(
        valid=True,
        ticker=t,
        country=country,
        is_india=is_india,
        requested_leverage=lev,
        allowed_max_leverage=allowed_max,
        reason=None,
        detail=None,
        stamps=stamps,
    )


__all__ = [
    "INDIA_MAX_LEVERAGE",
    "ROW_MAX_LEVERAGE",
    "LEVERAGE_MIN",
    "LEVERAGE_POLICY_VIOLATION",
    "LEVERAGE_NOT_A_NUMBER",
    "is_india_instrument",
    "get_max_allowed_leverage",
    "validate_leverage_policy",
    "LeverageValidationResult",
]
