"""
Phase D.1/D.2 — Chart Structure Engine Tests.

Covers all 33 test requirements:
 1  Empty candles
 2  Single candle
 3  Valid bullish candle
 4  Valid bearish candle
 5  Doji detection
 6  Long upper wick detection
 7  Long lower wick detection
 8  Marubozu-like detection
 9  Uptrend detection
10  Downtrend detection
11  Sideways detection
12  Volatility compressed
13  Volatility expanded
14  Gap flag
15  Large move flag
16  Range expansion flag
17  Support/resistance proximity
18  Breakout attempt state
19  Reversal risk state
20  Volatile unclear state
21  Invalid candles skipped / flagged safely
22  Non-numeric values handled safely
23  Missing fields handled safely
24  Negative prices rejected safely
25  Unordered candles sorted safely
26  max_candles respected
27  to_dict serializable
28  Safety invariants always present
29  No forbidden execution words in suggested_next_step
30  AST scan: no forbidden broker/order methods in chart_structure_engine.py
31  chart_confirmation_score always between 0 and 1
32  No live internet dependency
33  No backend or frontend changes in this phase

No live network calls are made in any test.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Repo root on sys.path
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.chart_structure_engine import (
    ChartStructureReport,
    _clamp01,
    _load_candles,
    _parse_candle,
    _safe_div,
    _safe_float,
    _sma,
    _true_range,
    analyze_chart_structure,
)

# ---------------------------------------------------------------------------
# Candle fixture helpers
# ---------------------------------------------------------------------------

def _candle(
    ts: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _bullish_candles(n: int = 25, base: float = 100.0, step: float = 1.0) -> list[dict]:
    """Steadily rising candles — good for uptrend tests."""
    candles = []
    for i in range(n):
        o = base + i * step
        c = o + step * 0.8
        h = c + step * 0.1
        lo = o - step * 0.05
        candles.append(_candle(f"2024-01-{i+1:02d}", o, h, lo, c))
    return candles


def _bearish_candles(n: int = 25, base: float = 200.0, step: float = 1.0) -> list[dict]:
    """Steadily falling candles — good for downtrend tests."""
    candles = []
    for i in range(n):
        o = base - i * step
        c = o - step * 0.8
        lo = c - step * 0.1
        h = o + step * 0.05
        candles.append(_candle(f"2024-01-{i+1:02d}", o, h, lo, c))
    return candles


def _flat_candles(n: int = 25, price: float = 100.0) -> list[dict]:
    """Flat, narrow-range candles — sideways / compressed."""
    candles = []
    for i in range(n):
        o = price + (0.05 if i % 2 == 0 else -0.05)
        c = price - (0.05 if i % 2 == 0 else -0.05)
        h = price + 0.1
        lo = price - 0.1
        candles.append(_candle(f"2024-01-{i+1:02d}", o, h, lo, c))
    return candles


# ===========================================================================
# 1. Empty candles
# ===========================================================================

class TestEmptyCandles:
    def test_returns_report(self):
        r = analyze_chart_structure([])
        assert isinstance(r, ChartStructureReport)

    def test_candle_count_zero(self):
        r = analyze_chart_structure([])
        assert r.summary.candle_count == 0

    def test_no_anatomy(self):
        r = analyze_chart_structure([])
        assert r.candle_anatomy is None

    def test_chart_state_insufficient(self):
        r = analyze_chart_structure([])
        assert r.context.chart_state == "INSUFFICIENT_DATA"

    def test_suggested_step_not_execution(self):
        r = analyze_chart_structure([])
        assert r.advisory.suggested_next_step in (
            "WATCH_ONLY", "REQUEST_MORE_EVIDENCE", "HUMAN_REVIEW", "NO_ACTION"
        )


# ===========================================================================
# 2. Single candle
# ===========================================================================

class TestSingleCandle:
    def test_single_candle_parses(self):
        r = analyze_chart_structure([_candle("2024-01-01", 100, 105, 98, 103)])
        assert r.summary.candle_count == 1

    def test_anatomy_present(self):
        r = analyze_chart_structure([_candle("2024-01-01", 100, 105, 98, 103)])
        assert r.candle_anatomy is not None

    def test_no_price_change(self):
        r = analyze_chart_structure([_candle("2024-01-01", 100, 105, 98, 103)])
        assert r.summary.price_change_abs is None

    def test_trend_insufficient(self):
        r = analyze_chart_structure([_candle("2024-01-01", 100, 105, 98, 103)])
        assert r.trend.trend_direction == "insufficient_data"


# ===========================================================================
# 3. Valid bullish candle
# ===========================================================================

class TestBullishCandle:
    def test_direction_bullish(self):
        r = analyze_chart_structure([_candle("2024-01-01", 100, 110, 98, 108)])
        assert r.candle_anatomy.candle_direction == "bullish"

    def test_price_change_positive(self):
        c = [
            _candle("2024-01-01", 100, 102, 99, 101),
            _candle("2024-01-02", 101, 112, 100, 110),
        ]
        r = analyze_chart_structure(c)
        assert r.summary.price_change_abs > 0
        assert r.summary.price_change_pct > 0


# ===========================================================================
# 4. Valid bearish candle
# ===========================================================================

class TestBearishCandle:
    def test_direction_bearish(self):
        r = analyze_chart_structure([_candle("2024-01-01", 110, 112, 98, 100)])
        assert r.candle_anatomy.candle_direction == "bearish"

    def test_price_change_negative(self):
        c = [
            _candle("2024-01-01", 110, 112, 108, 109),
            _candle("2024-01-02", 109, 110, 95, 97),
        ]
        r = analyze_chart_structure(c)
        assert r.summary.price_change_abs < 0


# ===========================================================================
# 5. Doji detection
# ===========================================================================

class TestDojiDetection:
    def test_doji_shape(self):
        # open == close → pure doji
        r = analyze_chart_structure([_candle("2024-01-01", 100, 105, 95, 100)])
        assert r.candle_anatomy.candle_shape == "doji"

    def test_near_doji_tiny_body(self):
        # body = 0.1 out of range 10 → 1 % < 5 % threshold
        r = analyze_chart_structure([_candle("2024-01-01", 100.0, 105.0, 95.0, 100.1)])
        assert r.candle_anatomy.candle_shape == "doji"


# ===========================================================================
# 6. Long upper wick detection
# ===========================================================================

class TestLongUpperWick:
    def test_long_upper_wick_shape(self):
        # open=100 close=101 high=110 low=99 → upper wick=9, range=11, upper_wick_pct≈82%
        r = analyze_chart_structure([_candle("2024-01-01", 100, 110, 99, 101)])
        assert r.candle_anatomy.candle_shape == "long_upper_wick"

    def test_upper_wick_pct_high(self):
        r = analyze_chart_structure([_candle("2024-01-01", 100, 110, 99, 101)])
        assert r.candle_anatomy.upper_wick_pct >= 0.40


# ===========================================================================
# 7. Long lower wick detection
# ===========================================================================

class TestLongLowerWick:
    def test_long_lower_wick_shape(self):
        # open=101 close=100 high=102 low=90 → lower wick=10, range=12
        r = analyze_chart_structure([_candle("2024-01-01", 101, 102, 90, 100)])
        assert r.candle_anatomy.candle_shape == "long_lower_wick"

    def test_lower_wick_pct_high(self):
        r = analyze_chart_structure([_candle("2024-01-01", 101, 102, 90, 100)])
        assert r.candle_anatomy.lower_wick_pct >= 0.40


# ===========================================================================
# 8. Marubozu-like detection
# ===========================================================================

class TestMarubozuLike:
    def test_marubozu_bullish(self):
        # open=100 close=110 high=110.1 low=99.9 → body=10, range=10.2 → body_pct≈98%
        r = analyze_chart_structure([_candle("2024-01-01", 100, 110.1, 99.9, 110)])
        assert r.candle_anatomy.candle_shape == "marubozu_like"

    def test_marubozu_body_pct(self):
        r = analyze_chart_structure([_candle("2024-01-01", 100, 110.1, 99.9, 110)])
        assert r.candle_anatomy.body_pct_of_range >= 0.85


# ===========================================================================
# 9. Uptrend detection
# ===========================================================================

class TestUptrend:
    def test_uptrend_direction(self):
        r = analyze_chart_structure(_bullish_candles(25))
        assert r.trend.trend_direction == "uptrend"

    def test_uptrend_strength_positive(self):
        r = analyze_chart_structure(_bullish_candles(25))
        assert r.trend.trend_strength_score > 0

    def test_chart_state_trending_up(self):
        r = analyze_chart_structure(_bullish_candles(25))
        assert r.context.chart_state == "TRENDING_UP"


# ===========================================================================
# 10. Downtrend detection
# ===========================================================================

class TestDowntrend:
    def test_downtrend_direction(self):
        r = analyze_chart_structure(_bearish_candles(25))
        assert r.trend.trend_direction == "downtrend"

    def test_chart_state_trending_down(self):
        r = analyze_chart_structure(_bearish_candles(25))
        assert r.context.chart_state == "TRENDING_DOWN"


# ===========================================================================
# 11. Sideways detection
# ===========================================================================

class TestSideways:
    def test_sideways_direction(self):
        # Constant close price ensures all SMAs are equal → sideways
        candles = [_candle(f"2024-01-{i+1:02d}", 100.0, 101.0, 99.0, 100.0) for i in range(25)]
        r = analyze_chart_structure(candles)
        assert r.trend.trend_direction == "sideways"


# ===========================================================================
# 12. Volatility compressed
# ===========================================================================

class TestVolatilityCompressed:
    def test_compressed_regime(self):
        r = analyze_chart_structure(_flat_candles(25))
        assert r.volatility.volatility_regime == "compressed"


# ===========================================================================
# 13. Volatility expanded
# ===========================================================================

class TestVolatilityExpanded:
    def test_expanded_regime(self):
        candles = []
        # Alternating large swings
        for i in range(20):
            direction = 1 if i % 2 == 0 else -1
            o = 100.0 + direction * 5
            c = 100.0 - direction * 5
            h = max(o, c) + 3.0
            lo = min(o, c) - 3.0
            candles.append(_candle(f"2024-01-{i+1:02d}", o, h, lo, c))
        r = analyze_chart_structure(candles)
        assert r.volatility.volatility_regime == "expanded"


# ===========================================================================
# 14. Gap flag
# ===========================================================================

class TestGapFlag:
    def test_gap_detected(self):
        # prev close = 100, next open = 102 → gap > 0.5 %
        c = [
            _candle("2024-01-01", 100, 101, 99, 100),
            _candle("2024-01-02", 102, 103, 101.5, 102.5),
        ]
        r = analyze_chart_structure(c)
        assert r.volatility.gap_flag is True

    def test_no_gap_when_close(self):
        c = [
            _candle("2024-01-01", 100, 101, 99, 100),
            _candle("2024-01-02", 100.1, 101, 99.5, 100.5),
        ]
        r = analyze_chart_structure(c)
        assert r.volatility.gap_flag is False


# ===========================================================================
# 15. Large move flag
# ===========================================================================

class TestLargeMoveFlag:
    def test_large_move_detected(self):
        c = [
            _candle("2024-01-01", 100, 101, 99, 100),
            _candle("2024-01-02", 100, 105, 99, 103),   # +3 % close
        ]
        r = analyze_chart_structure(c)
        assert r.volatility.large_move_flag is True

    def test_no_large_move_small_change(self):
        c = [
            _candle("2024-01-01", 100, 101, 99, 100),
            _candle("2024-01-02", 100, 101, 99, 100.5),  # +0.5 %
        ]
        r = analyze_chart_structure(c)
        assert r.volatility.large_move_flag is False


# ===========================================================================
# 16. Range expansion flag
# ===========================================================================

class TestRangeExpansionFlag:
    def test_range_expansion_detected(self):
        # Small ranges then one very wide candle
        candles = [_candle(f"2024-01-{i+1:02d}", 100, 101, 99, 100) for i in range(9)]
        candles.append(_candle("2024-01-10", 100, 120, 80, 100))  # range=40 vs avg≈2
        r = analyze_chart_structure(candles)
        assert r.volatility.range_expansion_flag is True

    def test_no_expansion_uniform_ranges(self):
        candles = [_candle(f"2024-01-{i+1:02d}", 100, 102, 98, 100) for i in range(10)]
        r = analyze_chart_structure(candles)
        assert r.volatility.range_expansion_flag is False


# ===========================================================================
# 17. Support/resistance proximity
# ===========================================================================

class TestSupportResistanceProximity:
    def test_near_resistance(self):
        # Price at the rolling high
        candles = [_candle(f"2024-01-{i+1:02d}", 100, 105, 95, 100) for i in range(9)]
        candles.append(_candle("2024-01-10", 104.5, 105.1, 104, 105))  # near the 105 high
        r = analyze_chart_structure(candles)
        assert r.support_resistance.breakout_proximity == "near_resistance"

    def test_near_support(self):
        # Price at the rolling low
        candles = [_candle(f"2024-01-{i+1:02d}", 100, 105, 95, 100) for i in range(9)]
        candles.append(_candle("2024-01-10", 95.5, 96, 94.9, 95.2))  # near the 95 low
        r = analyze_chart_structure(candles)
        assert r.support_resistance.breakout_proximity == "near_support"

    def test_middle_range(self):
        candles = [_candle(f"2024-01-{i+1:02d}", 100, 110, 90, 100) for i in range(10)]
        r = analyze_chart_structure(candles)
        assert r.support_resistance.breakout_proximity == "middle_range"

    def test_insufficient_data_sr(self):
        candles = [_candle("2024-01-01", 100, 105, 95, 100)]
        r = analyze_chart_structure(candles)
        assert r.support_resistance.breakout_proximity == "insufficient_data"


# ===========================================================================
# 18. Breakout attempt state
# ===========================================================================

class TestBreakoutAttemptState:
    def test_breakout_attempt(self):
        # Compressed volatility + near resistance → BREAKOUT_ATTEMPT
        candles = []
        for i in range(19):
            candles.append(_candle(f"2024-01-{i+1:02d}", 100, 100.1, 99.9, 100))
        # Last candle near the 100.1 high (within 1%)
        candles.append(_candle("2024-01-20", 100.05, 100.15, 100.0, 100.08))
        r = analyze_chart_structure(candles)
        assert r.context.chart_state == "BREAKOUT_ATTEMPT"


# ===========================================================================
# 19. Reversal risk state
# ===========================================================================

class TestReversalRiskState:
    def test_reversal_risk(self):
        # Expanded volatility + doji on last candle
        candles = []
        for i in range(19):
            direction = 1 if i % 2 == 0 else -1
            o = 100.0 + direction * 6
            c = 100.0 - direction * 6
            h = max(o, c) + 3
            lo = min(o, c) - 3
            candles.append(_candle(f"2024-01-{i+1:02d}", o, h, lo, c))
        # Pure doji last
        candles.append(_candle("2024-01-20", 100, 105, 95, 100))
        r = analyze_chart_structure(candles)
        assert r.context.chart_state == "REVERSAL_RISK"


# ===========================================================================
# 20. Volatile unclear state
# ===========================================================================

class TestVolatileUnclearState:
    def test_volatile_unclear(self):
        # Expanded vol + large move (non-doji last)
        candles = []
        for i in range(19):
            direction = 1 if i % 2 == 0 else -1
            o = 100.0 + direction * 6
            c = 100.0 - direction * 6
            h = max(o, c) + 3
            lo = min(o, c) - 3
            candles.append(_candle(f"2024-01-{i+1:02d}", o, h, lo, c))
        # Big bullish candle at end (not a doji)
        candles.append(_candle("2024-01-20", 90, 115, 89, 113))
        r = analyze_chart_structure(candles)
        assert r.context.chart_state == "VOLATILE_UNCLEAR"


# ===========================================================================
# 21. Invalid candles skipped or flagged safely
# ===========================================================================

class TestInvalidCandlesSkipped:
    def test_high_lt_low_skipped(self):
        bad = {"timestamp": "2024-01-01", "open": 100, "high": 90, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_high_lt_close_skipped(self):
        bad = {"timestamp": "2024-01-01", "open": 100, "high": 95, "low": 90, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_low_gt_open_skipped(self):
        bad = {"timestamp": "2024-01-01", "open": 90, "high": 100, "low": 95, "close": 98, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_valid_mixed_with_invalid(self):
        good = _candle("2024-01-01", 100, 105, 95, 102)
        bad = {"timestamp": "2024-01-02", "open": 100, "high": 80, "low": 90, "close": 95, "volume": 1000}
        r = analyze_chart_structure([good, bad])
        assert r.summary.candle_count == 1


# ===========================================================================
# 22. Non-numeric values handled safely
# ===========================================================================

class TestNonNumericValues:
    def test_string_price_skipped(self):
        bad = {"timestamp": "2024-01-01", "open": "abc", "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_none_price_skipped(self):
        bad = {"timestamp": "2024-01-01", "open": None, "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_nan_price_skipped(self):
        import math
        bad = {"timestamp": "2024-01-01", "open": float("nan"), "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_inf_price_skipped(self):
        bad = {"timestamp": "2024-01-01", "open": float("inf"), "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0


# ===========================================================================
# 23. Missing fields handled safely
# ===========================================================================

class TestMissingFields:
    def test_missing_open(self):
        bad = {"timestamp": "2024-01-01", "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_missing_volume(self):
        bad = {"timestamp": "2024-01-01", "open": 100, "high": 105, "low": 95, "close": 100}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_missing_timestamp(self):
        bad = {"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_empty_timestamp(self):
        bad = {"timestamp": "", "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0


# ===========================================================================
# 24. Negative prices rejected safely
# ===========================================================================

class TestNegativePrices:
    def test_negative_close_rejected(self):
        bad = {"timestamp": "2024-01-01", "open": 100, "high": 105, "low": 95, "close": -1, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_negative_open_rejected(self):
        bad = {"timestamp": "2024-01-01", "open": -5, "high": 105, "low": 95, "close": 100, "volume": 1000}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_negative_volume_rejected(self):
        bad = {"timestamp": "2024-01-01", "open": 100, "high": 105, "low": 95, "close": 100, "volume": -500}
        r = analyze_chart_structure([bad])
        assert r.summary.candle_count == 0

    def test_zero_volume_accepted(self):
        # Zero volume is valid (halted trading)
        good = {"timestamp": "2024-01-01", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 0}
        r = analyze_chart_structure([good])
        assert r.summary.candle_count == 1


# ===========================================================================
# 25. Unordered candles sorted safely
# ===========================================================================

class TestUnorderedCandles:
    def test_sorted_by_timestamp(self):
        candles = [
            _candle("2024-01-05", 100, 105, 95, 103),
            _candle("2024-01-01", 90, 95, 88, 92),
            _candle("2024-01-03", 95, 100, 93, 98),
        ]
        r = analyze_chart_structure(candles)
        assert r.summary.first_timestamp == "2024-01-01"
        assert r.summary.latest_timestamp == "2024-01-05"

    def test_latest_close_from_latest_timestamp(self):
        candles = [
            _candle("2024-01-05", 100, 110, 99, 109),
            _candle("2024-01-01", 90, 95, 88, 92),
        ]
        r = analyze_chart_structure(candles)
        assert r.summary.latest_close == 109.0


# ===========================================================================
# 26. max_candles respected
# ===========================================================================

class TestMaxCandles:
    def test_max_candles_caps_count(self):
        candles = _bullish_candles(25)
        r = analyze_chart_structure(candles, max_candles=10)
        assert r.summary.candle_count == 10

    def test_max_candles_takes_latest(self):
        candles = _bullish_candles(25)
        all_r = analyze_chart_structure(candles)
        cap_r = analyze_chart_structure(candles, max_candles=10)
        # Latest close must be the same (last candle)
        assert cap_r.summary.latest_close == all_r.summary.latest_close

    def test_max_candles_zero_ignored(self):
        candles = _bullish_candles(10)
        r = analyze_chart_structure(candles, max_candles=0)
        # max_candles=0 means no-op (use all)
        assert r.summary.candle_count == 10

    def test_max_candles_none_uses_all(self):
        candles = _bullish_candles(20)
        r = analyze_chart_structure(candles, max_candles=None)
        assert r.summary.candle_count == 20


# ===========================================================================
# 27. to_dict serializable
# ===========================================================================

class TestToDictSerializable:
    def test_to_dict_returns_dict(self):
        r = analyze_chart_structure(_bullish_candles(10))
        d = r.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_safety_keys(self):
        d = analyze_chart_structure(_bullish_candles(10)).to_dict()
        for key in ("advisory_status", "execution_gate", "human_review_required",
                    "ai_execution_count", "broker_api_called", "broker_order_id"):
            assert key in d

    def test_to_dict_json_serializable(self):
        import json
        d = analyze_chart_structure(_bullish_candles(15)).to_dict()
        # Should not raise
        json.dumps(d)

    def test_to_dict_empty_candles(self):
        import json
        d = analyze_chart_structure([]).to_dict()
        json.dumps(d)

    def test_to_dict_nested_structure(self):
        d = analyze_chart_structure(_bullish_candles(10)).to_dict()
        assert "summary" in d
        assert "candle_anatomy" in d
        assert "trend" in d
        assert "volatility" in d
        assert "support_resistance" in d
        assert "context" in d
        assert "advisory" in d


# ===========================================================================
# 28. Safety invariants always present
# ===========================================================================

class TestSafetyInvariants:
    def _check_invariants(self, r: ChartStructureReport):
        assert r.advisory_status == "ADVISORY_ONLY"
        assert r.execution_gate == "LOCKED"
        assert r.human_review_required is True
        assert r.ai_execution_count == 0
        assert r.broker_api_called is False
        assert r.broker_order_id == "NONE"

    def test_invariants_empty(self):
        self._check_invariants(analyze_chart_structure([]))

    def test_invariants_single_candle(self):
        self._check_invariants(analyze_chart_structure([_candle("2024-01-01", 100, 105, 95, 102)]))

    def test_invariants_bullish_trend(self):
        self._check_invariants(analyze_chart_structure(_bullish_candles(25)))

    def test_invariants_bearish_trend(self):
        self._check_invariants(analyze_chart_structure(_bearish_candles(25)))

    def test_invariants_invalid_candles(self):
        bad = [{"timestamp": "x", "open": "bad", "high": "bad", "low": "bad", "close": "bad", "volume": "bad"}]
        self._check_invariants(analyze_chart_structure(bad))

    def test_invariants_in_to_dict(self):
        d = analyze_chart_structure(_bullish_candles(10)).to_dict()
        assert d["advisory_status"] == "ADVISORY_ONLY"
        assert d["execution_gate"] == "LOCKED"
        assert d["human_review_required"] is True
        assert d["ai_execution_count"] == 0
        assert d["broker_api_called"] is False
        assert d["broker_order_id"] == "NONE"


# ===========================================================================
# 29. No forbidden execution words in suggested_next_step
# ===========================================================================

class TestNoForbiddenExecutionWords:
    _FORBIDDEN = {"BUY", "SELL", "EXECUTE", "TRADE_NOW", "AUTO_TRADE", "PLACE_ORDER"}

    def _assert_clean(self, step: str):
        assert step not in self._FORBIDDEN, f"Forbidden step: {step!r}"
        for w in self._FORBIDDEN:
            assert w not in step.upper(), f"Forbidden word {w!r} in step {step!r}"

    def test_empty_candles_step(self):
        self._assert_clean(analyze_chart_structure([]).advisory.suggested_next_step)

    def test_bullish_step(self):
        self._assert_clean(analyze_chart_structure(_bullish_candles(25)).advisory.suggested_next_step)

    def test_bearish_step(self):
        self._assert_clean(analyze_chart_structure(_bearish_candles(25)).advisory.suggested_next_step)

    def test_single_candle_step(self):
        self._assert_clean(analyze_chart_structure([_candle("2024-01-01", 100, 105, 95, 102)]).advisory.suggested_next_step)

    def test_all_valid_steps_are_allowed(self):
        valid = {"WATCH_ONLY", "REQUEST_MORE_EVIDENCE", "HUMAN_REVIEW", "NO_ACTION"}
        for step in valid:
            assert step not in self._FORBIDDEN


# ===========================================================================
# 30. AST scan: no forbidden broker/order methods
# ===========================================================================

class TestASTStaticScan:
    _ENGINE_PATH = _REPO / "scripts" / "chart_structure_engine.py"
    _FORBIDDEN_NAMES = {
        "place_order", "submit_order", "execute_trade",
        "buy", "sell", "send_transaction", "sign_transaction",
        "broker_api", "create_order", "cancel_order",
    }

    def test_engine_file_exists(self):
        assert self._ENGINE_PATH.exists()

    def test_no_forbidden_function_defs(self):
        source = self._ENGINE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name.lower() not in self._FORBIDDEN_NAMES, (
                    f"Forbidden function definition found: {node.name}"
                )

    def test_no_forbidden_calls(self):
        source = self._ENGINE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name and name.lower() in self._FORBIDDEN_NAMES:
                    pytest.fail(f"Forbidden function call found: {name}")

    def test_no_import_broker_libs(self):
        source = self._ENGINE_PATH.read_text(encoding="utf-8")
        forbidden_imports = ["alpaca", "ib_insync", "ccxt", "web3", "eth_account"]
        for lib in forbidden_imports:
            assert lib not in source.lower(), f"Forbidden import found: {lib}"

    def test_no_private_key_patterns(self):
        source = self._ENGINE_PATH.read_text(encoding="utf-8")
        patterns = ["private_key", "PRIVATE_KEY", "secret_key", "SECRET_KEY"]
        for p in patterns:
            assert p not in source, f"Forbidden pattern found: {p}"


# ===========================================================================
# 31. chart_confirmation_score always between 0 and 1
# ===========================================================================

class TestConfirmationScoreBounded:
    def _check_score(self, r: ChartStructureReport):
        score = r.context.chart_confirmation_score
        assert 0.0 <= score <= 1.0, f"Score out of bounds: {score}"

    def test_empty(self):
        self._check_score(analyze_chart_structure([]))

    def test_single(self):
        self._check_score(analyze_chart_structure([_candle("2024-01-01", 100, 105, 95, 102)]))

    def test_bullish(self):
        self._check_score(analyze_chart_structure(_bullish_candles(25)))

    def test_bearish(self):
        self._check_score(analyze_chart_structure(_bearish_candles(25)))

    def test_flat(self):
        self._check_score(analyze_chart_structure(_flat_candles(25)))

    def test_extreme_volatility(self):
        candles = []
        for i in range(20):
            d = 1 if i % 2 == 0 else -1
            o = 100 + d * 10
            c = 100 - d * 10
            h = max(o, c) + 5
            lo = min(o, c) - 5
            candles.append(_candle(f"2024-01-{i+1:02d}", o, h, lo, c))
        self._check_score(analyze_chart_structure(candles))


# ===========================================================================
# 32. No live internet dependency
# ===========================================================================

class TestNoLiveInternet:
    def test_analyze_works_without_network(self, monkeypatch):
        import socket
        original_getaddrinfo = socket.getaddrinfo

        def no_network(*args, **kwargs):
            raise OSError("Network access is blocked in tests")

        monkeypatch.setattr(socket, "getaddrinfo", no_network)
        # Should work fine — no network calls in engine
        r = analyze_chart_structure(_bullish_candles(10))
        assert isinstance(r, ChartStructureReport)


# ===========================================================================
# 33. No backend or frontend changes in this phase
# ===========================================================================

class TestNoBackendFrontendChanges:
    def test_api_server_unchanged(self):
        api_path = _REPO / "scripts" / "api_server.py"
        if api_path.exists():
            source = api_path.read_text(encoding="utf-8")
            # chart_structure_engine must not be imported in api_server yet (that's D.3)
            assert "chart_structure_engine" not in source, (
                "api_server.py must not import chart_structure_engine until Phase D.3"
            )

    def test_frontend_unchanged(self):
        frontend = _REPO / "frontend" / "src"
        if frontend.exists():
            for f in frontend.rglob("*.tsx"):
                if "chart" in f.name.lower():
                    pytest.fail(f"Unexpected chart frontend file found (Phase D.4 not yet): {f}")


# ===========================================================================
# Helper function unit tests
# ===========================================================================

class TestHelpers:
    def test_safe_div_zero_denominator(self):
        assert _safe_div(10.0, 0.0) == 0.0

    def test_safe_div_normal(self):
        assert abs(_safe_div(10.0, 4.0) - 2.5) < 1e-9

    def test_safe_div_custom_default(self):
        assert _safe_div(1.0, 0.0, default=99.0) == 99.0

    def test_clamp01_low(self):
        assert _clamp01(-5.0) == 0.0

    def test_clamp01_high(self):
        assert _clamp01(5.0) == 1.0

    def test_clamp01_mid(self):
        assert _clamp01(0.5) == 0.5

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_string(self):
        assert _safe_float("bad") is None

    def test_safe_float_nan(self):
        assert _safe_float(float("nan")) is None

    def test_safe_float_valid(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_sma_insufficient(self):
        assert _sma([1.0, 2.0], 5) is None

    def test_sma_exact(self):
        assert _sma([1.0, 2.0, 3.0, 4.0, 5.0], 5) == pytest.approx(3.0)

    def test_true_range_no_prev(self):
        from scripts.chart_structure_engine import Candle
        c = Candle("2024-01-01", 100, 110, 90, 105, 1000)
        assert _true_range(c, None) == pytest.approx(20.0)

    def test_parse_candle_valid(self):
        raw = {"timestamp": "2024-01-01", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}
        c = _parse_candle(raw)
        assert c is not None
        assert c.close == 105.0

    def test_parse_candle_invalid_high_low(self):
        raw = {"timestamp": "2024-01-01", "open": 100, "high": 80, "low": 90, "close": 100, "volume": 1000}
        assert _parse_candle(raw) is None

    def test_load_candles_sorts(self):
        raws = [
            {"timestamp": "2024-01-05", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 100},
            {"timestamp": "2024-01-01", "open": 90, "high": 95, "low": 88, "close": 92, "volume": 100},
        ]
        candles = _load_candles(raws, None)
        assert candles[0].timestamp == "2024-01-01"
        assert candles[1].timestamp == "2024-01-05"

    def test_load_candles_max(self):
        raws = [
            {"timestamp": f"2024-01-{i+1:02d}", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 100}
            for i in range(10)
        ]
        candles = _load_candles(raws, 5)
        assert len(candles) == 5
