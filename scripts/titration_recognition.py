"""Price/volume recognition components for the Market Titration layer.

Computes recognition signals that are INDEPENDENT of the evidence feed —
the market's own visible reaction — from locally imported daily OHLCV
bars.  These decouple Visible Market Recognition from the evidence
arrivals that also drive readiness, which is what makes the Pre-Alpha
Gap a meaningful difference rather than a self-comparison.

    price_recognition   in [0,1]:  where the latest close sits in the
                        recent range, plus short-horizon move size scaled
                        by pre-move volatility.
    volume_recognition  in [0,1]:  latest volume versus the recent median.

Pure module (bars in, scores out); missing/short history yields
``available=False`` rather than fabricated zeros.  Advisory-only.
"""

from __future__ import annotations

import math
from typing import Any

RECOGNITION_ESTIMATOR_VERSION = "ohlcv_recognition_v1"

MIN_BARS = 10
RANGE_LOOKBACK = 20
MOVE_LOOKBACK = 5
VOLUME_LOOKBACK = 20


def _finite_pos(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f <= 0:
        return None
    return f


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_recognition_inputs(bars: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Recognition components from ascending daily bars.

    Returns {available, price_recognition, volume_recognition, components,
    bars_used, estimator}.  Anything unavailable is None with a reason —
    never a silent zero.
    """
    out: dict[str, Any] = {
        "available": False,
        "price_recognition": None,
        "volume_recognition": None,
        "components": {},
        "bars_used": 0,
        "estimator": RECOGNITION_ESTIMATOR_VERSION,
        "reason": None,
    }
    if not isinstance(bars, list) or len(bars) < MIN_BARS:
        out["reason"] = "insufficient_bars"
        return out

    closes: list[float] = []
    volumes: list[float | None] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        close = _finite_pos(bar.get("adjusted_close")) or _finite_pos(bar.get("close"))
        if close is None:
            continue
        closes.append(close)
        vol = bar.get("volume")
        volumes.append(
            float(vol)
            if isinstance(vol, (int, float))
            and not isinstance(vol, bool)
            and math.isfinite(float(vol))
            and float(vol) >= 0
            else None
        )
    if len(closes) < MIN_BARS:
        out["reason"] = "insufficient_usable_closes"
        return out
    out["bars_used"] = len(closes)

    # --- price recognition -------------------------------------------------
    window = closes[-(RANGE_LOOKBACK + 1):]
    last = window[-1]
    prior = window[:-1]
    lo, hi = min(prior), max(prior)
    range_position = 0.5 if hi <= lo else _clip01((last - lo) / (hi - lo))

    move_score = 0.0
    pre = closes[:-MOVE_LOOKBACK] if len(closes) > MOVE_LOOKBACK else []
    if len(pre) >= MIN_BARS:
        rets = [
            pre[i + 1] / pre[i] - 1.0 for i in range(len(pre) - 1) if pre[i] > 0
        ][-RANGE_LOOKBACK:]
        if len(rets) >= MIN_BARS - 1:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
            sigma = math.sqrt(max(0.0, var))
            if sigma > 1e-6 and pre[-1] > 0:
                move = last / pre[-1] - 1.0
                z = abs(move) / (sigma * math.sqrt(MOVE_LOOKBACK))
                move_score = _clip01(z / 2.0)
    price_recognition = _clip01(0.6 * range_position + 0.4 * move_score)

    # --- volume recognition -------------------------------------------------
    volume_recognition = None
    usable = [v for v in volumes[-(VOLUME_LOOKBACK + 1):-1] if v is not None and v > 0]
    last_vol = volumes[-1] if volumes else None
    if last_vol is not None and last_vol > 0 and len(usable) >= MIN_BARS - 1:
        ordered = sorted(usable)
        mid = len(ordered) // 2
        median = (
            ordered[mid]
            if len(ordered) % 2
            else 0.5 * (ordered[mid - 1] + ordered[mid])
        )
        if median > 0:
            ratio = last_vol / median
            volume_recognition = _clip01((ratio - 1.0) / 3.0)

    out.update({
        "available": True,
        "price_recognition": round(price_recognition, 6),
        "volume_recognition": (
            round(volume_recognition, 6) if volume_recognition is not None else None
        ),
        "components": {
            "range_position": round(range_position, 6),
            "move_score": round(move_score, 6),
        },
        "reason": None,
    })
    return out


__all__ = [
    "RECOGNITION_ESTIMATOR_VERSION",
    "compute_recognition_inputs",
]
