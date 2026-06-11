"""Theme mapper, exposure resolver, and circuit classifier tests."""

from __future__ import annotations

import pytest

from src.simulator.circuit_classifier import (
    CIRCUIT_BIOTECH_EVENT,
    CIRCUIT_DEFENSIVE,
    CIRCUIT_HIGH_VOLATILITY_MOMENTUM,
    CIRCUIT_LARGE_CAP,
    CIRCUIT_MICRO_CAP,
    CIRCUIT_MID_CAP,
    CIRCUIT_PROFILES,
    CIRCUIT_SMALL_CAP,
    classify_circuit,
)
from src.simulator.exposure_resolver import (
    EXPOSURE_DIRECT,
    EXPOSURE_FALSE_POSITIVE,
    EXPOSURE_NARRATIVE_PASSENGER,
    EXPOSURE_SECOND_ORDER,
    resolve_exposure,
)
from src.simulator.theme_mapper import map_theme, score_track_condition


def test_track_condition_supportive_when_tailwinds_dominate() -> None:
    raw, normalized = score_track_condition(
        macro_support=0.8, sector_momentum=0.7, policy_tailwind=0.9,
        liquidity_environment=0.7, risk_appetite=0.6,
        regulatory_friction=0.1, crowding=0.2, valuation_heat=0.2,
    )
    assert raw == pytest.approx(3.2)
    assert normalized > 0.6


def test_track_condition_hostile_when_heat_and_friction_dominate() -> None:
    _, normalized = score_track_condition(
        macro_support=0.2, sector_momentum=0.1, policy_tailwind=0.0,
        liquidity_environment=0.2, risk_appetite=0.1,
        regulatory_friction=0.9, crowding=0.9, valuation_heat=0.9,
    )
    assert normalized < 0.4


def test_theme_mapper_flags_valuation_heat_and_crowding() -> None:
    theme = map_theme(
        theme="ai_grid", policy_fit=0.8, macro_fit=0.6, sector_momentum=0.7,
        liquidity_support=0.6, valuation_heat=0.8, crowding=0.8,
        regulatory_friction=0.3,
    )
    assert "VALUATION_HEAT_WARNING" in theme.reason_codes
    assert "CROWDED_THEME" in theme.reason_codes


def test_backlog_linked_company_is_direct_beneficiary() -> None:
    exposure = resolve_exposure(
        ticker="gridco", theme="ai_grid",
        revenue_exposure=0.7, margin_sensitivity=0.5, backlog_linkage=0.8,
        customer_linkage=0.5, geographic_fit=0.6, policy_fit=0.7,
        supply_chain_position=0.6,
    )
    assert exposure.exposure_class == EXPOSURE_DIRECT
    assert exposure.ticker == "GRIDCO"
    assert exposure.exposure_score > 0.5


def test_supply_chain_company_is_second_order() -> None:
    exposure = resolve_exposure(
        ticker="cu", theme="ai_grid",
        revenue_exposure=0.2, margin_sensitivity=0.6, backlog_linkage=0.1,
        customer_linkage=0.3, geographic_fit=0.4, policy_fit=0.3,
        supply_chain_position=0.7,
    )
    assert exposure.exposure_class == EXPOSURE_SECOND_ORDER


def test_weak_evidence_creates_narrative_passenger_or_false_positive() -> None:
    passenger = resolve_exposure(
        ticker="hype", theme="ai_grid",
        revenue_exposure=0.1, margin_sensitivity=0.4, backlog_linkage=0.2,
        customer_linkage=0.4, geographic_fit=0.5, policy_fit=0.4,
        supply_chain_position=0.3, weak_evidence_penalty=0.6,
    )
    assert passenger.exposure_class == EXPOSURE_NARRATIVE_PASSENGER

    false_positive = resolve_exposure(
        ticker="fake", theme="ai_grid",
        revenue_exposure=0.1, margin_sensitivity=0.1, backlog_linkage=0.0,
        customer_linkage=0.1, geographic_fit=0.1, policy_fit=0.1,
        supply_chain_position=0.1, weak_evidence_penalty=0.9,
    )
    assert false_positive.exposure_class == EXPOSURE_FALSE_POSITIVE


def test_cap_size_circuit_boundaries() -> None:
    assert classify_circuit(market_cap_usd=50e9).circuit == CIRCUIT_LARGE_CAP
    assert classify_circuit(market_cap_usd=5e9).circuit == CIRCUIT_MID_CAP
    assert classify_circuit(market_cap_usd=1e9).circuit == CIRCUIT_SMALL_CAP
    assert classify_circuit(market_cap_usd=100e6).circuit == CIRCUIT_MICRO_CAP


def test_special_regimes_outrank_cap_size() -> None:
    biotech = classify_circuit(
        market_cap_usd=50e9, is_biotech_event_driven=True
    )
    assert biotech.circuit == CIRCUIT_BIOTECH_EVENT

    momentum = classify_circuit(market_cap_usd=50e9, annualized_volatility=0.95)
    assert momentum.circuit == CIRCUIT_HIGH_VOLATILITY_MOMENTUM

    defensive = classify_circuit(market_cap_usd=5e9, sector="utilities")
    assert defensive.circuit == CIRCUIT_DEFENSIVE


def test_circuit_difficulty_is_sum_of_risk_components() -> None:
    for profile in CIRCUIT_PROFILES.values():
        expected = (
            profile.volatility_risk
            + profile.liquidity_risk
            + profile.data_quality_risk
            + profile.manipulation_risk
            + profile.crash_baseline
        )
        assert profile.difficulty == pytest.approx(expected)


def test_harder_circuits_demand_more() -> None:
    micro = CIRCUIT_PROFILES[CIRCUIT_MICRO_CAP]
    large = CIRCUIT_PROFILES[CIRCUIT_LARGE_CAP]
    assert micro.difficulty > large.difficulty
    assert micro.threshold_multiplier > large.threshold_multiplier
    assert micro.position_size_cap_pct < large.position_size_cap_pct
    assert micro.half_life_decay_multiplier < large.half_life_decay_multiplier
    # Microcap circuit bans soft signals entirely.
    assert "soft" not in micro.allowed_signal_compounds
    assert "soft" in large.allowed_signal_compounds
