"""Timing-layer invariants for holding-period calculation.

Coordination audit — Layer 2 (Timing).  These tests pin the behaviour of
``paper_reconciliation._compute_holding_period_days`` so the audit can grade
``holding_period_calculation_integrity`` as PASS with a real proof behind it.

ALL inputs here are SYNTHETIC test fixtures (hand-written ISO timestamps).
They never touch the runtime DB, a broker, or any live/manual record — they
exercise a pure date-math helper.

Invariants proven:
  * same-day exit  -> 0.0 (a valid, zero-length holding window)
  * multi-day exit -> positive day count computed from real dates
  * missing exit   -> None (never silently treated as 0)
  * missing entry  -> None
  * invalid/swapped dates (exit before entry) -> None, NOT a negative number
"""
from __future__ import annotations

import importlib

pr = importlib.import_module("scripts.paper_reconciliation")

# SYNTHETIC fixture timestamps — provenance: hand-authored, not real outcomes.
_ENTRY = "2026-01-10T09:30:00+00:00"
_SAME_DAY_EXIT = "2026-01-10T15:30:00+00:00"  # +6h, same calendar day
_MULTI_DAY_EXIT = "2026-01-15T09:30:00+00:00"  # +5 days exactly
_BEFORE_ENTRY = "2026-01-05T09:30:00+00:00"  # exit precedes entry (invalid)


def test_same_day_exit_is_fractional_not_missing():
    """Same-day round-trip is a valid positive (or zero) window, not None."""
    days = pr._compute_holding_period_days(_ENTRY, _SAME_DAY_EXIT)
    assert days is not None
    assert days == 0.25  # 6 hours / 24


def test_multi_day_exit_counts_real_days():
    days = pr._compute_holding_period_days(_ENTRY, _MULTI_DAY_EXIT)
    assert days == 5.0


def test_missing_exit_returns_none_not_zero():
    assert pr._compute_holding_period_days(_ENTRY, None) is None
    assert pr._compute_holding_period_days(_ENTRY, "") is None


def test_missing_entry_returns_none():
    assert pr._compute_holding_period_days(None, _MULTI_DAY_EXIT) is None


def test_negative_holding_period_is_rejected():
    """Exit before entry is an invalid/swapped pair -> None, never negative."""
    result = pr._compute_holding_period_days(_ENTRY, _BEFORE_ENTRY)
    assert result is None


def test_no_negative_value_ever_emitted_across_synthetic_pairs():
    """No ordering of synthetic dates may yield a negative holding period."""
    pairs = [
        (_ENTRY, _SAME_DAY_EXIT),
        (_ENTRY, _MULTI_DAY_EXIT),
        (_MULTI_DAY_EXIT, _ENTRY),  # swapped
        (_ENTRY, _BEFORE_ENTRY),  # invalid
    ]
    for entry, exit_ in pairs:
        val = pr._compute_holding_period_days(entry, exit_)
        assert val is None or val >= 0.0
