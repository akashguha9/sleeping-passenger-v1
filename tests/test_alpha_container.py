"""Module H — container recommendation invariants."""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.container import CONTAINERS, recommend_container


def test_strong_durable_proven_signal_is_core_candidate() -> None:
    result = recommend_container(
        conviction=85.0,
        volatility=30.0,
        half_life_days=365.0,
        proof_score=80.0,
        valuation_risk=30.0,
    )
    assert result["recommended_container"] == "core_candidate"
    assert result["time_horizon"] == "long"


def test_rich_valuation_weak_proof_is_avoid_trap() -> None:
    result = recommend_container(
        conviction=90.0,
        half_life_days=365.0,
        proof_score=20.0,
        valuation_risk=90.0,
    )
    assert result["recommended_container"] == "avoid_trap"


def test_short_half_life_is_event_trade_only() -> None:
    result = recommend_container(
        conviction=70.0, half_life_days=5.0, proof_score=60.0, valuation_risk=40.0
    )
    assert result["recommended_container"] == "event_trade_only"
    assert result["time_horizon"] == "short"


def test_no_proof_no_conviction_is_ignore() -> None:
    result = recommend_container(conviction=10.0, proof_score=10.0)
    assert result["recommended_container"] == "ignore"


def test_hedge_intent_routes_to_hedge_candidate() -> None:
    result = recommend_container(conviction=60.0, hedge_intent=True)
    assert result["recommended_container"] == "hedge_candidate"


def test_middling_signal_lands_in_research_or_watchlist() -> None:
    result = recommend_container(conviction=45.0, proof_score=45.0)
    assert result["recommended_container"] in ("deep_research", "watchlist")


def test_every_output_is_a_known_container_with_disclaimer() -> None:
    for conviction in (0.0, 30.0, 50.0, 70.0, 100.0):
        for proof in (0.0, 50.0, 100.0):
            result = recommend_container(
                conviction=conviction, proof_score=proof, half_life_days=90.0
            )
            assert result["recommended_container"] in CONTAINERS
            assert 0.0 <= result["confidence"] <= 100.0
            assert result["disclaimer"] == ADVISORY_DISCLAIMER


def test_high_volatility_adds_risk_control() -> None:
    result = recommend_container(conviction=60.0, proof_score=60.0, volatility=90.0)
    assert any("volatility" in note.lower() for note in result["risk_controls"])


def test_no_execution_language_in_outputs() -> None:
    result = recommend_container(conviction=90.0, proof_score=90.0)
    text = " ".join(
        [result["reason"], result["disclaimer"], *result["risk_controls"]]
    ).lower()
    for forbidden in ("place order", "broker", "guaranteed"):
        assert forbidden not in text
