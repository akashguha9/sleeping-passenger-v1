"""Entry-quality gate — blocks falling-knife and over-extended entries.

Pure module: no I/O, no broker, no network. Takes daily OHLCV history (a list
of dicts with `date`, `open`, `high`, `low`, `close`, `volume`) up to and
including the candidate's buy date, plus optional same-shape history for a
local-market index (used for relative-strength), and returns:

    {
        "entry_quality_score": float in [0, 1],
        "entry_quality_pass":  bool,
        "components":          { feature -> raw + pass },
        "reasons":             list[str],   # explains why pass/fail
    }

Hard gates (all required for pass, when their inputs are available):
    * close > SMA50 and SMA50 rising
    * dist_from_sma50 ∈ [min, max]                    (default [-2%, +12%])
    * 20-day return ≥ percentile floor vs scored universe (default 40th pctl)
    * rs_vs_index 20d > floor                          (default 0)
    * close ≤ (52w-high * (1 + extension_vs_52w_high_max))  (default ≥2% below high)
    * atr14_pct ∈ [min, max]                          (default [1%, 6%])
    * 30-day avg dollar volume ≥ floor                (default 5M local)
    * if risk_band == "core": close > SMA200

Missing OHLCV history (insufficient bars) → entry_quality_pass = False with
reason "insufficient_history". Never fabricate values.

All thresholds come from ``config/thresholds.yaml`` under ``entry_quality:``.
The gate is itself off-by-default if ``enabled: false``.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT


DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "require_close_above_sma50": True,
    "require_sma50_rising": True,
    "require_close_above_sma200_for_core": True,
    "dist_from_sma50_min": -0.02,
    "dist_from_sma50_max": 0.12,
    "mom_20d_percentile_min": 0.40,
    "rs_vs_index_min": 0.0,
    "extension_vs_52w_high_max": -0.02,
    "atr14_pct_min": 0.010,
    "atr14_pct_max": 0.060,
    "adv_local_min": 5_000_000,
    "score_weights": {
        "trend_50": 0.20,
        "trend_200": 0.15,
        "dist_from_sma50": 0.15,
        "mom_20d": 0.20,
        "rs_vs_index": 0.15,
        "extension_vs_52w_high": 0.10,
        "atr14_pct": 0.05,
    },
}

_THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"


def load_entry_quality_config() -> dict[str, Any]:
    """Return the entry_quality config block merged over the spec defaults."""
    merged: dict[str, Any] = {k: v for k, v in DEFAULTS.items() if k != "score_weights"}
    merged["score_weights"] = dict(DEFAULTS["score_weights"])
    try:
        from src.utils.config_loader import load_yaml_config

        config = load_yaml_config(_THRESHOLDS_PATH)
    except Exception:
        return merged
    block = config.get("entry_quality") if isinstance(config, dict) else None
    if not isinstance(block, dict):
        return merged
    for key, value in block.items():
        if key == "score_weights" and isinstance(value, dict):
            merged["score_weights"].update(value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Feature primitives — pure functions on a list of candles up to buy date.
# A "candle" is any object with attributes `close`, `high`, `low`, `volume`,
# or a dict with those keys. We work in lists of floats internally.
# ---------------------------------------------------------------------------


def _series(candles: Iterable[dict[str, Any]], field: str) -> list[float]:
    out: list[float] = []
    for c in candles or []:
        try:
            val = c.get(field) if isinstance(c, dict) else getattr(c, field)
        except AttributeError:
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        out.append(num)
    return out


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _pct_return(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    prev = values[-window - 1]
    if prev == 0:
        return None
    return (values[-1] - prev) / prev


def _max_high(highs: list[float], window: int) -> float | None:
    if len(highs) < window:
        return None
    return max(highs[-window:])


def _atr14(highs: list[float], lows: list[float], closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    trs: list[float] = []
    for i in range(-14, 0):
        h = highs[i]; l = lows[i]; pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / 14


def _percentile(values: list[float], x: float) -> float:
    """Return the percentile rank (0..1) of x within values (inclusive)."""
    if not values:
        return 0.0
    below = sum(1 for v in values if v <= x)
    return below / len(values)


# ---------------------------------------------------------------------------
# Main gate
# ---------------------------------------------------------------------------


def compute_entry_quality(
    *,
    candles: list[dict[str, Any]],
    index_candles: list[dict[str, Any]] | None = None,
    universe_mom_20d: list[float] | None = None,
    risk_band: str = "core",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one ticker's entry quality at the LAST candle in `candles`.

    `candles`: sorted ascending, most recent at the end. The last entry is the
        proposed buy date (close used as the buy price proxy).
    `index_candles`: same-shape series for the local market index (e.g. SPX
        for US, NIFTY for IN, DAX for DE) to compute relative strength.
        If None or insufficient history, RS check is skipped (component = 0.5
        but it does NOT cause a hard fail — RS_min applies only when computable).
    `universe_mom_20d`: today's 20d returns across the scored universe; used
        to compute mom_20d percentile. If None, the percentile gate is skipped.
    `risk_band`: "core" applies the SMA200 trend filter; other bands skip it.
    """
    cfg = config or load_entry_quality_config()
    if not cfg.get("enabled", True):
        return {
            "entry_quality_score": 1.0,
            "entry_quality_pass": True,
            "components": {},
            "reasons": ["entry_quality.disabled — gate bypassed"],
        }

    closes = _series(candles, "close")
    highs = _series(candles, "high")
    lows = _series(candles, "low")
    volumes = _series(candles, "volume")
    if len(closes) < 21:
        return {
            "entry_quality_score": 0.0,
            "entry_quality_pass": False,
            "components": {},
            "reasons": [f"insufficient_history: {len(closes)} bars (need ≥ 21)"],
        }

    price = closes[-1]
    components: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    soft_scores: dict[str, float] = {}

    # --- trend_50 -----------------------------------------------------------
    sma50_now = _sma(closes, 50)
    sma50_prev = _sma(closes[:-5], 50) if len(closes) >= 55 else None
    if sma50_now is None:
        components["trend_50"] = {"raw": None, "pass": False, "note": "need ≥50 bars"}
        reasons.append("trend_50: insufficient history")
    else:
        rising = (sma50_prev is not None) and (sma50_now > sma50_prev)
        above = price > sma50_now
        cond = (above if cfg["require_close_above_sma50"] else True) and (
            rising if cfg["require_sma50_rising"] else True
        )
        components["trend_50"] = {
            "raw": {"price": price, "sma50": sma50_now, "rising": rising, "above": above},
            "pass": bool(cond),
        }
        soft_scores["trend_50"] = 1.0 if cond else 0.0
        if not cond:
            reasons.append(f"trend_50: above={above}, rising={rising}")

    # --- trend_200 ----------------------------------------------------------
    sma200 = _sma(closes, 200)
    required_200 = (risk_band == "core") and cfg["require_close_above_sma200_for_core"]
    if sma200 is None:
        components["trend_200"] = {"raw": None, "pass": not required_200, "note": "need ≥200 bars"}
        if required_200:
            reasons.append("trend_200: insufficient history (core requires SMA200)")
        soft_scores["trend_200"] = 0.5 if sma200 is None else 0.0
    else:
        above_200 = price > sma200
        cond = above_200 if required_200 else True
        components["trend_200"] = {
            "raw": {"price": price, "sma200": sma200, "above": above_200},
            "pass": bool(cond),
        }
        soft_scores["trend_200"] = 1.0 if above_200 else 0.0
        if not cond:
            reasons.append(f"trend_200: core band requires close>SMA200 (got {above_200})")

    # --- dist_from_sma50 ----------------------------------------------------
    if sma50_now:
        dist = (price - sma50_now) / sma50_now
        lo = float(cfg["dist_from_sma50_min"])
        hi = float(cfg["dist_from_sma50_max"])
        cond = lo <= dist <= hi
        components["dist_from_sma50"] = {"raw": dist, "pass": cond, "band": [lo, hi]}
        # Soft score: tent-shape — peak at middle of band, 0 at edges.
        center = (lo + hi) / 2
        half = max(hi - center, center - lo, 1e-9)
        soft_scores["dist_from_sma50"] = max(0.0, 1.0 - abs(dist - center) / half) if cond else 0.0
        if not cond:
            reasons.append(f"dist_from_sma50: {dist:+.2%} outside [{lo:+.0%}, {hi:+.0%}]")
    else:
        components["dist_from_sma50"] = {"raw": None, "pass": False, "note": "no SMA50"}
        soft_scores["dist_from_sma50"] = 0.0

    # --- 20-day return + percentile vs universe ----------------------------
    mom_20d = _pct_return(closes, 20)
    if mom_20d is None:
        components["mom_20d"] = {"raw": None, "pass": False}
        soft_scores["mom_20d"] = 0.0
        reasons.append("mom_20d: insufficient history")
    else:
        if universe_mom_20d:
            pct = _percentile(universe_mom_20d, mom_20d)
            floor = float(cfg["mom_20d_percentile_min"])
            cond = pct >= floor
            components["mom_20d"] = {
                "raw": mom_20d, "pct": pct, "pass": cond, "floor": floor,
            }
            soft_scores["mom_20d"] = float(pct)
            if not cond:
                reasons.append(f"mom_20d: pct {pct:.2f} < floor {floor:.2f}")
        else:
            # No universe context: positive 20d return is a softer floor.
            cond = mom_20d > 0
            components["mom_20d"] = {
                "raw": mom_20d, "pct": None, "pass": cond, "floor": "universe_unavailable_fallback>0",
            }
            soft_scores["mom_20d"] = 1.0 if cond else max(0.0, 0.5 + 5 * mom_20d)
            if not cond:
                reasons.append(f"mom_20d: {mom_20d:+.2%} ≤ 0 (universe unavailable)")

    # --- relative strength vs index (20d) ----------------------------------
    if index_candles is not None:
        idx_closes = _series(index_candles, "close")
        idx_mom = _pct_return(idx_closes, 20)
    else:
        idx_mom = None
    if idx_mom is None or mom_20d is None:
        components["rs_vs_index"] = {"raw": None, "pass": True, "note": "skipped (no index data)"}
        soft_scores["rs_vs_index"] = 0.5
    else:
        rs = mom_20d - idx_mom
        floor = float(cfg["rs_vs_index_min"])
        cond = rs >= floor
        components["rs_vs_index"] = {
            "raw": rs, "stock_20d": mom_20d, "index_20d": idx_mom, "pass": cond, "floor": floor,
        }
        # Map rs in [-0.10, +0.10] → [0, 1]
        soft_scores["rs_vs_index"] = max(0.0, min(1.0, 0.5 + 5 * rs))
        if not cond:
            reasons.append(f"rs_vs_index: {rs:+.2%} < floor {floor:+.2%}")

    # --- distance from 52w-high --------------------------------------------
    high_252 = _max_high(highs, 252) if len(highs) >= 252 else (max(highs) if highs else None)
    if high_252 and high_252 > 0:
        ext = (price - high_252) / high_252  # ≤ 0 means below the high
        ceiling = float(cfg["extension_vs_52w_high_max"])
        cond = ext <= ceiling
        components["extension_vs_52w_high"] = {
            "raw": ext, "ceiling": ceiling, "52w_high": high_252, "pass": cond,
        }
        # Soft score: penalize within 5% of high; peak around -10..-20% below.
        if ext > 0:
            soft_scores["extension_vs_52w_high"] = 0.0
        elif ext > -0.20:
            soft_scores["extension_vs_52w_high"] = max(0.0, min(1.0, -ext / 0.10))
        else:
            soft_scores["extension_vs_52w_high"] = 1.0
        if not cond:
            reasons.append(
                f"extension_vs_52w_high: {ext:+.2%} > ceiling {ceiling:+.2%} (within reversion zone)"
            )
    else:
        components["extension_vs_52w_high"] = {"raw": None, "pass": False}
        soft_scores["extension_vs_52w_high"] = 0.0

    # --- ATR(14)/close band -------------------------------------------------
    atr = _atr14(highs, lows, closes)
    if atr is None or price == 0:
        components["atr14_pct"] = {"raw": None, "pass": False}
        soft_scores["atr14_pct"] = 0.0
        reasons.append("atr14_pct: insufficient history")
    else:
        atrp = atr / price
        lo = float(cfg["atr14_pct_min"]); hi = float(cfg["atr14_pct_max"])
        cond = lo <= atrp <= hi
        components["atr14_pct"] = {"raw": atrp, "band": [lo, hi], "pass": cond}
        center = (lo + hi) / 2
        half = max(hi - center, center - lo, 1e-9)
        soft_scores["atr14_pct"] = max(0.0, 1.0 - abs(atrp - center) / half) if cond else 0.0
        if not cond:
            reasons.append(f"atr14_pct: {atrp:.2%} outside [{lo:.1%}, {hi:.1%}]")

    # --- liquidity floor (local currency 30d ADV) --------------------------
    if len(closes) >= 30 and len(volumes) >= 30:
        adv = sum(closes[-i] * volumes[-i] for i in range(1, 31)) / 30
        floor = float(cfg["adv_local_min"])
        cond = adv >= floor
        components["adv_local"] = {"raw": adv, "floor": floor, "pass": cond}
        if not cond:
            reasons.append(f"adv_local: {adv:,.0f} < floor {floor:,.0f}")
    else:
        components["adv_local"] = {"raw": None, "pass": False, "note": "need ≥30 bars"}
        reasons.append("adv_local: insufficient history")

    # --- aggregate ----------------------------------------------------------
    hard_pass = all(comp["pass"] for comp in components.values())
    weights = cfg["score_weights"]
    total_w = sum(float(weights.get(k, 0.0)) for k in soft_scores) or 1.0
    score = sum(float(weights.get(k, 0.0)) * soft_scores[k] for k in soft_scores) / total_w
    score = round(max(0.0, min(1.0, score)), 4)

    return {
        "entry_quality_score": score,
        "entry_quality_pass": bool(hard_pass),
        "components": components,
        "reasons": reasons,
    }


__all__ = [
    "DEFAULTS",
    "load_entry_quality_config",
    "compute_entry_quality",
]
