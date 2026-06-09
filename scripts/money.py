"""Decimal money helper — L1/F3 fix.

The MVP's journal had every monetary field declared as ``float`` in
pydantic models and Python signatures.  Binary floats can't represent
common decimal prices exactly, so rolling PnL drifts and reconciliation
totals diverge from what the operator saw on the broker side.  Since
the entire product value is calibrating operator memory against
reality, this is a primary correctness defect.

Strategy (post-F3 migration — this describes SHIPPED behaviour)
----------------------------------------------------------------
- Boundary: API request models accept ``Decimal | float | int | str``
  and **immediately** coerce to ``Decimal`` via a validator that rejects
  NaN/Inf and quantises to a safe 12-place quantum.
- Internals: money stays ``Decimal`` through ``log_manual_trade`` /
  ``reconcile_trade`` and all realized-P/L arithmetic
  (:mod:`scripts.reconciliation_extras` computes in Decimal).
- Persistence: the journal money columns (``manual_trades.quantity`` /
  ``price`` / ``leverage``, ``reconciliation_results.actual_fill_price``
  / ``actual_quantity`` / ``pnl_estimate``) are TEXT-affinity and store
  the canonical Decimal string from :func:`money_to_str`.  SQLite never
  sees a float for these values.
- Egress: JSON responses render money as the canonical Decimal string.
  Downstream code that maths on these values can ``Decimal(value)``
  losslessly; display layers may format them however they like.

Rounding mode (documented per audit F3)
---------------------------------------
All quantisation in this module uses **ROUND_HALF_EVEN** (banker's
rounding) at a quantum of 1e-12 (``_QUANTUM``).  Half-even is the IEEE
754 default and avoids the systematic upward drift of half-up when
aggregating many small P/L values.  Twelve fractional digits cover FX,
crypto (8 dp standard) and basis-point-scale ratios.

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

# The single rounding mode used everywhere money is quantised.  See the
# module docstring for the rationale.
MONEY_ROUNDING = ROUND_HALF_EVEN

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

    return dec.quantize(_QUANTUM, rounding=MONEY_ROUNDING)


def parse_money_opt(value: Any, *, allow_negative: bool = True) -> Decimal | None:
    """Like ``parse_money`` but maps None / empty-string to None."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return parse_money(value, allow_negative=allow_negative)


def money_to_str(value: Decimal | None) -> str | None:
    """Render a Decimal as the canonical string for persistence/egress.

    Quantises to the 12-dp quantum (ROUND_HALF_EVEN), strips redundant
    trailing zeros, and always renders fixed-point (never ``1E+2``):
    ``Decimal("100.00")`` → ``"100"``, ``Decimal("0.020")`` → ``"0.02"``.
    The string round-trips losslessly through ``Decimal(s)``.
    """
    if value is None:
        return None
    quantised = value.quantize(_QUANTUM, rounding=MONEY_ROUNDING)
    # ``normalize()`` alone would produce exponent notation ("1E+2");
    # fixed-point formatting of the normalised value avoids that while
    # still dropping trailing zeros.
    return format(quantised.normalize(), "f")
