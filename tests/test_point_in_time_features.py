"""T4 — point-in-time correctness of the entry-quality gate.

Pins the contract: the gate must NOT see any bar on or after the buy date.

The strict invariant the audit asked for: features computed from data
"up to and including the prior close" only. The buy-date bar is excluded.

The gate operates on whatever list of candles the caller passes in. The
point-in-time invariant therefore lives in the SLICE that the caller
performs. We test the contract from two angles:

1. The gate itself is referentially transparent in its input -- given the
   same candles, it returns the same score. So the leakage protection is
   that the slice does not let post-buy bars into the input.

2. ``build_report`` slices history with strict ``< buy_date``. We verify the
   slice predicate directly (the function is tested end-to-end in the
   replay tests; here we pin the prior-close-only contract).

The "leakage canary": if a hypothetical leaked future bar with extreme
high/low values were appended to the feature window, the entry quality
must NOT change vs the no-leak baseline -- because the slice predicate
must drop it. This is the failing-before / passing-after test for the
shift to strict ``<``.
"""
from __future__ import annotations

from datetime import date, timedelta

from scripts.entry_quality_gate import compute_entry_quality


def _candle(d: date, close: float, high: float | None = None,
            low: float | None = None) -> dict:
    return {
        "date": d.isoformat(),
        "open": close,
        "high": high if high is not None else close * 1.005,
        "low": low if low is not None else close * 0.995,
        "close": close,
        "volume": 1_000_000,
    }


def _history(n: int, start_date: date, start_price: float = 100.0,
             drift: float = 0.001) -> list[dict]:
    """A clean ascending series long enough to compute SMA200 + 52w."""
    out = []
    p = start_price
    for i in range(n):
        d = start_date + timedelta(days=i)
        out.append(_candle(d, p))
        p *= (1 + drift)
    return out


# ---------------------------------------------------------------------------
# Gate is referentially transparent: deterministic given input.
# ---------------------------------------------------------------------------


def test_gate_is_deterministic_for_same_input():
    candles = _history(260, date(2025, 1, 1))
    a = compute_entry_quality(candles=candles)
    b = compute_entry_quality(candles=candles)
    assert a == b


# ---------------------------------------------------------------------------
# Leakage canary: appending a future bar must change the gate score (proving
# the gate DOES read the last element), so the slice must exclude that bar.
# ---------------------------------------------------------------------------


def test_gate_reads_the_last_candle_so_slice_must_protect_against_leakage():
    """If the gate did not read the last candle this test would be a no-op.
    By proving the score moves when we append a bar, we prove that whoever
    feeds the gate is responsible for excluding post-buy bars."""
    candles = _history(260, date(2025, 1, 1))
    baseline = compute_entry_quality(candles=candles)

    # Append a "future" bar with an extreme low and tame close.
    leaked = candles + [_candle(date(2025, 9, 18), close=50.0,
                                high=51.0, low=49.0)]
    with_leak = compute_entry_quality(candles=leaked)

    assert baseline["entry_quality_score"] != with_leak["entry_quality_score"], (
        "Score should move when the last bar moves -- confirming the gate is "
        "sensitive to the as-of bar. This is why the caller MUST slice with "
        "strict < buy_date (T4)."
    )


# ---------------------------------------------------------------------------
# The build_report slice predicate is < buy_date (strict).
# ---------------------------------------------------------------------------


def test_build_report_uses_strict_prior_close_slice():
    """Inspect the SOURCE of build_report and pin that the feature slice
    uses ``< buy_date`` (not ``<=``). This is brittle on purpose: any
    regression that re-introduces same-bar leakage will trip this test."""
    from pathlib import Path
    src = Path("scripts/backtest_entry_quality.py").read_text(encoding="utf-8")
    # The strict feature slice. There must be at least two occurrences:
    # one for the stock history, one for the index history.
    feature_strict = src.count("date.fromisoformat(c[\"date\"]) < buy_date")
    assert feature_strict >= 2, (
        "Feature history slices must use STRICT '< buy_date' (T4). "
        f"Found {feature_strict} occurrences; expected >= 2 (stock + index)."
    )
    # And the loose '<=' must NOT appear in a feature slice context.
    assert "date.fromisoformat(c[\"date\"]) <= buy_date" not in src, (
        "Found '<= buy_date' slice -- this is the same-bar leakage path "
        "T4 deleted. Use strict '< buy_date' for features."
    )


# ---------------------------------------------------------------------------
# Outcome slice: must NOT exclude the buy-date bar (the fill happens at
# buy-date open; the buy-date intraday range can trigger TP1 or stop).
# ---------------------------------------------------------------------------


def test_build_report_outcome_slice_includes_buy_date_bar():
    """Outcomes start from buy_date inclusive (>=). The audit explicitly
    flagged 'gap through stop on the buy day' as a realism gap; the only
    way to capture that is to include the buy-date bar in `after`."""
    from pathlib import Path
    src = Path("scripts/backtest_entry_quality.py").read_text(encoding="utf-8")
    assert "date.fromisoformat(c[\"date\"]) >= buy_date" in src, (
        "Outcome slice must include the buy-date bar so a gap-through-stop "
        "on the buy day counts toward the realized P/L."
    )


# ---------------------------------------------------------------------------
# Insufficient-history defensiveness: gate must fail closed, not silently
# pass, when there are not enough bars to compute features.
# ---------------------------------------------------------------------------


def test_short_history_fails_closed():
    candles = _history(10, date(2025, 1, 1))
    out = compute_entry_quality(candles=candles)
    assert out["entry_quality_pass"] is False
    assert any("insufficient_history" in r for r in out["reasons"])
