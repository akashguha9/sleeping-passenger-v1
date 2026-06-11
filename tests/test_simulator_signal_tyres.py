"""Signal tyre physics: half-life decay, grip, freshness, conviction gate."""

from __future__ import annotations

import pytest

from src.simulator.signal_tyres import (
    COMPOUND_HARD,
    COMPOUND_SOFT,
    HARD_EVIDENCE_FLOOR,
    blended_grip_pct,
    classify_signal_compound,
    hard_conviction_allowed,
    reaction_freshness,
    score_signal_tyre,
    signal_grip_pct,
)


def test_grip_is_100_at_age_zero() -> None:
    assert signal_grip_pct(0.0, 18.0) == 100.0


def test_grip_halves_at_exactly_one_half_life() -> None:
    assert signal_grip_pct(18.0, 18.0) == pytest.approx(50.0)


def test_grip_quarters_at_two_half_lives() -> None:
    assert signal_grip_pct(36.0, 18.0) == pytest.approx(25.0)


def test_grip_never_negative_for_extreme_age() -> None:
    assert 0.0 <= signal_grip_pct(1_000_000.0, 18.0) < 0.001


def test_soft_compound_decays_faster_than_hard() -> None:
    soft = score_signal_tyre(
        signal_type="social_spike", raw_strength=80, signal_age_hours=72
    )
    hard = score_signal_tyre(
        signal_type="free_cash_flow", raw_strength=80, signal_age_hours=72
    )
    assert soft.compound == COMPOUND_SOFT
    assert hard.compound == COMPOUND_HARD
    assert soft.signal_grip_pct < hard.signal_grip_pct
    assert soft.is_worn
    assert not hard.is_worn


def test_classification_defaults_unknown_types_to_soft() -> None:
    assert classify_signal_compound("totally_unknown_signal") == COMPOUND_SOFT


def test_reaction_lag_reduces_effective_signal_strength() -> None:
    fresh = score_signal_tyre(
        signal_type="earnings_beat",
        raw_strength=90,
        signal_age_hours=10,
        reaction_lag_hours=0,
    )
    late = score_signal_tyre(
        signal_type="earnings_beat",
        raw_strength=90,
        signal_age_hours=10,
        reaction_lag_hours=48,
    )
    assert late.effective_signal_strength < fresh.effective_signal_strength
    assert "LATE_DETECTION" in late.reason_codes


def test_reaction_window_missed_zeroes_freshness() -> None:
    assert reaction_freshness(20.0, 12.0) == 0.0
    state = score_signal_tyre(
        signal_type="social_spike",
        raw_strength=95,
        signal_age_hours=1,
        reaction_lag_hours=20,
    )
    assert state.effective_signal_strength == 0.0
    assert "REACTION_WINDOW_MISSED" in state.reason_codes


def test_strong_but_late_is_weak_case_study() -> None:
    # Case study 2: a raw-90 soft signal at ~one half-life with late
    # detection collapses to a fraction of its raw strength.
    state = score_signal_tyre(
        signal_type="social_spike",
        raw_strength=90,
        signal_age_hours=18.0,
        reaction_lag_hours=4.8,
    )
    assert state.effective_signal_strength < state.raw_strength * 0.6


def test_stale_soft_signal_blocked_from_hard_conviction() -> None:
    stale_soft = score_signal_tyre(
        signal_type="viral_article", raw_strength=95, signal_age_hours=200
    )
    allowed, reasons = hard_conviction_allowed(
        [stale_soft], hard_evidence_score=0.9
    )
    assert not allowed
    assert "STALE_SOFT_CANNOT_SUPPORT_HARD_CONVICTION" in reasons


def test_fresh_soft_alone_needs_hard_evidence() -> None:
    fresh_soft = score_signal_tyre(
        signal_type="social_spike", raw_strength=90, signal_age_hours=1
    )
    allowed, reasons = hard_conviction_allowed(
        [fresh_soft], hard_evidence_score=HARD_EVIDENCE_FLOOR - 0.1
    )
    assert not allowed
    assert "SOFT_ONLY_NEEDS_HARD_EVIDENCE" in reasons


def test_hard_tyre_with_evidence_supports_conviction() -> None:
    hard = score_signal_tyre(
        signal_type="backlog", raw_strength=80, signal_age_hours=100
    )
    allowed, reasons = hard_conviction_allowed([hard], hard_evidence_score=0.8)
    assert allowed
    assert "HARD_CONVICTION_SUPPORTED" in reasons


def test_no_signals_blocks_conviction() -> None:
    allowed, reasons = hard_conviction_allowed([], hard_evidence_score=1.0)
    assert not allowed
    assert "NO_SIGNALS_PRESENT" in reasons


def test_blended_grip_weighted_by_strength() -> None:
    strong_fresh = score_signal_tyre(
        signal_type="backlog", raw_strength=90, signal_age_hours=0
    )
    weak_stale = score_signal_tyre(
        signal_type="social_spike", raw_strength=10, signal_age_hours=500
    )
    blended = blended_grip_pct([strong_fresh, weak_stale])
    assert blended > 80.0
    assert blended_grip_pct([]) == 0.0


def test_hostile_circuit_shortens_half_life() -> None:
    calm = score_signal_tyre(
        signal_type="earnings_beat",
        raw_strength=80,
        signal_age_hours=60,
        circuit_decay_multiplier=1.0,
    )
    hostile = score_signal_tyre(
        signal_type="earnings_beat",
        raw_strength=80,
        signal_age_hours=60,
        circuit_decay_multiplier=0.5,
    )
    assert hostile.adjusted_half_life_hours < calm.adjusted_half_life_hours
    assert hostile.signal_grip_pct < calm.signal_grip_pct
