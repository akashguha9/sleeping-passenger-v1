"""Regime-transition sprint — probability-to-equity propagation gap (PEG).

The flagship discovery question (reflection §3, §30, component 25):

    Has the event probability repriced faster than a fundamentally
    exposed equity — i.e. is there an unabsorbed gap worth researching?

    expected_move_i = ΔP_event × exposure_i × sensitivity_i
    gap_i           = expected_move_i − observed_move_i (direction-aligned)

Honesty rules:
- exposure below the floor ⇒ NO_EXPOSURE (an irrelevant company is not a
  "lagging" one — reflection unresolved Q12);
- stale or missing price data ⇒ UNKNOWN, never a fake gap;
- a stock that moved BEFORE the probability did is PRICE_LED (the equity
  market may have led the prediction market — do not call it absorbed);
- sensitivity defaults to a documented ASSUMED value and is labeled so;
- output is a RESEARCH TRIGGER with provenance labels, never a BUY.

Advisory-only.  Pure/deterministic, no network.
"""
from __future__ import annotations

from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
CALIBRATION_STATUS = "UNCALIBRATED_DEFAULTS"
OK = "OK"
UNKNOWN = "UNKNOWN"

# Gap states.
GAP_OPEN = "GAP_OPEN"
PARTIALLY_ABSORBED = "PARTIALLY_ABSORBED"
ABSORBED = "ABSORBED"
PRICE_LED = "PRICE_LED"
NO_EXPOSURE = "NO_EXPOSURE"
CONTRARY_MOVE = "CONTRARY_MOVE"

# Provenance labels for report surfaces.
OBSERVED = "OBSERVED"
INFERRED = "INFERRED"
ASSUMED = "ASSUMED"

_EXPOSURE_FLOOR = 0.10
_DEFAULT_SENSITIVITY = 0.30   # expected % equity move per 100% ΔP at exposure 1.0
_ABSORBED_CEILING = 0.25      # ≤25% of expected move unabsorbed ⇒ ABSORBED
_OPEN_FLOOR = 0.60            # ≥60% unabsorbed ⇒ GAP_OPEN
_PRICE_STALE_DAYS = 5


def propagation_gap(
    *,
    ticker: str,
    delta_p_event: float,
    prob_move_start_day: int,
    exposure: float | None,
    exposure_evidence_ref: str | None,
    observed_price_move: float | None,
    price_move_start_day: int | None = None,
    price_age_days: int | None = None,
    direction: int = 1,
    sensitivity: float | None = None,
) -> dict[str, Any]:
    """Compute PEG for one security.

    ``direction`` +1 means the event benefits the ticker (expected move
    up when ΔP rises), -1 means it harms it.  ``observed_price_move`` is
    the fractional move over the comparison window (0.03 == +3%).
    """
    base: dict[str, Any] = {
        "ticker": ticker,
        "signal_class": "RESEARCH_TRIGGER_ONLY",
        "calibration_status": CALIBRATION_STATUS,
        "safety": {"advisory_status": ADVISORY_STATUS,
                   "real_money": REAL_MONEY},
        "provenance": {
            "delta_p_event": OBSERVED,
            "exposure": INFERRED if exposure_evidence_ref else UNKNOWN,
            "sensitivity": ASSUMED if sensitivity is None else INFERRED,
            "observed_price_move": OBSERVED
            if observed_price_move is not None else UNKNOWN,
        },
    }
    # Exposure honesty: uncited exposure is not admissible evidence.
    if exposure is None or not exposure_evidence_ref:
        return {**base, "status": UNKNOWN, "gap_state": None,
                "reason": "exposure unknown or uncited"}
    if exposure < _EXPOSURE_FLOOR:
        return {**base, "status": OK, "gap_state": NO_EXPOSURE,
                "exposure": round(exposure, 4),
                "reason": f"exposure {exposure:.2f} below floor "
                          f"{_EXPOSURE_FLOOR} — thematic proxy, not a "
                          "lagging beneficiary"}
    if observed_price_move is None or (
            price_age_days is not None and price_age_days > _PRICE_STALE_DAYS):
        return {**base, "status": UNKNOWN, "gap_state": None,
                "reason": "price data missing or stale"}

    sens = _DEFAULT_SENSITIVITY if sensitivity is None else sensitivity
    expected = delta_p_event * max(0.0, min(1.0, exposure)) * sens * (
        1 if direction >= 0 else -1)
    # Align observed move to the expected direction: positive = with-thesis.
    sign = 1 if expected >= 0 else -1
    observed_aligned = observed_price_move * sign
    expected_abs = abs(expected)

    if (price_move_start_day is not None
            and price_move_start_day < prob_move_start_day
            and abs(observed_price_move) > 0.5 * expected_abs > 0):
        state = PRICE_LED
        unabsorbed = None
    elif expected_abs < 1e-9:
        return {**base, "status": UNKNOWN, "gap_state": None,
                "reason": "expected move is zero (ΔP or exposure zero)"}
    elif observed_aligned < -0.25 * expected_abs:
        state = CONTRARY_MOVE
        unabsorbed = 1.0
    else:
        unabsorbed = max(0.0, 1.0 - max(0.0, observed_aligned) / expected_abs)
        if unabsorbed <= _ABSORBED_CEILING:
            state = ABSORBED
        elif unabsorbed >= _OPEN_FLOOR:
            state = GAP_OPEN
        else:
            state = PARTIALLY_ABSORBED
    return {**base, "status": OK, "gap_state": state,
            "expected_move": round(expected, 6),
            "observed_move": round(observed_price_move, 6),
            "unabsorbed_fraction": None if unabsorbed is None
            else round(unabsorbed, 4),
            "exposure": round(exposure, 4),
            "sensitivity_used": sens,
            "exposure_evidence_ref": exposure_evidence_ref}


def rank_gap_candidates(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order PEG results for research triage — GAP_OPEN first, by expected
    unabsorbed magnitude.  Excludes NO_EXPOSURE / UNKNOWN / PRICE_LED
    (those are not propagation opportunities)."""
    eligible = [g for g in gaps
                if g.get("status") == OK
                and g.get("gap_state") in (GAP_OPEN, PARTIALLY_ABSORBED)]
    return sorted(
        eligible,
        key=lambda g: -(abs(g.get("expected_move") or 0.0)
                        * (g.get("unabsorbed_fraction") or 0.0)))
