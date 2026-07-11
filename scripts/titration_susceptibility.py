"""Measured market susceptibility — robust, sample-gated, hierarchy-resolved.

Replaces the Market Titration Engine's heuristic susceptibility with an
EMPIRICAL estimate wherever matured evidence→response observations exist:

    chi  =  d(market response) / d(evidence dose)

estimated as the robust (Theil–Sen) slope of volatility-scaled forward
response ``Z_h`` on incremental evidence dose across matured observations.

Honesty contract
----------------
* Every estimate exposes: estimator, version, scope, horizon, sample size,
  slope, approximate confidence interval, normalized operational score,
  fallback level, and whether it is MEASURED / SHRUNK / PROXY.
* Sample gates are hard: below ``min_obs_ticker`` a ticker-level estimate
  is NOT produced (the hierarchy falls through); below ``min_obs_pooled``
  no pooled estimate is produced at all and the engine keeps its labelled
  heuristic proxy.
* Slopes are clipped (``slope_clip``) so a tiny-sample outlier cannot
  explode into an operational score; the normalized score is additionally
  bounded to [0, 1].
* Negative measured slopes are real information (the market is absorbing
  evidence — high buffer) and normalize to LOW susceptibility, never an
  error.
* This module never presents a slope as a calibrated probability.

Fallback hierarchy (resolution order)
-------------------------------------
    LEVEL 1  MEASURED_TICKER    ticker-scope slope, shrunk toward parent
    LEVEL 2  SHRUNK_SECTOR      sector×market pool (skipped when the
                                securities master carries no sector)
    LEVEL 3  MEASURED_MARKET    market pool (INDIA / US / GLOBAL_OTHER)
    LEVEL 4  MEASURED_GLOBAL    all matured observations
    LEVEL 5  HEURISTIC_PROXY    the engine's existing labelled proxy

Pure module: stdlib only, no DB access (the response pipeline feeds it
observation rows and persists its outputs).  Advisory-only.
"""

from __future__ import annotations

import math
from typing import Any

SUSCEPTIBILITY_ESTIMATOR_VERSION = "chi_theil_sen_v1"

SOURCE_MEASURED_TICKER = "MEASURED_TICKER"
SOURCE_SHRUNK_SECTOR = "SHRUNK_SECTOR"
SOURCE_MEASURED_MARKET = "MEASURED_MARKET"
SOURCE_MEASURED_GLOBAL = "MEASURED_GLOBAL"
SOURCE_HEURISTIC_PROXY = "HEURISTIC_PROXY"

SUSCEPTIBILITY_SOURCES: tuple[str, ...] = (
    SOURCE_MEASURED_TICKER,
    SOURCE_SHRUNK_SECTOR,
    SOURCE_MEASURED_MARKET,
    SOURCE_MEASURED_GLOBAL,
    SOURCE_HEURISTIC_PROXY,
)

ACCEL_ACCELERATING = "RESPONSE_ACCELERATING"
ACCEL_STABLE = "RESPONSE_STABLE"
ACCEL_DECELERATING = "RESPONSE_DECELERATING"
ACCEL_INSUFFICIENT = "INSUFFICIENT_DATA"

ACCELERATION_CLASSES: tuple[str, ...] = (
    ACCEL_ACCELERATING, ACCEL_STABLE, ACCEL_DECELERATING, ACCEL_INSUFFICIENT,
)

DEFAULT_PARAMS: dict[str, Any] = {
    # Hard sample gates.
    "min_obs_ticker": 12,
    "min_obs_pooled": 30,
    "min_obs_acceleration_window": 8,
    # Shrinkage strength: ticker slope is pulled toward its parent pool
    # with pseudo-count k (empirical-Bayes style partial pooling).
    "shrinkage_k": 10.0,
    # Robustness: pairwise slopes and the final slope are clipped here.
    "slope_clip": 25.0,
    # Normalization: slope (Z units per unit dose) mapping to [0,1].
    # chi_norm = clip01(slope / slope_scale); negative slopes -> 0.
    "slope_scale": 4.0,
    # Acceleration: |late - early| slope difference must exceed this
    # fraction of slope_scale to leave RESPONSE_STABLE.
    "acceleration_min_delta_fraction": 0.15,
    # Cap on pairwise-slope evaluations (deterministic thinning).
    "max_pairs": 20000,
}


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _clip(x: float, bound: float) -> float:
    return max(-bound, min(bound, x))


def theil_sen_slope(
    xs: list[float], ys: list[float], *, clip: float = 25.0, max_pairs: int = 20000
) -> dict[str, Any]:
    """Robust median-of-pairwise-slopes estimator with an approximate CI.

    Returns {slope, slope_lo, slope_hi, n, pairs}.  slope is None when
    fewer than 3 usable points or no informative x-spread exists (constant
    dose cannot identify a response slope).  The CI is the central 90%
    band of pairwise slopes — an honest, distribution-free spread measure,
    labelled approximate by construction.
    """
    pts = [
        (x, y)
        for x, y in zip(xs, ys)
        if _finite(x) is not None and _finite(y) is not None
    ]
    n = len(pts)
    if n < 3:
        return {"slope": None, "slope_lo": None, "slope_hi": None, "n": n, "pairs": 0}
    slopes: list[float] = []
    # Deterministic pair thinning for large n: stride the second index.
    total_pairs = n * (n - 1) // 2
    stride = max(1, int(math.ceil(total_pairs / max(1, max_pairs))))
    count = 0
    for i in range(n - 1):
        for j in range(i + 1, n, stride):
            dx = pts[j][0] - pts[i][0]
            if abs(dx) < 1e-12:
                continue
            slopes.append(_clip((pts[j][1] - pts[i][1]) / dx, clip))
            count += 1
    if not slopes:
        return {"slope": None, "slope_lo": None, "slope_hi": None, "n": n, "pairs": 0}
    slopes.sort()
    mid = len(slopes) // 2
    if len(slopes) % 2:
        slope = slopes[mid]
    else:
        slope = 0.5 * (slopes[mid - 1] + slopes[mid])
    lo_idx = max(0, int(0.05 * (len(slopes) - 1)))
    hi_idx = min(len(slopes) - 1, int(0.95 * (len(slopes) - 1)))
    return {
        "slope": round(slope, 8),
        "slope_lo": round(slopes[lo_idx], 8),
        "slope_hi": round(slopes[hi_idx], 8),
        "n": n,
        "pairs": count,
    }


def normalize_susceptibility(slope: float | None, *, slope_scale: float = 4.0) -> float | None:
    """Map a measured response slope to the engine's [0,1] susceptibility.

    Zero or negative slope (market absorbing evidence) -> 0.0.
    slope >= slope_scale -> 1.0.  ``slope_scale`` is a configured prior
    (Z units of response per unit evidence dose considered "fully
    susceptible") — recorded on every estimate.
    """
    s = _finite(slope)
    if s is None:
        return None
    if slope_scale <= 0:
        return None
    return max(0.0, min(1.0, s / slope_scale))


def shrink_slope(
    child_slope: float | None,
    child_n: int,
    parent_slope: float | None,
    *,
    shrinkage_k: float = 10.0,
) -> tuple[float | None, bool]:
    """Empirical-Bayes style partial pooling toward the parent estimate.

    shrunk = (n*child + k*parent) / (n + k).  Returns (slope, was_shrunk).
    With no parent, the child stands alone (was_shrunk=False); with no
    child, returns the parent (was_shrunk=True).
    """
    c = _finite(child_slope)
    p = _finite(parent_slope)
    if c is None and p is None:
        return None, False
    if c is None:
        return p, True
    if p is None:
        return c, False
    k = max(0.0, float(shrinkage_k))
    if k == 0.0:
        return c, False
    shrunk = (child_n * c + k * p) / (child_n + k)
    return round(shrunk, 8), True


def classify_response_acceleration(
    ordered_doses: list[float],
    ordered_zs: list[float],
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Is each incremental evidence dose producing a stronger response?

    Splits chronologically ordered matured observations into halves,
    estimates the response slope in each, and compares.  Requires
    ``min_obs_acceleration_window`` per half; otherwise INSUFFICIENT_DATA.
    An operationally-defensible d(chi)/dt approximation — labelled as a
    windowed contrast, not a derivative.
    """
    cfg = {**DEFAULT_PARAMS, **(params or {})}
    min_win = int(cfg["min_obs_acceleration_window"])
    n = min(len(ordered_doses), len(ordered_zs))
    if n < 2 * min_win:
        return {
            "acceleration_class": ACCEL_INSUFFICIENT,
            "slope_early": None,
            "slope_late": None,
            "delta": None,
            "window_size": None,
            "estimator": "windowed_slope_contrast_v1",
        }
    half = n // 2
    early = theil_sen_slope(
        list(ordered_doses[:half]), list(ordered_zs[:half]),
        clip=float(cfg["slope_clip"]), max_pairs=int(cfg["max_pairs"]),
    )
    late = theil_sen_slope(
        list(ordered_doses[half:]), list(ordered_zs[half:]),
        clip=float(cfg["slope_clip"]), max_pairs=int(cfg["max_pairs"]),
    )
    if early["slope"] is None or late["slope"] is None:
        return {
            "acceleration_class": ACCEL_INSUFFICIENT,
            "slope_early": early["slope"],
            "slope_late": late["slope"],
            "delta": None,
            "window_size": half,
            "estimator": "windowed_slope_contrast_v1",
        }
    delta = late["slope"] - early["slope"]
    min_delta = float(cfg["acceleration_min_delta_fraction"]) * float(cfg["slope_scale"])
    if delta > min_delta:
        cls = ACCEL_ACCELERATING
    elif delta < -min_delta:
        cls = ACCEL_DECELERATING
    else:
        cls = ACCEL_STABLE
    return {
        "acceleration_class": cls,
        "slope_early": early["slope"],
        "slope_late": late["slope"],
        "delta": round(delta, 8),
        "window_size": half,
        "estimator": "windowed_slope_contrast_v1",
    }


def estimate_scope(
    observations: list[dict[str, Any]],
    *,
    scope_type: str,
    scope_key: str,
    horizon: int,
    params: dict[str, Any] | None = None,
    parent_slope: float | None = None,
    min_obs: int | None = None,
) -> dict[str, Any] | None:
    """Estimate susceptibility for one scope (ticker/sector/market/global).

    ``observations`` rows need: dose (float), z (float), event_ts (str,
    chronological sort key).  Returns None when the sample gate fails —
    the hierarchy simply falls through; nothing is fabricated.
    """
    cfg = {**DEFAULT_PARAMS, **(params or {})}
    gate = int(min_obs if min_obs is not None else cfg["min_obs_pooled"])
    rows = sorted(
        (
            r for r in observations
            if _finite(r.get("dose")) is not None and _finite(r.get("z")) is not None
        ),
        key=lambda r: str(r.get("event_ts", "")),
    )
    if len(rows) < gate:
        return None
    doses = [float(r["dose"]) for r in rows]
    zs = [float(r["z"]) for r in rows]
    fit = theil_sen_slope(
        doses, zs, clip=float(cfg["slope_clip"]), max_pairs=int(cfg["max_pairs"])
    )
    if fit["slope"] is None:
        return None
    slope, was_shrunk = shrink_slope(
        fit["slope"], fit["n"], parent_slope, shrinkage_k=float(cfg["shrinkage_k"])
    )
    chi_norm = normalize_susceptibility(slope, slope_scale=float(cfg["slope_scale"]))
    accel = classify_response_acceleration(doses, zs, params=cfg)
    return {
        "scope_type": scope_type,
        "scope_key": scope_key,
        "horizon": int(horizon),
        "estimator": SUSCEPTIBILITY_ESTIMATOR_VERSION,
        "raw_slope": fit["slope"],
        "slope": slope,
        "slope_lo": fit["slope_lo"],
        "slope_hi": fit["slope_hi"],
        "was_shrunk": bool(was_shrunk and parent_slope is not None),
        "shrinkage_k": float(cfg["shrinkage_k"]),
        "chi_norm": round(chi_norm, 6) if chi_norm is not None else None,
        "slope_scale": float(cfg["slope_scale"]),
        "n": fit["n"],
        "pairs": fit["pairs"],
        "acceleration_class": accel["acceleration_class"],
        "slope_early": accel["slope_early"],
        "slope_late": accel["slope_late"],
        "acceleration_delta": accel["delta"],
        "score_semantics": "measured_response_slope_not_probability",
    }


def resolve_susceptibility(
    *,
    ticker: str,
    market: str,
    sector: str | None,
    horizon: int,
    estimates: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the fallback hierarchy for one (ticker, horizon) lookup.

    ``estimates`` is the persisted estimate table (list of dicts as
    produced by ``estimate_scope``).  Returns the chosen estimate plus a
    ``fallback_path`` recording every level tried and why it was skipped.
    When nothing measurable exists the result is
    ``{"source": "HEURISTIC_PROXY", ...}`` and the engine keeps its proxy.
    """
    cfg = {**DEFAULT_PARAMS, **(params or {})}
    path: list[dict[str, str]] = []

    def _find(scope_type: str, scope_key: str) -> dict[str, Any] | None:
        for est in estimates:
            if (
                est.get("scope_type") == scope_type
                and str(est.get("scope_key", "")).upper() == scope_key.upper()
                and int(est.get("horizon", -1)) == int(horizon)
                and est.get("chi_norm") is not None
            ):
                return est
        return None

    ticker_est = _find("TICKER", ticker)
    if ticker_est is not None and int(ticker_est.get("n", 0)) >= int(cfg["min_obs_ticker"]):
        path.append({"level": SOURCE_MEASURED_TICKER, "status": "used"})
        return {
            "source": SOURCE_MEASURED_TICKER,
            "fallback_level": 1,
            "estimate": ticker_est,
            "fallback_path": path,
        }
    path.append({
        "level": SOURCE_MEASURED_TICKER,
        "status": "insufficient_sample" if ticker_est is None else "below_ticker_gate",
    })

    if sector:
        sector_est = _find("SECTOR", f"{sector}|{market}") or _find("SECTOR", sector)
        if sector_est is not None:
            path.append({"level": SOURCE_SHRUNK_SECTOR, "status": "used"})
            return {
                "source": SOURCE_SHRUNK_SECTOR,
                "fallback_level": 2,
                "estimate": sector_est,
                "fallback_path": path,
            }
        path.append({"level": SOURCE_SHRUNK_SECTOR, "status": "insufficient_sample"})
    else:
        path.append({"level": SOURCE_SHRUNK_SECTOR, "status": "sector_unavailable"})

    market_est = _find("MARKET", market)
    if market_est is not None:
        path.append({"level": SOURCE_MEASURED_MARKET, "status": "used"})
        return {
            "source": SOURCE_MEASURED_MARKET,
            "fallback_level": 3,
            "estimate": market_est,
            "fallback_path": path,
        }
    path.append({"level": SOURCE_MEASURED_MARKET, "status": "insufficient_sample"})

    global_est = _find("GLOBAL", "GLOBAL")
    if global_est is not None:
        path.append({"level": SOURCE_MEASURED_GLOBAL, "status": "used"})
        return {
            "source": SOURCE_MEASURED_GLOBAL,
            "fallback_level": 4,
            "estimate": global_est,
            "fallback_path": path,
        }
    path.append({"level": SOURCE_MEASURED_GLOBAL, "status": "insufficient_sample"})

    path.append({"level": SOURCE_HEURISTIC_PROXY, "status": "used"})
    return {
        "source": SOURCE_HEURISTIC_PROXY,
        "fallback_level": 5,
        "estimate": None,
        "fallback_path": path,
    }


CONVEXITY_ESTIMATOR_VERSION = "cc_quadratic_ls_v1"

CC_NEGATIVE = "NEGATIVE"
CC_APPROX_LINEAR = "APPROXIMATELY_LINEAR"
CC_POSITIVE = "POSITIVE"
CC_UNSTABLE = "UNSTABLE"
CC_INSUFFICIENT = "INSUFFICIENT_DATA"

CONVEXITY_STATES: tuple[str, ...] = (
    CC_NEGATIVE, CC_APPROX_LINEAR, CC_POSITIVE, CC_UNSTABLE, CC_INSUFFICIENT,
)

DEFAULT_CONVEXITY_PARAMS: dict[str, Any] = {
    "min_obs_convexity": 40,
    # Dose spread requirement: (p90 - p10) of dose must exceed this
    # fraction of the dose range used for normalization.
    "min_dose_spread": 0.02,
    # |quadratic coefficient| below this (in Z per dose^2 units) counts as
    # approximately linear.
    "linear_band": 2.0,
    # Split-half stability: the quadratic coefficient must keep its sign
    # in both chronological halves to be called a state.
    "coefficient_clip": 500.0,
}


def _quadratic_fit(xs: list[float], ys: list[float]) -> float | None:
    """Least-squares quadratic coefficient of y = a + b·x + c·x².

    Solves the 3x3 normal equations directly (stdlib only).  Returns the
    quadratic coefficient c, or None on degenerate/singular design.
    """
    n = len(xs)
    if n < 3:
        return None
    s = [0.0] * 5
    for x in xs:
        p = 1.0
        for k in range(5):
            s[k] += p
            p *= x
    t = [0.0] * 3
    for x, y in zip(xs, ys):
        t[0] += y
        t[1] += y * x
        t[2] += y * x * x
    # Normal-equation matrix [[s0,s1,s2],[s1,s2,s3],[s2,s3,s4]] · [a,b,c] = t
    m = [
        [s[0], s[1], s[2], t[0]],
        [s[1], s[2], s[3], t[1]],
        [s[2], s[3], s[4], t[2]],
    ]
    for col in range(3):
        pivot_row = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot_row][col]) < 1e-12:
            return None
        m[col], m[pivot_row] = m[pivot_row], m[col]
        for r in range(3):
            if r == col:
                continue
            factor = m[r][col] / m[col][col]
            for k in range(col, 4):
                m[r][k] -= factor * m[col][k]
    c = m[2][3] / m[2][2]
    return c if math.isfinite(c) else None


def estimate_catalytic_convexity(
    observations: list[dict[str, Any]],
    *,
    horizon: int,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """EXPERIMENTAL measured catalytic convexity: d²E[R]/dE².

    Quadratic coefficient of the dose→response curve, subject to hard
    gates: minimum sample, minimum dose spread, and split-half sign
    stability.  Anything failing a gate returns INSUFFICIENT_DATA or
    UNSTABLE — a positive coefficient is never reported as meaningful
    from a sample that cannot support it.  Never a probability; never a
    state-machine gate in this version.
    """
    cfg = {**DEFAULT_CONVEXITY_PARAMS, **(params or {})}
    rows = sorted(
        (
            r for r in observations
            if _finite(r.get("dose")) is not None and _finite(r.get("z")) is not None
        ),
        key=lambda r: str(r.get("event_ts", "")),
    )
    base = {
        "estimator": CONVEXITY_ESTIMATOR_VERSION,
        "horizon": int(horizon),
        "coefficient": None,
        "coefficient_half_1": None,
        "coefficient_half_2": None,
        "n": len(rows),
        "dose_spread": None,
        "state": CC_INSUFFICIENT,
        "is_experimental": True,
        "score_semantics": "experimental_response_curvature_not_probability",
    }
    if len(rows) < int(cfg["min_obs_convexity"]):
        return base
    doses = [float(r["dose"]) for r in rows]
    zs = [float(r["z"]) for r in rows]
    ordered = sorted(doses)
    p10 = ordered[int(0.10 * (len(ordered) - 1))]
    p90 = ordered[int(0.90 * (len(ordered) - 1))]
    spread = p90 - p10
    base["dose_spread"] = round(spread, 8)
    if spread < float(cfg["min_dose_spread"]):
        base["state"] = CC_INSUFFICIENT
        return base
    clip = float(cfg["coefficient_clip"])
    coeff = _quadratic_fit(doses, zs)
    if coeff is None:
        return base
    coeff = _clip(coeff, clip)
    half = len(rows) // 2
    c1 = _quadratic_fit(doses[:half], zs[:half])
    c2 = _quadratic_fit(doses[half:], zs[half:])
    base.update({
        "coefficient": round(coeff, 8),
        "coefficient_half_1": round(_clip(c1, clip), 8) if c1 is not None else None,
        "coefficient_half_2": round(_clip(c2, clip), 8) if c2 is not None else None,
    })
    band = float(cfg["linear_band"])
    if abs(coeff) <= band:
        base["state"] = CC_APPROX_LINEAR
        return base
    if c1 is None or c2 is None or (c1 > 0) != (c2 > 0) or (coeff > 0) != (c1 > 0):
        base["state"] = CC_UNSTABLE
        return base
    base["state"] = CC_POSITIVE if coeff > 0 else CC_NEGATIVE
    return base


def market_for_ticker(ticker: str, country: str | None = None) -> str:
    """Market bucket for the hierarchy: INDIA / US / GLOBAL_OTHER.

    Prefers the securities-master country when supplied; else the ticker
    suffix heuristic used elsewhere in the repo (.NS/.BO -> India).
    """
    if isinstance(country, str) and country.strip():
        c = country.strip().upper()
        if c in {"IN", "IND", "INDIA"}:
            return "INDIA"
        if c in {"US", "USA", "UNITED STATES"}:
            return "US"
        return "GLOBAL_OTHER"
    t = (ticker or "").strip().upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return "INDIA"
    if "." not in t and t:
        return "US"
    return "GLOBAL_OTHER"


__all__ = [
    "CONVEXITY_ESTIMATOR_VERSION",
    "CONVEXITY_STATES",
    "CC_NEGATIVE", "CC_APPROX_LINEAR", "CC_POSITIVE", "CC_UNSTABLE", "CC_INSUFFICIENT",
    "DEFAULT_CONVEXITY_PARAMS",
    "estimate_catalytic_convexity",
    "SUSCEPTIBILITY_ESTIMATOR_VERSION",
    "SUSCEPTIBILITY_SOURCES",
    "SOURCE_MEASURED_TICKER", "SOURCE_SHRUNK_SECTOR", "SOURCE_MEASURED_MARKET",
    "SOURCE_MEASURED_GLOBAL", "SOURCE_HEURISTIC_PROXY",
    "ACCELERATION_CLASSES",
    "ACCEL_ACCELERATING", "ACCEL_STABLE", "ACCEL_DECELERATING", "ACCEL_INSUFFICIENT",
    "DEFAULT_PARAMS",
    "theil_sen_slope",
    "normalize_susceptibility",
    "shrink_slope",
    "classify_response_acceleration",
    "estimate_scope",
    "resolve_susceptibility",
    "market_for_ticker",
]
