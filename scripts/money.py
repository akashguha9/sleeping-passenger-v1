"""Decimal money helper — L1 fix.

The MVP's journal had every monetary field declared as ``float`` in
pydantic models and Python signatures.  Binary floats can't represent
common decimal prices exactly, so rolling PnL drifts and reconciliation
totals diverge from what the operator saw on the broker side.  Since
the entire product value is calibrating operator memory against
reality, this is a primary correctness defect.

Strategy
--------
- Boundary: API request models accept ``Decimal | float | int | str``
  and **immediately** coerce to ``Decimal`` via a validator that rejects
  NaN/Inf and quantises to a safe 12-place quantum.
- Internals: any new code MUST use ``Decimal`` end-to-end.  Legacy
  helpers (``log_manual_trade``, ``reconcile_trade``) currently accept
  ``float``; the API layer converts to ``Decimal`` then back to a
  ``str`` of the Decimal so the persisted ``payload_json`` is the
  Decimal string, not the float repr.  That preserves the exact value
  the operator entered.
- Egress: when serialising back to JSON we render Decimals as strings to
  match what we stored.  Downstream code that math's on these values
  can ``Decimal(value)`` losslessly.

Advisory invariants are not touched by this module.  It contains no
broker calls, no execution permission, no AI execution.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, getcontext
from typing import Any

# Twelve fractional digits is enough for FX, crypto (8 dp standard), and
# basis-point-scale ratios.  Greater precision is overkill; less risks
# clipping spot crypto prices.
_QUANTUM = Decimal("0.000000000001")

# Set a generous context precision so add/subtract chains don't lose
# digits before we re-quantise.  Note: pydantic + this module operate on
# instance-level Decimals so we don't need to mutate the global context,
# but a sane default helps callers that compute outside the boundary.
getcontext().prec = 50


class MoneyError(ValueError):
    """Raised when a money value is malformed (NaN, Inf, non-numeric)."""


def parse_money(value: Any, *, allow_negative: bool = True) -> Decimal:
    """Parse an arbitrary money-like input into a quantised Decimal.

    Accepts:
      * Decimal — returned quantised
      * int — converted exactly
      * float — converted via ``str()`` to dodge the float-repr surprise
      * str — passed to Decimal directly (decimal-faithful)
      * None — raises (callers use ``parse_money_opt`` instead)

    Rejects NaN / Inf / non-numeric strings.
    """
    if value is None:
        raise MoneyError("money value is required (received None)")
    try:
        if isinstance(value, Decimal):
            dec = value
        elif isinstance(value, bool):  # bool is a subclass of int — reject explicitly
            raise MoneyError(f"refusing bool as money: {value!r}")
        elif isinstance(value, int):
            dec = Decimal(value)
        elif isinstance(value, float):
            # str(float) is the closest decimal repr; Decimal(float) would
            # bake in the binary error.
            dec = Decimal(str(value))
        elif isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            if not cleaned:
                raise MoneyError("money value is empty")
            dec = Decimal(cleaned)
        else:
            raise MoneyError(f"unsupported money type: {type(value).__name__}")
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"invalid money value: {value!r}") from exc

    if dec.is_nan() or dec.is_infinite():
        raise MoneyError(f"refusing NaN/Inf money value: {value!r}")
    if not allow_negative and dec < 0:
        raise MoneyError(f"refusing negative money value: {value!r}")

    return dec.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def parse_money_opt(value: Any, *, allow_negative: bool = True) -> Decimal | None:
    """Like ``parse_money`` but maps None / empty-string to None."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return parse_money(value, allow_negative=allow_negative)


def money_to_str(value: Decimal | None) -> str | None:
    """Render a Decimal as a stable normalised string for persistence."""
    if value is None:
        return None
    # ``normalize()`` strips trailing zeros; we DON'T want that for money
    # ("100.00" should not become "1E+2").  Quantise instead.
    return format(value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def money_to_legacy_float(value: Decimal | None) -> float | None:
    """Bridge helper: convert Decimal → float for legacy float-typed APIs.

    Marked explicitly so audit-grep can find every spot where we still
    cross the float boundary.  Each call site is a TODO for the full L1
    schema migration.
    """
    if value is None:
        return None
    return float(value)
