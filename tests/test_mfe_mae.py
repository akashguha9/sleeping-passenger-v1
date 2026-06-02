"""Tests for scripts/mfe_mae.py — entry-quality diagnosis."""
from __future__ import annotations

import pytest

from scripts.mfe_mae import (
    BAD_DISCOVERY_OR_BAD_ENTRY,
    GOOD_DISCOVERY_BAD_EXIT,
    GOOD_DISCOVERY_GOOD_ENTRY,
    GOOD_THESIS_POOR_ENTRY_TIMING,
    PENDING_HORIZON,
    analyze,
    compute_excursions,
    diagnose,
)


def test_provisional_excursions_from_live_only():
    ex = compute_excursions(100.0, live=105.0)
    assert ex["current_return"] == pytest.approx(0.05)
    assert ex["mfe"] == pytest.approx(0.05)
    assert ex["mae"] == 0.0
    assert ex["provisional"] is True


def test_true_excursions_from_high_low():
    ex = compute_excursions(100.0, live=102.0, high_since_entry=110.0, low_since_entry=96.0)
    assert ex["mfe"] == pytest.approx(0.10)
    assert ex["mae"] == pytest.approx(-0.04)
    assert ex["provisional"] is False


def test_diagnose_good_discovery_bad_exit():
    assert diagnose(mfe=0.10, mae=-0.01, final_pl=-5.0, current_return=-0.01, age_trading_days=8) == GOOD_DISCOVERY_BAD_EXIT


def test_diagnose_good_thesis_poor_entry():
    assert diagnose(mfe=0.06, mae=-0.05, final_pl=3.0, current_return=0.03, age_trading_days=8) == GOOD_THESIS_POOR_ENTRY_TIMING


def test_diagnose_bad_discovery():
    assert diagnose(mfe=0.01, mae=-0.05, final_pl=-2.0, current_return=-0.05, age_trading_days=8) == BAD_DISCOVERY_OR_BAD_ENTRY


def test_diagnose_good_discovery_good_entry():
    assert diagnose(mfe=0.06, mae=-0.01, final_pl=4.0, current_return=0.05, age_trading_days=8) == GOOD_DISCOVERY_GOOD_ENTRY


def test_pending_when_young_and_flat():
    assert diagnose(mfe=0.0, mae=0.0, final_pl=0.0, current_return=0.005, age_trading_days=2) == PENDING_HORIZON


def test_analyze_is_advisory():
    out = analyze(100.0, live=108.0, final_pl=-1.0, age_trading_days=8)
    assert out["diagnosis"] == GOOD_DISCOVERY_BAD_EXIT
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["human_execution_required"] is True
