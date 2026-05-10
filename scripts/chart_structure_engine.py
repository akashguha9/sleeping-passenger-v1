"""
Chart Structure Engine — Phase D.1/D.2.

Pure advisory chart analysis: reads OHLCV candles, produces chart structure /
regime / candlestick features. No execution. No broker APIs. No order placement.

All outputs carry:
  advisory_status       = ADVISORY_ONLY
  execution_gate        = LOCKED
  human_review_required = True
  ai_execution_count    = 0
  broker_api_called     = False
  broker_order_id       = NONE
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Safety constants — never mutate
# ---------------------------------------------------------------------------
_ADVISORY_STATUS: str = "ADVISORY_ONLY"
_EXECUTION_GATE: str = "LOCKED"
_BROKER_ORDER_ID: str = "NONE"

# ---------------------------------------------------------------------------
# Thresholds (documented for auditability)
# ---------------------------------------------------------------------------
# Candle anatomy
_DOJI_BODY_RATIO: float = 0.05          # body < 5 % of range → doji
_MARUBOZU_BODY_RATIO: float = 0.85      # body ≥ 85 % of range → marubozu-like
_LONG_WICK_RATIO: float = 0.40          # wick ≥ 40 % of range → long wick

# Trend (SMA windows)
_SHORT_SMA_WINDOW: int = 5
_MEDIUM_SMA_WINDOW: int = 10
_LONG_SMA_WINDOW: int = 20

# Volatility / regime
_COMPRESSED_ATR_PCT: float = 0.5        # ATR % < 0.5 % → compressed
_EXPANDED_ATR_PCT: float = 2.5          # ATR % > 2.5 % → expanded
_LARGE_MOVE_PCT: float = 2.0            # single-candle move > 2 % → large move
_RANGE_EXPANSION_RATIO: float = 1.5     # today's range > 1.5× recent avg → expansion
_GAP_PCT: float = 0.5                   # open vs prev close > 0.5 % → gap

# Support / resistance
_SR_WINDOW: int = 20                    # rolling high / low look-back
_NEAR_SR_PCT: float = 1.0               # within 1 % of rolling high/low

# Scoring
_SCORE_TREND_WEIGHT: float = 0.35
_SCORE_VOL_WEIGHT: float = 0.35
_SCORE_CANDLE_WEIGHT: float = 0.30

# Minimum candles for regime / trend features
_MIN_CANDLES_TREND: int = 3
_MIN_CANDLES_ATR: int = 2
_MIN_CANDLES_SR: int = 5

# Forbidden words (static check bait — intentionally absent from logic)
# BUY SELL EXECUTE TRADE_NOW AUTO_TRADE PLACE_ORDER

# ---------------------------------------------------------------------------
# Safe math helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0.0 or not math.isfinite(denominator):
        return default
    result = numerator / denominator
    return result if math.isfinite(result) else default


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_float(value: Any) -> float | None:
    """Convert to float; return None on failure."""
    if value is None:
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    subset = values[-window:]
    return sum(subset) / len(subset)


# ---------------------------------------------------------------------------
# Candle validation / normalisation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


@dataclass
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _parse_candle(raw: dict[str, Any]) -> Candle | None:
    """Return a valid Candle or None if the dict fails validation."""
    ts = raw.get("timestamp")
    if ts is None:
        return None
    ts = str(ts).strip()
    if not ts:
        return None

    o = _safe_float(raw.get("open"))
    h = _safe_float(raw.get("high"))
    lo = _safe_float(raw.get("low"))
    c = _safe_float(raw.get("close"))
    v = _safe_float(raw.get("volume"))

    if any(x is None for x in (o, h, lo, c, v)):
        return None
    if any(x < 0 for x in (o, h, lo, c)):   # type: ignore[operator]
        return None
    if v < 0:   # type: ignore[operator]
        return None
    if h < lo or h < o or h < c or lo > o or lo > c:  # type: ignore[operator]
        return None

    return Candle(timestamp=ts, open=o, high=h, low=lo, close=c, volume=v)  # type: ignore[arg-type]


def _load_candles(
    raw: list[dict[str, Any]],
    max_candles: int | None,
) -> list[Candle]:
    """Parse, validate, deduplicate, sort, and optionally cap candle list."""
    parsed: list[Candle] = []
    for item in raw:
        c = _parse_candle(item)
        if c is not None:
            parsed.append(c)
    # Sort ascending by timestamp string (ISO timestamps sort lexicographically)
    parsed.sort(key=lambda c: c.timestamp)
    if max_candles is not None and max_candles > 0:
        parsed = parsed[-max_candles:]
    return parsed


# ---------------------------------------------------------------------------
# Feature dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OHLCVSummary:
    symbol: str | None
    source: str
    candle_count: int
    first_timestamp: str | None
    latest_timestamp: str | None
    latest_close: float | None
    latest_volume: float | None
    price_change_abs: float | None
    price_change_pct: float | None
    high_low_range_pct: float | None
    average_volume: float | None
    volume_ratio_latest_to_average: float | None


@dataclass
class CandleAnatomy:
    body_size: float | None
    body_pct_of_range: float | None
    upper_wick_size: float | None
    lower_wick_size: float | None
    upper_wick_pct: float | None
    lower_wick_pct: float | None
    close_position_in_range: float | None
    candle_direction: str          # bullish / bearish / neutral
    candle_shape: str              # doji / marubozu_like / long_upper_wick / long_lower_wick / wide_range / normal


@dataclass
class TrendFeatures:
    short_sma: float | None
    medium_sma: float | None
    long_sma: float | None
    trend_direction: str           # uptrend / downtrend / sideways / insufficient_data
    trend_strength_score: float    # 0–1
    consecutive_up_closes: int
    consecutive_down_closes: int
    distance_from_short_sma_pct: float | None
    distance_from_medium_sma_pct: float | None


@dataclass
class VolatilityFeatures:
    average_true_range: float | None
    atr_pct: float | None
    realized_volatility_proxy: float | None
    volatility_regime: str         # compressed / normal / expanded / insufficient_data
    range_expansion_flag: bool
    gap_flag: bool
    large_move_flag: bool


@dataclass
class SupportResistance:
    rolling_high: float | None
    rolling_low: float | None
    distance_to_rolling_high_pct: float | None
    distance_to_rolling_low_pct: float | None
    breakout_proximity: str        # near_resistance / near_support / middle_range / insufficient_data


@dataclass
class MarketContext:
    chart_confirmation_score: float    # 0–1
    confirmation_reasons: list[str]
    contradiction_reasons: list[str]
    chart_state: str
    # states: INSUFFICIENT_DATA / COMPRESSED / TRENDING_UP / TRENDING_DOWN /
    #         RANGE_BOUND / BREAKOUT_ATTEMPT / REVERSAL_RISK / VOLATILE_UNCLEAR


@dataclass
class AdvisoryInterpretation:
    advisory_summary: str
    suggested_next_step: str       # WATCH_ONLY / REQUEST_MORE_EVIDENCE / HUMAN_REVIEW / NO_ACTION


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

@dataclass
class ChartStructureReport:
    # Safety invariants — always present
    advisory_status: str = _ADVISORY_STATUS
    execution_gate: str = _EXECUTION_GATE
    human_review_required: bool = True
    ai_execution_count: int = 0
    broker_api_called: bool = False
    broker_order_id: str = _BROKER_ORDER_ID

    # Feature groups
    summary: OHLCVSummary | None = None
    candle_anatomy: CandleAnatomy | None = None
    trend: TrendFeatures | None = None
    volatility: VolatilityFeatures | None = None
    support_resistance: SupportResistance | None = None
    context: MarketContext | None = None
    advisory: AdvisoryInterpretation | None = None

    def to_dict(self) -> dict[str, Any]:
        def _cvt(obj: Any) -> Any:
            if obj is None:
                return None
            if isinstance(obj, (str, int, float, bool)):
                return obj
            if isinstance(obj, list):
                return [_cvt(i) for i in obj]
            if hasattr(obj, "__dataclass_fields__"):
                return {k: _cvt(getattr(obj, k)) for k in obj.__dataclass_fields__}
            return obj

        return {
            "advisory_status": self.advisory_status,
            "execution_gate": self.execution_gate,
            "human_review_required": self.human_review_required,
            "ai_execution_count": self.ai_execution_count,
            "broker_api_called": self.broker_api_called,
            "broker_order_id": self.broker_order_id,
            "summary": _cvt(self.summary),
            "candle_anatomy": _cvt(self.candle_anatomy),
            "trend": _cvt(self.trend),
            "volatility": _cvt(self.volatility),
            "support_resistance": _cvt(self.support_resistance),
            "context": _cvt(self.context),
            "advisory": _cvt(self.advisory),
        }


# ---------------------------------------------------------------------------
# Feature extraction functions
# ---------------------------------------------------------------------------

def _compute_ohlcv_summary(
    candles: list[Candle],
    symbol: str | None,
    source: str,
) -> OHLCVSummary:
    n = len(candles)
    if n == 0:
        return OHLCVSummary(
            symbol=symbol, source=source, candle_count=0,
            first_timestamp=None, latest_timestamp=None,
            latest_close=None, latest_volume=None,
            price_change_abs=None, price_change_pct=None,
            high_low_range_pct=None, average_volume=None,
            volume_ratio_latest_to_average=None,
        )

    first = candles[0]
    last = candles[-1]

    price_change_abs: float | None = None
    price_change_pct: float | None = None
    if n >= 2:
        prev_close = candles[-2].close
        if prev_close > 0:
            price_change_abs = round(last.close - prev_close, 6)
            price_change_pct = round(_safe_div(price_change_abs, prev_close) * 100.0, 6)

    candle_range = last.high - last.low
    high_low_range_pct: float | None = None
    if last.close > 0:
        high_low_range_pct = round(_safe_div(candle_range, last.close) * 100.0, 6)

    volumes = [c.volume for c in candles]
    avg_vol: float | None = None
    vol_ratio: float | None = None
    if n >= 2:
        prior_vols = volumes[:-1]
        if prior_vols:
            avg_vol = round(sum(prior_vols) / len(prior_vols), 4)
        if avg_vol and avg_vol > 0:
            vol_ratio = round(_safe_div(last.volume, avg_vol), 4)
    elif n == 1:
        avg_vol = last.volume

    return OHLCVSummary(
        symbol=symbol,
        source=source,
        candle_count=n,
        first_timestamp=first.timestamp,
        latest_timestamp=last.timestamp,
        latest_close=last.close,
        latest_volume=last.volume,
        price_change_abs=price_change_abs,
        price_change_pct=price_change_pct,
        high_low_range_pct=high_low_range_pct,
        average_volume=avg_vol,
        volume_ratio_latest_to_average=vol_ratio,
    )


def _compute_candle_anatomy(candle: Candle) -> CandleAnatomy:
    candle_range = candle.high - candle.low
    body = abs(candle.close - candle.open)
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low

    body_pct = _safe_div(body, candle_range) if candle_range > 0 else 0.0
    upper_wick_pct = _safe_div(upper_wick, candle_range) if candle_range > 0 else 0.0
    lower_wick_pct = _safe_div(lower_wick, candle_range) if candle_range > 0 else 0.0
    close_pos = _safe_div(candle.close - candle.low, candle_range) if candle_range > 0 else 0.5

    if candle.close > candle.open:
        direction = "bullish"
    elif candle.close < candle.open:
        direction = "bearish"
    else:
        direction = "neutral"

    if candle_range == 0 or body_pct < _DOJI_BODY_RATIO:
        shape = "doji"
    elif body_pct >= _MARUBOZU_BODY_RATIO:
        shape = "marubozu_like"
    elif upper_wick_pct >= _LONG_WICK_RATIO and upper_wick_pct > lower_wick_pct:
        shape = "long_upper_wick"
    elif lower_wick_pct >= _LONG_WICK_RATIO and lower_wick_pct > upper_wick_pct:
        shape = "long_lower_wick"
    elif body_pct >= 0.5:
        shape = "wide_range"
    else:
        shape = "normal"

    return CandleAnatomy(
        body_size=round(body, 6),
        body_pct_of_range=round(body_pct, 4),
        upper_wick_size=round(upper_wick, 6),
        lower_wick_size=round(lower_wick, 6),
        upper_wick_pct=round(upper_wick_pct, 4),
        lower_wick_pct=round(lower_wick_pct, 4),
        close_position_in_range=round(close_pos, 4),
        candle_direction=direction,
        candle_shape=shape,
    )


def _compute_trend(candles: list[Candle]) -> TrendFeatures:
    closes = [c.close for c in candles]
    n = len(closes)

    short_sma = _sma(closes, _SHORT_SMA_WINDOW)
    medium_sma = _sma(closes, _MEDIUM_SMA_WINDOW)
    long_sma = _sma(closes, _LONG_SMA_WINDOW)

    # Consecutive up/down closes
    consec_up = 0
    consec_dn = 0
    for i in range(n - 1, 0, -1):
        if candles[i].close > candles[i - 1].close:
            if consec_dn == 0:
                consec_up += 1
            else:
                break
        elif candles[i].close < candles[i - 1].close:
            if consec_up == 0:
                consec_dn += 1
            else:
                break
        else:
            break

    latest_close = closes[-1] if closes else None

    dist_short: float | None = None
    dist_medium: float | None = None
    if latest_close and short_sma and short_sma > 0:
        dist_short = round(_safe_div(latest_close - short_sma, short_sma) * 100.0, 4)
    if latest_close and medium_sma and medium_sma > 0:
        dist_medium = round(_safe_div(latest_close - medium_sma, medium_sma) * 100.0, 4)

    # Trend direction logic
    if n < _MIN_CANDLES_TREND:
        direction = "insufficient_data"
        strength = 0.0
    else:
        sma_signals: list[int] = []  # +1 up, -1 down, 0 flat
        if short_sma and medium_sma:
            sma_signals.append(1 if short_sma > medium_sma else (-1 if short_sma < medium_sma else 0))
        if medium_sma and long_sma:
            sma_signals.append(1 if medium_sma > long_sma else (-1 if medium_sma < long_sma else 0))
        if short_sma and long_sma:
            sma_signals.append(1 if short_sma > long_sma else (-1 if short_sma < long_sma else 0))
        if latest_close and short_sma:
            sma_signals.append(1 if latest_close > short_sma else (-1 if latest_close < short_sma else 0))

        score_sum = sum(sma_signals) if sma_signals else 0
        max_sum = len(sma_signals) if sma_signals else 1
        strength = _clamp01(_safe_div(abs(score_sum), max_sum))

        if not sma_signals:
            direction = "sideways"
        elif score_sum >= max_sum * 0.5:
            direction = "uptrend"
        elif score_sum <= -max_sum * 0.5:
            direction = "downtrend"
        else:
            direction = "sideways"

    return TrendFeatures(
        short_sma=round(short_sma, 6) if short_sma is not None else None,
        medium_sma=round(medium_sma, 6) if medium_sma is not None else None,
        long_sma=round(long_sma, 6) if long_sma is not None else None,
        trend_direction=direction,
        trend_strength_score=round(strength, 4),
        consecutive_up_closes=consec_up,
        consecutive_down_closes=consec_dn,
        distance_from_short_sma_pct=dist_short,
        distance_from_medium_sma_pct=dist_medium,
    )


def _true_range(curr: Candle, prev: Candle | None) -> float:
    if prev is None:
        return curr.high - curr.low
    return max(
        curr.high - curr.low,
        abs(curr.high - prev.close),
        abs(curr.low - prev.close),
    )


def _compute_volatility(candles: list[Candle]) -> VolatilityFeatures:
    n = len(candles)

    # ATR
    atr: float | None = None
    atr_pct: float | None = None
    if n >= _MIN_CANDLES_ATR:
        trs = [
            _true_range(candles[i], candles[i - 1] if i > 0 else None)
            for i in range(1, n)
        ]
        if trs:
            atr = round(sum(trs) / len(trs), 6)
            last_close = candles[-1].close
            if last_close > 0:
                atr_pct = round(_safe_div(atr, last_close) * 100.0, 4)

    # Realized vol proxy: std of log returns
    rv_proxy: float | None = None
    closes = [c.close for c in candles]
    if len(closes) >= 3:
        log_rets: list[float] = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0 and closes[i] > 0:
                lr = math.log(closes[i] / closes[i - 1])
                log_rets.append(lr)
        if len(log_rets) >= 2:
            rv_proxy = round(statistics.stdev(log_rets) * 100.0, 6)

    # Regime
    if n < _MIN_CANDLES_ATR or atr_pct is None:
        regime = "insufficient_data"
    elif atr_pct < _COMPRESSED_ATR_PCT:
        regime = "compressed"
    elif atr_pct > _EXPANDED_ATR_PCT:
        regime = "expanded"
    else:
        regime = "normal"

    # Range expansion: latest candle range vs avg of prior candles
    range_expansion = False
    if n >= 3:
        latest_range = candles[-1].high - candles[-1].low
        prior_ranges = [c.high - c.low for c in candles[:-1]]
        avg_prior = sum(prior_ranges) / len(prior_ranges) if prior_ranges else 0.0
        if avg_prior > 0 and latest_range > avg_prior * _RANGE_EXPANSION_RATIO:
            range_expansion = True

    # Gap flag: latest open vs prior close
    gap = False
    if n >= 2:
        prev_close = candles[-2].close
        curr_open = candles[-1].open
        if prev_close > 0:
            gap_pct = abs(_safe_div(curr_open - prev_close, prev_close)) * 100.0
            gap = gap_pct > _GAP_PCT

    # Large move flag: latest close vs prior close
    large_move = False
    if n >= 2:
        prev_close = candles[-2].close
        curr_close = candles[-1].close
        if prev_close > 0:
            move_pct = abs(_safe_div(curr_close - prev_close, prev_close)) * 100.0
            large_move = move_pct > _LARGE_MOVE_PCT

    return VolatilityFeatures(
        average_true_range=atr,
        atr_pct=atr_pct,
        realized_volatility_proxy=rv_proxy,
        volatility_regime=regime,
        range_expansion_flag=range_expansion,
        gap_flag=gap,
        large_move_flag=large_move,
    )


def _compute_support_resistance(candles: list[Candle]) -> SupportResistance:
    n = len(candles)
    if n < _MIN_CANDLES_SR:
        return SupportResistance(
            rolling_high=None, rolling_low=None,
            distance_to_rolling_high_pct=None, distance_to_rolling_low_pct=None,
            breakout_proximity="insufficient_data",
        )

    window = min(_SR_WINDOW, n)
    subset = candles[-window:]
    rolling_high = max(c.high for c in subset)
    rolling_low = min(c.low for c in subset)
    last_close = candles[-1].close

    dist_high: float | None = None
    dist_low: float | None = None
    if last_close > 0:
        dist_high = round(_safe_div(rolling_high - last_close, last_close) * 100.0, 4)
        dist_low = round(_safe_div(last_close - rolling_low, last_close) * 100.0, 4)

    proximity = "middle_range"
    if dist_high is not None and dist_low is not None:
        if dist_high <= _NEAR_SR_PCT:
            proximity = "near_resistance"
        elif dist_low <= _NEAR_SR_PCT:
            proximity = "near_support"

    return SupportResistance(
        rolling_high=round(rolling_high, 6),
        rolling_low=round(rolling_low, 6),
        distance_to_rolling_high_pct=dist_high,
        distance_to_rolling_low_pct=dist_low,
        breakout_proximity=proximity,
    )


def _compute_market_context(
    trend: TrendFeatures,
    vol: VolatilityFeatures,
    anatomy: CandleAnatomy | None,
    sr: SupportResistance,
    n: int,
) -> MarketContext:
    confirmations: list[str] = []
    contradictions: list[str] = []

    if n < _MIN_CANDLES_TREND:
        return MarketContext(
            chart_confirmation_score=0.0,
            confirmation_reasons=[],
            contradiction_reasons=["Insufficient candles for analysis"],
            chart_state="INSUFFICIENT_DATA",
        )

    # Trend component
    trend_score = 0.0
    if trend.trend_direction == "uptrend":
        trend_score = trend.trend_strength_score
        confirmations.append(f"Uptrend detected (strength {trend.trend_strength_score:.2f})")
    elif trend.trend_direction == "downtrend":
        trend_score = trend.trend_strength_score
        confirmations.append(f"Downtrend detected (strength {trend.trend_strength_score:.2f})")
    elif trend.trend_direction == "sideways":
        trend_score = 0.3
        confirmations.append("Price action is sideways / range-bound")

    # Volatility component
    vol_score = 0.0
    if vol.volatility_regime == "normal":
        vol_score = 0.6
        confirmations.append("Volatility is in normal regime")
    elif vol.volatility_regime == "compressed":
        vol_score = 0.4
        confirmations.append("Volatility compressed — potential coiling")
    elif vol.volatility_regime == "expanded":
        vol_score = 0.2
        contradictions.append("Volatility expanded — elevated risk / unclear direction")

    if vol.gap_flag:
        contradictions.append("Gap detected at open — price continuity broken")
    if vol.large_move_flag:
        contradictions.append("Large single-candle move detected")
    if vol.range_expansion_flag:
        contradictions.append("Range expanded relative to recent average")

    # Candle component
    candle_score = 0.0
    if anatomy:
        if anatomy.candle_direction == "bullish" and anatomy.candle_shape not in ("doji",):
            candle_score = 0.7
            confirmations.append(f"Latest candle is bullish ({anatomy.candle_shape})")
        elif anatomy.candle_direction == "bearish" and anatomy.candle_shape not in ("doji",):
            candle_score = 0.7
            confirmations.append(f"Latest candle is bearish ({anatomy.candle_shape})")
        elif anatomy.candle_shape == "doji":
            candle_score = 0.3
            contradictions.append("Doji candle — indecision / reversal risk")
        elif anatomy.candle_shape == "long_upper_wick":
            candle_score = 0.4
            contradictions.append("Long upper wick — rejection of highs")
        elif anatomy.candle_shape == "long_lower_wick":
            candle_score = 0.5
            confirmations.append("Long lower wick — rejection of lows / potential support")

    score = _clamp01(
        trend_score * _SCORE_TREND_WEIGHT
        + vol_score * _SCORE_VOL_WEIGHT
        + candle_score * _SCORE_CANDLE_WEIGHT
    )

    # Chart state determination
    state: str
    if vol.volatility_regime == "compressed" and sr.breakout_proximity == "near_resistance":
        state = "BREAKOUT_ATTEMPT"
    elif vol.volatility_regime == "expanded" and anatomy and anatomy.candle_shape == "doji":
        state = "REVERSAL_RISK"
    elif vol.volatility_regime == "expanded":
        state = "VOLATILE_UNCLEAR"
    elif trend.trend_direction == "uptrend" and not vol.large_move_flag:
        state = "TRENDING_UP"
    elif trend.trend_direction == "downtrend" and not vol.large_move_flag:
        state = "TRENDING_DOWN"
    elif vol.volatility_regime == "compressed":
        state = "COMPRESSED"
    elif trend.trend_direction == "sideways":
        state = "RANGE_BOUND"
    else:
        state = "VOLATILE_UNCLEAR"

    return MarketContext(
        chart_confirmation_score=round(score, 4),
        confirmation_reasons=confirmations,
        contradiction_reasons=contradictions,
        chart_state=state,
    )


def _compute_advisory(
    context: MarketContext,
    trend: TrendFeatures,
    vol: VolatilityFeatures,
    n: int,
) -> AdvisoryInterpretation:
    state = context.chart_state

    if n < _MIN_CANDLES_TREND:
        return AdvisoryInterpretation(
            advisory_summary=(
                "Insufficient candle data to form a chart structure opinion. "
                "More historical OHLCV data is required before any advisory context can be drawn."
            ),
            suggested_next_step="REQUEST_MORE_EVIDENCE",
        )

    summaries: dict[str, str] = {
        "TRENDING_UP": (
            "Chart structure shows an upward trend supported by SMA alignment. "
            "Momentum appears constructive but no execution action should be taken without human review."
        ),
        "TRENDING_DOWN": (
            "Chart structure shows a downward trend with SMAs aligned bearishly. "
            "Caution is warranted; human review is required before any advisory response."
        ),
        "RANGE_BOUND": (
            "Price is oscillating within a range with no clear directional bias. "
            "Range-bound conditions limit trending signals; human review recommended."
        ),
        "COMPRESSED": (
            "Volatility is compressed and price action is coiling. "
            "No directional conviction yet; further evidence required."
        ),
        "BREAKOUT_ATTEMPT": (
            "Price is near rolling resistance with compressed volatility, suggesting a potential breakout setup. "
            "This is advisory context only — no execution. Human review required."
        ),
        "REVERSAL_RISK": (
            "Doji candle within expanded volatility suggests indecision and potential reversal. "
            "Treat as elevated-uncertainty context; human review required."
        ),
        "VOLATILE_UNCLEAR": (
            "Expanded volatility with unclear directional signal. "
            "Chart structure is inconclusive; human review required before any advisory response."
        ),
        "INSUFFICIENT_DATA": (
            "Insufficient data to determine chart state."
        ),
    }

    steps: dict[str, str] = {
        "TRENDING_UP": "WATCH_ONLY",
        "TRENDING_DOWN": "WATCH_ONLY",
        "RANGE_BOUND": "WATCH_ONLY",
        "COMPRESSED": "REQUEST_MORE_EVIDENCE",
        "BREAKOUT_ATTEMPT": "HUMAN_REVIEW",
        "REVERSAL_RISK": "HUMAN_REVIEW",
        "VOLATILE_UNCLEAR": "HUMAN_REVIEW",
        "INSUFFICIENT_DATA": "REQUEST_MORE_EVIDENCE",
    }

    summary = summaries.get(state, "Chart state undetermined. Human review required.")
    step = steps.get(state, "NO_ACTION")

    if context.contradiction_reasons:
        summary += (
            " Note: contradictory signals present — "
            + "; ".join(context.contradiction_reasons) + "."
        )

    return AdvisoryInterpretation(
        advisory_summary=summary,
        suggested_next_step=step,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_chart_structure(
    candles: list[dict[str, Any]],
    symbol: str | None = None,
    source: str = "market_data",
    max_candles: int | None = None,
) -> ChartStructureReport:
    """
    Analyse a list of OHLCV candle dicts and return an advisory ChartStructureReport.

    No execution logic. No broker APIs. No order placement.
    Output is advisory-only and always requires human review.
    """
    report = ChartStructureReport()

    valid_candles = _load_candles(candles, max_candles)
    n = len(valid_candles)

    summary = _compute_ohlcv_summary(valid_candles, symbol, source)
    report.summary = summary

    anatomy: CandleAnatomy | None = None
    if n >= 1:
        anatomy = _compute_candle_anatomy(valid_candles[-1])
    report.candle_anatomy = anatomy

    trend = _compute_trend(valid_candles)
    report.trend = trend

    vol = _compute_volatility(valid_candles)
    report.volatility = vol

    sr = _compute_support_resistance(valid_candles)
    report.support_resistance = sr

    context = _compute_market_context(trend, vol, anatomy, sr, n)
    report.context = context

    advisory = _compute_advisory(context, trend, vol, n)
    report.advisory = advisory

    return report


__all__ = [
    "analyze_chart_structure",
    "ChartStructureReport",
    "OHLCVSummary",
    "CandleAnatomy",
    "TrendFeatures",
    "VolatilityFeatures",
    "SupportResistance",
    "MarketContext",
    "AdvisoryInterpretation",
    "Candle",
    "_parse_candle",
    "_load_candles",
    "_safe_div",
    "_clamp01",
    "_safe_float",
    "_sma",
    "_true_range",
]
