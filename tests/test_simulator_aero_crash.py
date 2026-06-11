"""Aero/chassis stability engine and crash-case permutation simulator tests."""

from __future__ import annotations

import pytest

from src.simulator.aero_engine import (
    MIN_DRAG,
    compute_downforce,
    compute_drag,
    score_aero,
)
from src.simulator.crash_simulator import (
    SEVERE_COMBINATION_THRESHOLD,
    pair_beta,
    simulate_crash_cases,
)

STRONG_EVIDENCE = {
    "filing_evidence": 0.9,
    "cash_flow_quality": 0.8,
    "backlog_evidence": 0.9,
    "insider_alignment": 0.7,
    "primary_source_confirmation": 0.8,
}


def _aero(**overrides):
    base = dict(
        evidence=STRONG_EVIDENCE,
        noise_level=0.2,
        contradiction_level=0.1,
        duplication_level=0.2,
        ambiguity_level=0.2,
        promotional_bias=0.1,
        independent_origin_count=10,
        total_source_count=12,
        sector_momentum=0.4,
        stock_specific_thrust=0.6,
        hidden_fundamental_improvement=0.7,
        narrative_crowding=0.2,
        data_quality=0.9,
    )
    base.update(overrides)
    return score_aero(**base)


def test_aero_efficiency_is_downforce_over_drag() -> None:
    state = _aero()
    assert state.aero_efficiency == pytest.approx(
        state.evidence_downforce / state.information_drag
    )
    assert state.aero_efficiency > 1.0


def test_drag_is_floored_so_efficiency_cannot_explode() -> None:
    assert compute_drag(
        noise_level=0, contradiction_level=0, duplication_level=0,
        ambiguity_level=0, promotional_bias=0,
    ) == MIN_DRAG


def test_downforce_zero_without_evidence() -> None:
    assert compute_downforce({}) == 0.0


def test_dirty_air_penalty_in_aero_state() -> None:
    state = _aero(independent_origin_count=2, total_source_count=37)
    assert state.dirty_air > 0.9
    assert "DIRTY_AIR_PENALTY" in state.reason_codes


def test_slipstream_dependence_detected() -> None:
    state = _aero(sector_momentum=0.9, stock_specific_thrust=0.1)
    assert state.slipstream >= 0.7
    assert "SLIPSTREAM_DEPENDENT" in state.reason_codes


def test_ground_effect_requires_low_crowding() -> None:
    quiet = _aero(hidden_fundamental_improvement=0.8, narrative_crowding=0.1)
    crowded = _aero(hidden_fundamental_improvement=0.8, narrative_crowding=0.9)
    assert quiet.ground_effect > crowded.ground_effect


def test_drs_opens_only_with_confirmed_near_catalyst() -> None:
    confirmed = _aero(catalyst_proximity_days=20, catalyst_confirmed=True)
    unconfirmed = _aero(catalyst_proximity_days=20, catalyst_confirmed=False)
    far = _aero(catalyst_proximity_days=90, catalyst_confirmed=True)
    assert confirmed.drs_active
    assert not unconfirmed.drs_active
    assert unconfirmed.drs_status == "unconfirmed_catalyst"
    assert not far.drs_active


def test_aero_stall_on_regime_shift_or_data_collapse() -> None:
    assert _aero(regime_shift_level=0.8).aero_stall_warning
    assert _aero(data_quality=0.1).aero_stall_warning
    assert not _aero().aero_stall_warning


def test_porpoising_detected_from_score_oscillation() -> None:
    stable = _aero(score_history=[0.6, 0.61, 0.62, 0.6])
    oscillating = _aero(score_history=[0.2, 0.8, 0.25, 0.75, 0.3])
    assert not stable.porpoising_warning
    assert oscillating.porpoising_warning
    assert "PORPOISING_FREEZE_PROMOTION" in oscillating.reason_codes


# ---------------------------------------------------------------------------
# Crash simulator
# ---------------------------------------------------------------------------


def test_crash_density_is_severe_over_total() -> None:
    report = simulate_crash_cases(
        {"high_valuation": 0.9, "weak_fcf": 0.8, "rising_rates": 0.9}
    )
    # 3 pairs + 1 triple = 4 combinations.
    assert report.total_tested_combinations == 4
    assert report.crash_density == pytest.approx(
        report.severe_combination_count / report.total_tested_combinations
    )
    assert report.crash_density > 0.5


def test_interaction_effects_exceed_additive_sum() -> None:
    report = simulate_crash_cases({"high_valuation": 0.8, "rising_rates": 0.8})
    combo = report.tested_combinations[0]
    additive = 0.8 + 0.8
    assert combo.combined_score > additive
    assert combo.interaction_effect == pytest.approx(
        pair_beta("high_valuation", "rising_rates") * 0.8 * 0.8
    )


def test_known_synergy_pairs_amplified() -> None:
    assert pair_beta("high_valuation", "rising_rates") > pair_beta(
        "high_valuation", "late_detection"
    )


def test_low_risks_survive_the_wall() -> None:
    report = simulate_crash_cases(
        {"high_valuation": 0.2, "rising_rates": 0.1, "low_volume": 0.1}
    )
    assert report.severe_combination_count == 0
    assert report.crash_density == 0.0
    assert "CRASH_SURVIVABLE" in report.reason_codes
    assert report.crash_risk_score < 0.3


def test_stacked_risks_produce_high_crash_risk() -> None:
    report = simulate_crash_cases(
        {
            "high_valuation": 0.9,
            "weak_fcf": 0.8,
            "rising_rates": 0.8,
            "insider_selling": 0.7,
        }
    )
    assert report.crash_risk_score > 0.6
    assert "HIGH_CRASH_RISK" in report.reason_codes
    assert report.worst_crash_combination
    assert report.worst_combination_score >= SEVERE_COMBINATION_THRESHOLD


def test_primary_crash_vector_and_safety_conditions() -> None:
    report = simulate_crash_cases(
        {"revenge_trading": 0.9, "low_volume": 0.5, "stale_signal": 0.2}
    )
    assert report.primary_crash_vector == "revenge_trading"
    assert report.primary_crash_category == "driver_behavior_crash"
    assert any("revenge_trading" in c for c in report.safe_to_enter_conditions)
    assert report.thesis_damage_triggers


def test_empty_risk_factors_yield_zero_risk() -> None:
    report = simulate_crash_cases({})
    assert report.crash_risk_score == 0.0
    assert report.crash_density == 0.0
    assert report.total_tested_combinations == 0


def test_crash_report_is_serializable() -> None:
    payload = simulate_crash_cases({"high_valuation": 0.5, "weak_fcf": 0.4}).to_dict()
    assert isinstance(payload["tested_combinations"], list)
    assert payload["individual_risks"] == {"high_valuation": 0.5, "weak_fcf": 0.4}
