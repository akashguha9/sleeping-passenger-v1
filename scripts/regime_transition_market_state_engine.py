"""Regime-transition sprint — prediction-market state engine.

Three narrowly-scoped jobs the existing prediction-market stack lacked
(the disagreement scanner matches events; the shock engine measures
conviction-weighted ΔP; NEITHER measures dynamics or venue quality):

1. **Venue quality score** — liquidity / spread / depth / staleness →
   confidence weight for a venue's probability.  Thin markets must not be
   trusted like deep markets (reflection §28, failure 4).
2. **Probability dynamics** — P_t, ΔP, dP/dt, d²P/dt² per contract, and
   D_t = |P_A − P_B| plus dD/dt across venues, with momentum-state
   classification (CONVERGING / CONSENSUS_SHIFT / INFORMATION_FRACTURE /
   OPPOSING / STABLE) per reflection §24–25.
3. **PMDS** — a [0, 100] research trigger (NEVER a trade signal) combining
   divergence, divergence velocity, momentum, quality and instability
   inputs with the reflection's §29 weights.  EXPERIMENTAL and
   UNCALIBRATED by construction; gated by the CES verdict.

Missing data is reported as UNKNOWN/INSUFFICIENT_HISTORY — never a silent
zero.  Advisory-only: no broker, no execution, no order placement.
"""
from __future__ import annotations

import math
from typing import Any

from scripts.regime_transition_contract_equivalence_score import (
    divergence_comparison_allowed,
)

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
EXPERIMENTAL = "EXPERIMENTAL"
CALIBRATION_STATUS = "UNCALIBRATED_DEFAULTS"

OK = "OK"
UNKNOWN = "UNKNOWN"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"

# Momentum states (reflection §25).
CONVERGING = "CONVERGING"                # gap shrinking
CONSENSUS_SHIFT = "CONSENSUS_SHIFT"      # both moving same direction, gap steady
INFORMATION_FRACTURE = "INFORMATION_FRACTURE"  # one venue moving, other flat
OPPOSING = "OPPOSING"                    # venues moving in opposite directions
STABLE = "STABLE"

_VELOCITY_FLOOR = 0.005   # prob/day below which a venue counts as "flat"
_MIN_POINTS_VELOCITY = 2
_MIN_POINTS_ACCEL = 3
_STALE_DAYS = 3           # last trade older than this → staleness penalty

# Quality component weights (documented heuristics, not calibrated).
_QUALITY_WEIGHTS = {"liquidity": 0.30, "spread": 0.30, "depth": 0.20,
                    "staleness": 0.20}
_MIN_QUALITY_COVERAGE = 0.50


def venue_quality_score(market: dict[str, Any]) -> dict[str, Any]:
    """Score one venue's market microstructure in [0, 100].

    Recognized keys (all optional): ``volume_usd``, ``bid``, ``ask``,
    ``depth_usd``, ``last_trade_age_days``.  Missing components fall out of
    the denominator; below 50% component coverage the whole score is
    UNKNOWN rather than a fake number.
    """
    components: dict[str, float | None] = {
        "liquidity": None, "spread": None, "depth": None, "staleness": None}

    vol = market.get("volume_usd")
    if isinstance(vol, (int, float)) and vol >= 0:
        components["liquidity"] = min(1.0, math.log10(1.0 + vol) / 6.0)

    bid, ask = market.get("bid"), market.get("ask")
    if (isinstance(bid, (int, float)) and isinstance(ask, (int, float))
            and 0 < bid <= ask <= 1):
        spread = ask - bid
        components["spread"] = max(0.0, 1.0 - spread / 0.10)  # 10pt spread → 0

    depth = market.get("depth_usd")
    if isinstance(depth, (int, float)) and depth >= 0:
        components["depth"] = min(1.0, math.log10(1.0 + depth) / 5.0)

    age = market.get("last_trade_age_days")
    if isinstance(age, (int, float)) and age >= 0:
        components["staleness"] = 1.0 if age <= _STALE_DAYS else max(
            0.0, 1.0 - (age - _STALE_DAYS) / 14.0)

    known = {k: v for k, v in components.items() if v is not None}
    coverage = sum(_QUALITY_WEIGHTS[k] for k in known)
    if coverage < _MIN_QUALITY_COVERAGE:
        return {"status": UNKNOWN, "score": None,
                "component_coverage": round(coverage, 4),
                "components": components,
                "missing": sorted(k for k in components if k not in known)}
    score = 100.0 * sum(_QUALITY_WEIGHTS[k] * v for k, v in known.items()) / coverage
    return {"status": OK, "score": round(score, 2),
            "component_coverage": round(coverage, 4),
            "components": {k: (None if v is None else round(v, 4))
                           for k, v in components.items()},
            "missing": sorted(k for k in components if k not in known),
            "stale": bool(isinstance(age, (int, float)) and age > _STALE_DAYS)}


def probability_dynamics(series: list[tuple[int, float]]) -> dict[str, Any]:
    """P_t, ΔP, dP/dt, d²P/dt² over an integer-day probability series."""
    pts = sorted((int(d), float(p)) for d, p in series
                 if isinstance(p, (int, float)) and 0.0 <= p <= 1.0)
    if not pts:
        return {"status": INSUFFICIENT_HISTORY, "points": 0}
    out: dict[str, Any] = {"status": OK, "points": len(pts),
                           "p_latest": round(pts[-1][1], 6),
                           "day_latest": pts[-1][0],
                           "delta_p": None, "velocity": None,
                           "acceleration": None}
    if len(pts) >= _MIN_POINTS_VELOCITY:
        (d0, p0), (d1, p1) = pts[-2], pts[-1]
        span = max(1, d1 - d0)
        out["delta_p"] = round(p1 - pts[0][1], 6)
        out["velocity"] = round((p1 - p0) / span, 6)
    if len(pts) >= _MIN_POINTS_ACCEL:
        (da, pa), (db, pb), (dc, pc) = pts[-3], pts[-2], pts[-1]
        v1 = (pb - pa) / max(1, db - da)
        v2 = (pc - pb) / max(1, dc - db)
        out["acceleration"] = round((v2 - v1) / max(1, dc - db), 6)
    if out["velocity"] is None:
        out["status"] = INSUFFICIENT_HISTORY
    return out


def divergence_dynamics(series_a: list[tuple[int, float]],
                        series_b: list[tuple[int, float]]) -> dict[str, Any]:
    """Cross-venue D_t = |P_A − P_B|, dD/dt, and momentum-state label."""
    map_a = {int(d): float(p) for d, p in series_a}
    map_b = {int(d): float(p) for d, p in series_b}
    days = sorted(set(map_a) & set(map_b))
    if len(days) < 1:
        return {"status": INSUFFICIENT_HISTORY, "aligned_days": 0}
    d_series = [(d, abs(map_a[d] - map_b[d])) for d in days]
    out: dict[str, Any] = {
        "status": OK, "aligned_days": len(days),
        "divergence_latest": round(d_series[-1][1], 6),
        "divergence_series": [(d, round(v, 6)) for d, v in d_series],
        "divergence_velocity": None, "momentum_state": None,
    }
    if len(days) < 2:
        out["status"] = INSUFFICIENT_HISTORY
        return out
    (d0, v0), (d1, v1) = d_series[-2], d_series[-1]
    out["divergence_velocity"] = round((v1 - v0) / max(1, d1 - d0), 6)

    dyn_a = probability_dynamics([(d, map_a[d]) for d in days])
    dyn_b = probability_dynamics([(d, map_b[d]) for d in days])
    va, vb = dyn_a.get("velocity"), dyn_b.get("velocity")
    if va is None or vb is None:
        out["momentum_state"] = UNKNOWN
    else:
        a_moving, b_moving = abs(va) >= _VELOCITY_FLOOR, abs(vb) >= _VELOCITY_FLOOR
        if not a_moving and not b_moving:
            out["momentum_state"] = STABLE
        elif a_moving != b_moving:
            out["momentum_state"] = INFORMATION_FRACTURE
        elif va * vb < 0:
            out["momentum_state"] = OPPOSING
        elif out["divergence_velocity"] < 0:
            out["momentum_state"] = CONVERGING
        else:
            out["momentum_state"] = CONSENSUS_SHIFT
    out["venue_velocities"] = {"a": va, "b": vb}
    return out


# PMDS weights (reflection §29; sum 100).  Research trigger only.
_PMDS_WEIGHTS = {
    "divergence": 25.0, "divergence_velocity": 15.0, "momentum": 15.0,
    "lead_lag": 10.0, "market_quality": 15.0, "narrative_instability": 10.0,
    "fundamental_confirmation": 10.0,
}
_MOMENTUM_CREDIT = {OPPOSING: 1.0, INFORMATION_FRACTURE: 0.85,
                    CONSENSUS_SHIFT: 0.5, CONVERGING: 0.3, STABLE: 0.0}
_MIN_PMDS_COVERAGE = 0.55


def prediction_market_divergence_score(
    *,
    ces_verdict: dict[str, Any],
    divergence: dict[str, Any],
    quality_a: dict[str, Any],
    quality_b: dict[str, Any],
    lead_lag_score: float | None = None,
    narrative_instability_0_100: float | None = None,
    fundamental_confirmation_0_1: float | None = None,
) -> dict[str, Any]:
    """PMDS ∈ [0, 100] — a RESEARCH TRIGGER, never a BUY signal.

    Fails closed: a blocked CES gate returns a blocked PMDS.  Lead-lag has
    no learned history yet, so unless a caller supplies an empirical score
    that component stays UNKNOWN (weight excluded, reported).
    """
    base = {"signal_class": "RESEARCH_TRIGGER_ONLY", "experimental": True,
            "calibration_status": CALIBRATION_STATUS,
            "safety": {"advisory_status": ADVISORY_STATUS,
                       "real_money": REAL_MONEY}}
    if not divergence_comparison_allowed(ces_verdict):
        return {**base, "status": "BLOCKED_BY_CES",
                "pmds": None, "ces_gate": ces_verdict.get("gate")}
    if divergence.get("status") != OK:
        return {**base, "status": INSUFFICIENT_HISTORY, "pmds": None}

    credits: dict[str, float | None] = {}
    credits["divergence"] = min(1.0, divergence["divergence_latest"] / 0.25)
    dv = divergence.get("divergence_velocity")
    credits["divergence_velocity"] = (
        None if dv is None else min(1.0, max(0.0, dv) / 0.05))
    ms = divergence.get("momentum_state")
    credits["momentum"] = _MOMENTUM_CREDIT.get(ms) if ms in _MOMENTUM_CREDIT else None
    credits["lead_lag"] = (
        None if lead_lag_score is None else max(0.0, min(1.0, lead_lag_score)))
    if quality_a.get("status") == OK and quality_b.get("status") == OK:
        credits["market_quality"] = min(quality_a["score"], quality_b["score"]) / 100.0
    else:
        credits["market_quality"] = None
    credits["narrative_instability"] = (
        None if narrative_instability_0_100 is None
        else max(0.0, min(1.0, narrative_instability_0_100 / 100.0)))
    credits["fundamental_confirmation"] = (
        None if fundamental_confirmation_0_1 is None
        else max(0.0, min(1.0, fundamental_confirmation_0_1)))

    known_w = sum(_PMDS_WEIGHTS[k] for k, v in credits.items() if v is not None)
    coverage = known_w / sum(_PMDS_WEIGHTS.values())
    if coverage < _MIN_PMDS_COVERAGE:
        return {**base, "status": "INSUFFICIENT_COMPONENTS", "pmds": None,
                "component_coverage": round(coverage, 4),
                "missing_components": sorted(
                    k for k, v in credits.items() if v is None)}

    raw = sum(_PMDS_WEIGHTS[k] * v for k, v in credits.items() if v is not None)
    pmds = 100.0 * raw / known_w
    # Penalized-CES pairs shrink the score instead of pretending equivalence.
    pmds *= float(ces_verdict.get("divergence_weight_multiplier", 0.0)) \
        if ces_verdict.get("gate") == "PENALIZED_COMPARISON" else 1.0
    return {**base, "status": OK, "pmds": round(pmds, 2),
            "component_coverage": round(coverage, 4),
            "component_credits": {k: (None if v is None else round(v, 4))
                                  for k, v in credits.items()},
            "missing_components": sorted(k for k, v in credits.items()
                                         if v is None),
            "ces_gate": ces_verdict.get("gate")}
