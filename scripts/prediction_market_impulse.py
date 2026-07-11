"""Prediction-market impulse engine — log-odds belief shifts, typed and gated.

Prediction-market probabilities are continuously updating belief
aggregates, not sentiment.  This module turns persisted probability
snapshots (``narrative_probability_snapshots``, written on every live
refresh) into typed impulses:

    L_t   = ln(p / (1-p)),  p clamped to [eps, 1-eps]
    dL_t  = L_t - L_{t-1}
    v_p   = dL / dt          (per hour)
    a_p   = dv / dt          (per hour^2)
    PMI   = |dL| * Q * I     (liquidity/quality- and independence-weighted)

Honesty contract
----------------
* An impulse requires >= 2 usable snapshots; a single snapshot yields
  ``impulse_available=False`` with a reason — never a fabricated change.
* Duplicate timestamps are collapsed (last wins); out-of-order input is
  sorted deterministically.
* Probability changes are upstream EVIDENCE for causal mapping — nothing
  here claims they predict any stock.
* Confidence bands are snapshot-count based (very_low < 3, low < 6,
  medium < 20, higher_but_contextual >= 20) and liquidity is a quality
  factor, not a truth claim.

Pure module: reads nothing itself; callers pass snapshot rows.
Advisory-only.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

IMPULSE_ENGINE_VERSION = "pm_impulse_v1"

EPS_PROB = 1e-4

REGIME_LEVEL = "LEVEL"
REGIME_REVERSAL = "REVERSAL"

SHIFT_CLASSES: tuple[str, ...] = (
    "NO_MATERIAL_SHIFT", "DRIFT", "SHIFT", "SHOCK", "INSUFFICIENT_DATA",
)


def _parse_ts(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def log_odds(probability: float, *, eps: float = EPS_PROB) -> float | None:
    """Bounded log odds; None for non-finite input."""
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        return None
    p = float(probability)
    if not math.isfinite(p):
        return None
    p = min(1.0 - eps, max(eps, p))
    return math.log(p / (1.0 - p))


def _quality_factor(volume: Any, liquidity: Any) -> tuple[float, list[str]]:
    """Liquidity/volume quality Q in [0.25, 1.0]; missing inputs listed."""
    missing: list[str] = []
    score = 0.0
    parts = 0
    for name, value, scale in (("volume", volume, 50000.0), ("liquidity", liquidity, 20000.0)):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0:
            score += min(1.0, float(value) / scale)
            parts += 1
        else:
            missing.append(name)
    if parts == 0:
        return 0.25, missing  # floor: usable but low-quality evidence
    return max(0.25, min(1.0, score / parts)), missing


def compute_market_impulse(
    snapshots: list[dict[str, Any]],
    *,
    independence_weight: float = 1.0,
) -> dict[str, Any]:
    """Impulse payload for ONE market's snapshot series.

    Snapshot rows need: fetched_at, probability (0..1 or None), and
    optionally volume/liquidity/question/market_id.
    """
    base: dict[str, Any] = {
        "engine_version": IMPULSE_ENGINE_VERSION,
        "impulse_available": False,
        "reason": None,
        "market_id": None,
        "question": None,
        "snapshot_count": 0,
        "usable_snapshot_count": 0,
        "score_semantics": "log_odds_shift_not_probability_of_anything",
    }
    if not isinstance(snapshots, list) or not snapshots:
        base["reason"] = "no_snapshots"
        return base

    usable: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for row in snapshots:
        if not isinstance(row, dict):
            continue
        ts = _parse_ts(row.get("fetched_at"))
        prob = row.get("probability")
        if ts is None or log_odds(prob) is None:
            continue
        usable[ts.isoformat()] = (ts, row)  # duplicate timestamps: last wins
    series = sorted(usable.values(), key=lambda pair: pair[0])
    first_row = series[0][1] if series else snapshots[0]
    base["market_id"] = str(first_row.get("market_id", "") or "")
    base["question"] = str(first_row.get("question", "") or "")[:200]
    base["snapshot_count"] = len(snapshots)
    base["usable_snapshot_count"] = len(series)

    if len(series) < 2:
        base["reason"] = "insufficient_snapshots_for_change"
        if series:
            ts, row = series[0]
            base["latest_probability"] = round(float(row["probability"]), 6)
            base["latest_log_odds"] = round(log_odds(row["probability"]), 6)
            base["latest_timestamp"] = ts.isoformat()
        return base

    points = [
        (ts, float(row["probability"]), log_odds(row["probability"]), row)
        for ts, row in series
    ]
    (t_prev, p_prev, l_prev, _), (t_last, p_last, l_last, row_last) = points[-2], points[-1]
    dt_hours = max(1e-6, (t_last - t_prev).total_seconds() / 3600.0)
    d_log_odds = l_last - l_prev
    velocity = d_log_odds / dt_hours

    acceleration = None
    reversal = False
    if len(points) >= 3:
        t_pp, _, l_pp, _ = points[-3]
        dt_prev_hours = max(1e-6, (t_prev - t_pp).total_seconds() / 3600.0)
        v_prev = (l_prev - l_pp) / dt_prev_hours
        acceleration = (velocity - v_prev) / dt_hours
        reversal = (v_prev > 0 > velocity) or (v_prev < 0 < velocity)

    quality, quality_missing = _quality_factor(
        row_last.get("volume"), row_last.get("liquidity")
    )
    independence = max(0.0, min(1.0, float(independence_weight)))
    pmi = abs(d_log_odds) * quality * independence

    abs_dl = abs(d_log_odds)
    if abs_dl < 0.05:
        shift_class = "NO_MATERIAL_SHIFT"
    elif abs_dl < 0.20:
        shift_class = "DRIFT"
    elif abs_dl < 0.60:
        shift_class = "SHIFT"
    else:
        shift_class = "SHOCK"

    n = len(points)
    if n < 3:
        confidence = "very_low"
    elif n < 6:
        confidence = "low"
    elif n < 20:
        confidence = "medium"
    else:
        confidence = "higher_but_contextual"

    return {
        **base,
        "impulse_available": True,
        "reason": None,
        "timestamp_utc": t_last.isoformat(),
        "probability": round(p_last, 6),
        "probability_change": round(p_last - p_prev, 6),
        "log_odds": round(l_last, 6),
        "log_odds_change": round(d_log_odds, 6),
        "velocity_per_hour": round(velocity, 6),
        "acceleration_per_hour2": (
            round(acceleration, 6) if acceleration is not None else None
        ),
        "reversal": reversal,
        "volume": row_last.get("volume"),
        "liquidity": row_last.get("liquidity"),
        "quality_factor": round(quality, 6),
        "quality_missing_inputs": quality_missing,
        "independence_factor": round(independence, 6),
        "impulse": round(pmi, 6),
        "shift_class": shift_class,
        "confidence": confidence,
        "observation_span_hours": round(
            (t_last - points[0][0]).total_seconds() / 3600.0, 2
        ),
    }


def compute_impulses_by_market(
    snapshots: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Group snapshot rows by market_id and compute per-market impulses."""
    by_market: dict[str, list[dict[str, Any]]] = {}
    for row in snapshots if isinstance(snapshots, list) else []:
        if not isinstance(row, dict):
            continue
        market_id = str(row.get("market_id", "") or "").strip()
        if market_id:
            by_market.setdefault(market_id, []).append(row)
    return {
        market_id: compute_market_impulse(rows)
        for market_id, rows in sorted(by_market.items())
    }


__all__ = [
    "IMPULSE_ENGINE_VERSION",
    "EPS_PROB",
    "SHIFT_CLASSES",
    "log_odds",
    "compute_market_impulse",
    "compute_impulses_by_market",
]
