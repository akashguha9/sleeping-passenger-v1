"""Unit tests for the strategy-layer engines (mechanism, doctrine, nodes,
competition, payoff matrix, chess, underground, distribution, backhand)."""

from __future__ import annotations

import pytest

from src.strategy.backhand import assess_backhand_defence
from src.strategy.chess_promotion import assess_chess_state
from src.strategy.competition_density import assess_competition_density
from src.strategy.distribution import (
    assess_distribution,
    percentile_band,
    place_metric,
    z_to_percentile,
)
from src.strategy.doctrine_filter import apply_doctrine_filter
from src.strategy.mechanism import assess_mechanism
from src.strategy.node_payoff import (
    casino_expected_value,
    evaluate_node_payoff,
    food_chain_power,
)
from src.strategy.predator_nodes import classify_predator_node
from src.strategy.underground import assess_underground


# ---------------------------------------------------------------------------
# Mechanism + doctrine
# ---------------------------------------------------------------------------


def test_no_mechanism_forces_zero_narrative_value() -> None:
    result = assess_mechanism(narrative="vibes", probability_shock=0.95)
    assert not result.mechanism_valid
    assert result.narrative_value == 0.0
    assert any("NO MECHANISM" in r for r in result.rationale)


def test_valid_mechanism_scales_with_shock() -> None:
    strong = assess_mechanism(
        narrative="grid capex", probability_shock=0.8, cash_flow_impact=0.7,
        demand_impact=0.6,
    )
    weak_shock = assess_mechanism(
        narrative="grid capex", probability_shock=0.2, cash_flow_impact=0.7,
        demand_impact=0.6,
    )
    assert strong.mechanism_valid
    assert strong.narrative_value > weak_shock.narrative_value > 0


def test_doctrine_rejects_each_fatal_condition() -> None:
    mechanism = assess_mechanism(
        narrative="n", probability_shock=0.5, cash_flow_impact=0.6
    )
    good = apply_doctrine_filter(
        mechanism=mechanism, evidence_source_count=2,
        value_chain_role_known=True,
    )
    assert good.passed

    fragile = apply_doctrine_filter(
        mechanism=mechanism, evidence_source_count=2,
        value_chain_role_known=True, balance_sheet_fragility=0.9,
    )
    assert "fatal_balance_sheet_fragility" in fragile.reject_reasons

    no_cash = apply_doctrine_filter(
        mechanism=mechanism, evidence_source_count=2,
        value_chain_role_known=True, has_cash_flow_path=False,
    )
    assert "pure_story_no_cash_flow_path" in no_cash.reject_reasons


# ---------------------------------------------------------------------------
# Predator nodes
# ---------------------------------------------------------------------------


def test_chokepoint_traits_classify_as_crocodile() -> None:
    node = classify_predator_node(
        {"chokepoint_control": 0.9, "switching_costs": 0.8, "flow_capture": 0.7},
        defensibility=0.7,
    )
    assert node.predator_node == "crocodile"
    assert node.dominant_weapon == "chokepoint_control"
    assert node.node_confidence >= 0.35


def test_platform_traits_classify_as_orca() -> None:
    node = classify_predator_node(
        {"network_effects": 0.9, "ecosystem_control": 0.8, "retention": 0.8,
         "coordination_leverage": 0.7},
    )
    assert node.predator_node == "orca"


def test_weak_traits_stay_unclassified_no_metaphor_overfit() -> None:
    node = classify_predator_node({"network_effects": 0.15})
    assert node.predator_node == "unclassified"
    assert node.node_fit_score == 0.0
    assert any("refusing to force" in r for r in node.rationale)


# ---------------------------------------------------------------------------
# Competition density
# ---------------------------------------------------------------------------


def test_easy_field_discounts_and_brutal_field_boosts() -> None:
    easy = assess_competition_density(
        raw_performance=0.9, era_difficulty=0.1, opponent_quality=0.2,
        evidence_confidence=0.8,
    )
    brutal = assess_competition_density(
        raw_performance=0.55, era_difficulty=0.9, opponent_quality=0.85,
        evidence_confidence=0.8,
    )
    # Strong raw growth in an easy field loses to moderate growth in war.
    assert brutal.competition_adjusted_strength > easy.competition_adjusted_strength
    assert any("easy field" in r for r in easy.rationale)
    assert any("brutal competition" in r for r in brutal.rationale)


# ---------------------------------------------------------------------------
# Node payoff matrix
# ---------------------------------------------------------------------------


def test_casino_ev_rejects_excitement_without_odds() -> None:
    assert casino_expected_value(
        probability_of_success=0.1, upside=5.0, downside=1.0,
        cost_of_waiting=0.1,
    ) < 0
    assert casino_expected_value(
        probability_of_success=0.6, upside=1.0, downside=0.3,
    ) > 0


def test_prey_position_is_capped() -> None:
    prey = food_chain_power(position="prey", pricing_power=0.9,
                            dependency_control=0.9)
    toll = food_chain_power(position="toll_booth", pricing_power=0.9,
                            dependency_control=0.9)
    assert prey <= 0.35
    assert toll > prey


def test_uncrossed_threshold_flags_watchlist_ceiling() -> None:
    matrix = evaluate_node_payoff(
        probability_of_success=0.7, upside=0.8, downside=0.2,
        threshold_crossed=False, missing_thresholds=["profitability"],
    )
    assert not matrix.threshold_crossed
    assert any("no threshold, no buy" in r for r in matrix.rationale)


def test_long_half_life_earns_durable_edge() -> None:
    durable = evaluate_node_payoff(
        current_edge_strength=0.8, edge_half_life_months=96,
        defensibility=0.8, threshold_crossed=True,
    )
    fleeting = evaluate_node_payoff(
        current_edge_strength=0.8, edge_half_life_months=2,
        defensibility=0.8, threshold_crossed=True,
    )
    assert durable.durable_edge_value > fleeting.durable_edge_value
    assert fleeting.decay_risk > durable.decay_risk


# ---------------------------------------------------------------------------
# Chess promotion
# ---------------------------------------------------------------------------


def test_fake_queen_is_demoted() -> None:
    fake = assess_chess_state(
        declared_state="queen",
        state_evidence={"network_effects": 0.2, "retention": 0.3,
                        "ecosystem_control": 0.2, "multi_vector_mobility": 0.1},
    )
    assert fake.fake_queen_detected
    assert fake.current_piece_state in ("rook", "bishop")
    assert any("FAKE QUEEN" in r for r in fake.rationale)

    real = assess_chess_state(
        declared_state="queen",
        state_evidence={"network_effects": 0.8, "retention": 0.8,
                        "ecosystem_control": 0.7, "multi_vector_mobility": 0.7},
    )
    assert not real.fake_queen_detected
    assert real.dynamic_table_score > fake.dynamic_table_score


def test_pawn_with_credible_promotion_beats_static_pawn() -> None:
    promoting = assess_chess_state(
        declared_state="pawn", promotion_target="rook",
        promotion_probability=0.6, promotion_payoff=0.8,
        promotion_timeframe_years=2, mobility=0.5,
    )
    static = assess_chess_state(declared_state="pawn")
    assert promoting.dynamic_table_score > static.dynamic_table_score
    assert promoting.promotion_adjusted_value > 0
    assert static.promotion_adjusted_value == 0.0


def test_invalid_promotion_path_is_voided() -> None:
    result = assess_chess_state(
        declared_state="rook", promotion_target="knight",
        promotion_probability=0.9, promotion_payoff=0.9,
    )
    assert result.promotion_adjusted_value == 0.0
    assert any("not a valid transition" in r for r in result.rationale)


# ---------------------------------------------------------------------------
# Underground
# ---------------------------------------------------------------------------


def test_high_visibility_is_not_underground() -> None:
    result = assess_underground(visibility=0.9, originality=0.9)
    assert not result.underground_status
    assert result.verdict == "NOT_UNDERGROUND"


def test_buried_noise_vs_buried_gem() -> None:
    noise = assess_underground(
        visibility=0.1, originality=0.2, cult_traction=0.1,
        breakout_catalyst=0.0, monetization_path=0.0,
    )
    gem = assess_underground(
        visibility=0.15, originality=0.85, cult_traction=0.7,
        repeat_usage=0.7, distribution_constraint_solvable=0.6,
        breakout_catalyst=0.5, monetization_path=0.6,
    )
    assert noise.verdict == "BURIED_FOR_REASON"
    assert gem.buried_gem_score > noise.buried_gem_score
    assert gem.verdict in ("RISING_UNDERGROUND", "BREAKOUT_READY",
                           "BURIED_GEM_WATCHLIST")


def test_viral_one_hit_is_temporary_pavilion() -> None:
    viral = assess_underground(
        visibility=0.3, originality=0.5, cult_traction=0.6, repeat_usage=0.1,
        attention_half_life_days=7,
    )
    assert viral.verdict == "ONE_HIT_NOISE"
    assert viral.temporary_pavilion
    assert any("Temporary Pavilion" in r for r in viral.rationale)


def test_gatekeeper_blocked_verdict() -> None:
    blocked = assess_underground(
        visibility=0.2, originality=0.8, cult_traction=0.7, repeat_usage=0.6,
        breakout_catalyst=0.6, monetization_path=0.6, gatekeeper_risk=0.85,
    )
    assert blocked.verdict == "GATEKEEPER_BLOCKED"


def test_breakout_ready_requires_all_legs() -> None:
    ready = assess_underground(
        visibility=0.2, originality=0.9, cult_traction=0.85, repeat_usage=0.8,
        distribution_constraint_solvable=0.8, breakout_catalyst=0.8,
        monetization_path=0.8, attention_to_revenue_conversion=0.7,
    )
    assert ready.verdict == "BREAKOUT_READY"

    no_distribution = assess_underground(
        visibility=0.2, originality=0.9, cult_traction=0.85, repeat_usage=0.8,
        distribution_constraint_solvable=0.1, breakout_catalyst=0.8,
        monetization_path=0.8,
    )
    assert no_distribution.verdict == "CULT_SIGNAL_NEEDS_DISTRIBUTION"


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


def test_z_score_and_percentile_math() -> None:
    placement = place_metric(
        metric="roic", value=0.20,
        peer_values=[0.10, 0.10, 0.10, 0.10, 0.10, 0.10],
    )
    assert placement.z_score == 0.0 or placement.peer_std == 0.0
    placement = place_metric(
        metric="roic", value=0.20,
        peer_values=[0.08, 0.10, 0.12, 0.09, 0.11, 0.10],
    )
    assert placement.z_score > 2.0
    assert placement.band in ("rare", "extreme_outlier", "strong")
    assert z_to_percentile(0.0) == pytest.approx(50.0)
    assert percentile_band(99.5) == "extreme_outlier"


def test_one_off_distortion_is_fake_outlier() -> None:
    placement = place_metric(
        metric="margin", value=0.9,
        peer_values=[0.1, 0.12, 0.11, 0.09, 0.1, 0.13],
        one_off_distortion=True,
    )
    assert placement.fake_outlier
    assert "one-off" in placement.fake_outlier_reason


def test_wrong_peer_universe_earns_confidence_penalty() -> None:
    wrong = assess_distribution(
        peer_universe_node="bluefin_tuna", company_node="crocodile",
        metrics={"growth": {"value": 0.4,
                            "peer_values": [0.1, 0.1, 0.12, 0.11, 0.09, 0.1]}},
        quality_percentile=90,
    )
    right = assess_distribution(
        peer_universe_node="crocodile", company_node="crocodile",
        metrics={"growth": {"value": 0.4,
                            "peer_values": [0.1, 0.1, 0.12, 0.11, 0.09, 0.1]}},
        quality_percentile=90,
    )
    assert wrong.confidence_penalty > right.confidence_penalty
    assert wrong.distribution_intelligence_score < (
        right.distribution_intelligence_score
    )
    assert any("PEER UNIVERSE INVALID" in r for r in wrong.rationale)


def test_archetypes_cover_required_cases() -> None:
    barbell = assess_distribution(
        peer_universe_node="n", company_node="n", metrics={},
        quality_percentile=90, fragility_percentile=90,
    )
    assert barbell.archetype == "barbell"
    hype = assess_distribution(
        peer_universe_node="n", company_node="n", metrics={},
        quality_percentile=30, narrative_percentile=90,
    )
    assert hype.archetype == "right_tail_narrative_weak_fundamentals"
    hidden = assess_distribution(
        peer_universe_node="n", company_node="n", metrics={},
        quality_percentile=88, visibility=0.2, catalyst=0.7,
    )
    assert hidden.archetype == "hidden_right_tail"
    fragile = assess_distribution(
        peer_universe_node="n", company_node="n", metrics={},
        quality_percentile=40, fragility_percentile=90,
    )
    assert fragile.archetype == "left_tail_fragility"


# ---------------------------------------------------------------------------
# Backhand defence
# ---------------------------------------------------------------------------


def test_untested_thesis_earns_no_survival_credit() -> None:
    result = assess_backhand_defence(bull_thesis="great company", bear_attacks=[])
    assert result.backhand_defence_score == 0.0
    assert "never been attacked" in result.weakest_point


def test_existential_unresolved_caps_score() -> None:
    fatal = assess_backhand_defence(
        bull_thesis="growth story",
        evidence_strength=0.9, weak_side_improvement=0.9,
        bear_attacks=[{"attack": "solvency collapse", "severity": 0.9,
                       "existential": True, "defence_strength": 0.2,
                       "defence_response": "hope"}],
    )
    assert fatal.existential_bear_unresolved
    assert fatal.backhand_defence_score <= 2.0
    defended = assess_backhand_defence(
        bull_thesis="growth story",
        evidence_strength=0.9, weak_side_improvement=0.6,
        bear_attacks=[{"attack": "solvency collapse", "severity": 0.9,
                       "existential": True, "defence_strength": 0.95,
                       "defence_response": "net cash, no maturities"}],
    )
    assert not defended.existential_bear_unresolved
    assert defended.backhand_defence_score > fatal.backhand_defence_score
