"""Adaptive Opponent Model proofs: weapon maps, weak-side AttackROI,
niche beachhead-vs-cage, the Opponent Adaptation Index, market-awareness
blind layers, catalyst+1, complete game, and pipeline gating."""

from __future__ import annotations

import copy

import pytest

from src.strategy.adaptive_opponent import (
    assess_adaptation,
    assess_adaptive_opponent,
    assess_weak_side,
    classify_niche,
    complete_game_score,
    map_weapons,
    model_catalyst_plus_one,
)
from src.simulator.pipeline import evaluate_candidate_payload
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


# --- Weapon Map ---------------------------------------------------------------
def test_weapon_map_names_strongest_edge() -> None:
    weapons = map_weapons(
        {"pricing_power": 0.9, "narrative_momentum": 0.5},
        evidence_reliability=0.8, durability=0.7, crowding=0.2,
    )
    assert weapons.strongest_weapon == "pricing_power"
    assert weapons.runner_up == "narrative_momentum"
    assert not weapons.overused
    assert weapons.weapon_score > 4.0


def test_crowded_strong_weapon_is_flagged_overused() -> None:
    weapons = map_weapons(
        {"narrative_momentum": 0.9}, crowding=0.8, evidence_reliability=0.7,
    )
    assert weapons.overused
    assert any("predictable" in r for r in weapons.rationale)
    uncrowded = map_weapons(
        {"narrative_momentum": 0.9}, crowding=0.0, evidence_reliability=0.7,
    )
    assert weapons.weapon_score < uncrowded.weapon_score


def test_no_strengths_means_no_weapon() -> None:
    assert map_weapons({}).strongest_weapon == "none_established"


# --- Weak side + minimum viable weakness ---------------------------------------
def test_attack_roi_separates_fatal_from_manageable() -> None:
    fatal = assess_weak_side(
        {"customer_concentration": 0.9}, attack_probability=0.8,
        cost_to_exploit=0.2,
    )
    assert fatal.classification == "fatal"
    assert not fatal.minimum_viable_pass

    expensive_to_attack = assess_weak_side(
        {"customer_concentration": 0.6}, attack_probability=0.4,
        cost_to_exploit=0.7,
    )
    assert expensive_to_attack.classification == "above_threshold"
    assert expensive_to_attack.minimum_viable_pass
    assert expensive_to_attack.attack_roi < 0


def test_improving_weakness_lowers_attack_roi() -> None:
    static = assess_weak_side(
        {"forehand_topspin": 0.6}, attack_probability=0.6,
        cost_to_exploit=0.3,
    )
    improving = assess_weak_side(
        {"forehand_topspin": 0.6}, attack_probability=0.6,
        cost_to_exploit=0.3, improving=True,
    )
    assert improving.attack_roi < static.attack_roi


# --- Niche classifier ------------------------------------------------------------
def test_niche_classifications() -> None:
    beachhead = classify_niche(
        dominance=0.8, expansion_potential=0.7, execution_proof=0.6,
        valuation_expectation_risk=0.5,
    )
    platform = classify_niche(
        dominance=0.8, expansion_potential=0.7, execution_proof=0.6,
        valuation_expectation_risk=0.2,
    )
    cage = classify_niche(dominance=0.8, expansion_potential=0.2)
    narrative = classify_niche(
        dominance=0.8, expansion_potential=0.2,
        valuation_expectation_risk=0.8,
    )
    fragile = classify_niche(dominance=0.3, concentration_risk=0.8)
    assert beachhead.classification == "beachhead"
    assert platform.classification == "underpriced_expansion_platform"
    assert cage.classification == "profitable_cage"
    assert narrative.classification == "overvalued_niche_narrative"
    assert fragile.classification == "one_product_fragility"
    assert any("good company" in r.lower() or "second act" in r
               for r in cage.rationale)


# --- OAI + blind layers ------------------------------------------------------------
def test_oai_states_and_blind_layers() -> None:
    fresh = assess_adaptation(
        signal_strength=0.8, repricing_observed=0.1, crowding=0.1,
        narrative_saturation=0.1,
    )
    assert fresh.state == "fresh_edge"
    assert fresh.market_awareness_layer == 1  # single blind

    partial = assess_adaptation(
        signal_strength=0.7, repricing_observed=0.5, crowding=0.5,
        narrative_saturation=0.4,
    )
    assert partial.state == "partially_recognized"
    assert partial.market_awareness_layer == 2  # double blind

    triple = assess_adaptation(
        signal_strength=0.5, repricing_observed=0.8, crowding=0.9,
        narrative_saturation=0.9, second_order_node_unpriced=True,
    )
    assert triple.state in ("crowded_edge", "exhausted_edge")
    assert triple.market_awareness_layer == 3  # bait the variation

    dead = assess_adaptation(
        signal_strength=0.4, repricing_observed=0.9, crowding=0.9,
        narrative_saturation=0.9,
    )
    assert dead.state == "exhausted_edge"
    assert dead.market_awareness_layer == 0


def test_anti_consensus_and_edge_decay() -> None:
    anti = assess_adaptation(
        signal_strength=0.7, consensus_against=True,
        repricing_observed=0.2, crowding=0.2, narrative_saturation=0.3,
    )
    assert anti.state == "anti_consensus_opportunity"
    decayed = assess_adaptation(
        signal_strength=0.8, recognition_age_days=60,
        edge_half_life_days=30,
    )
    assert decayed.live_edge_fraction == pytest.approx(0.25)


# --- Catalyst + 1 ---------------------------------------------------------------------
def test_catalyst_plus_one_prepositioning_value() -> None:
    setup = model_catalyst_plus_one(
        catalyst="approval decision", first_mover="HEADLINE_CO",
        lagging_node="SUPPLIER_CO", first_reaction_probability=0.8,
        expected_lag_repricing=0.7, current_lag_reaction=0.1,
        false_signal_risk=0.3,
    )
    assert setup.pre_positioning_value > 0.2
    already_moved = model_catalyst_plus_one(
        catalyst="approval decision", first_reaction_probability=0.8,
        expected_lag_repricing=0.7, current_lag_reaction=0.7,
        false_signal_risk=0.3,
    )
    assert already_moved.pre_positioning_value < setup.pre_positioning_value
    assert any("anticipation beats reaction" in r.lower()
               for r in setup.rationale)


# --- Complete game ----------------------------------------------------------------------
def test_complete_game_rewards_breadth_over_one_spike() -> None:
    complete = complete_game_score(
        {"revenue": 0.7, "product": 0.7, "geo": 0.65, "balance": 0.7}
    )
    spike = complete_game_score(
        {"revenue": 0.95, "product": 0.2, "geo": 0.15, "balance": 0.2}
    )
    assert complete["balanced"]
    assert not spike["balanced"]
    assert complete["score"] > spike["score"]
    assert "punish" in spike["note"]


# --- Pipeline integration ----------------------------------------------------------------
def _run(extra: dict | None = None) -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    if extra:
        payload.update(copy.deepcopy(extra))
    return evaluate_candidate_payload(payload)


def test_pipeline_without_opponent_section_self_feeds() -> None:
    # The model feeds itself: no opponent section, yet the engines that
    # already computed crowding/grip/saturation wire one up — with
    # provenance — and the gate runs. The strong payload still passes.
    out = _run()
    opp = out["opponent"]
    assert opp is not None
    assert opp["self_feed"]["auto_derived"] is True
    assert opp["self_feed"]["coverage"] == 1.0
    assert (
        opp["self_feed"]["provenance"]["adaptation.crowding"]
        == "theme_mapper.crowding"
    )
    assert "OPPONENT_SELF_FED" in out["decision"]["reason_codes"]
    assert out["decision"]["gate_results"]["adaptation_gate"] is True
    assert out["decision"]["final_state"] == "active_watch"


def test_self_feed_disabled_restores_passthrough() -> None:
    out = _run({"self_feed": {"enabled": False}})
    assert out["opponent"] is None
    assert "adaptation_gate" not in out["decision"]["gate_results"]


def test_exhausted_edge_caps_investment_state() -> None:
    base = _run()
    out = _run({"opponent": {
        "strengths": {"narrative_momentum": 0.9},
        "crowding": 0.9,
        "adaptation": {"signal_strength": 0.4, "repricing_observed": 0.9,
                       "crowding": 0.9, "narrative_saturation": 0.9},
    }})
    assert out["opponent"]["adaptation"]["state"] == "exhausted_edge"
    assert out["decision"]["gate_results"]["adaptation_gate"] is False
    assert "EDGE_EXHAUSTED" in out["decision"]["reason_codes"]
    assert out["decision"]["final_state"] == "watchlist"
    assert base["decision"]["final_state"] == "active_watch"


def test_fatal_weak_side_caps_state() -> None:
    out = _run({"opponent": {
        "weaknesses": {"customer_concentration": 0.9},
        "attack_probability": 0.8, "cost_to_exploit": 0.1,
        "adaptation": {"signal_strength": 0.8, "repricing_observed": 0.1},
    }})
    assert out["opponent"]["weak_side"]["classification"] == "fatal"
    assert "FATAL_WEAK_SIDE" in out["decision"]["reason_codes"]
    assert out["decision"]["final_state"] == "watchlist"


def test_fresh_edge_with_manageable_weakness_passes_gate() -> None:
    # Caller-judgement path (self-feed disabled): the section is taken
    # as supplied. The self-fed/merged variant of this scenario lives in
    # tests/test_self_feed.py.
    out = _run({"self_feed": {"enabled": False}, "opponent": {
        "strengths": {"supply_chain_position": 0.8},
        "weaknesses": {"geo_concentration": 0.4},
        "attack_probability": 0.3, "cost_to_exploit": 0.7,
        "adaptation": {"signal_strength": 0.8, "repricing_observed": 0.1,
                       "crowding": 0.1, "narrative_saturation": 0.1},
        "niche": {"dominance": 0.7, "expansion_potential": 0.6,
                  "execution_proof": 0.5},
        "capabilities": {"revenue": 0.7, "product": 0.6, "geo": 0.6},
        "catalyst_plus_one": {"catalyst": "capacity expansion",
                              "expected_lag_repricing": 0.6,
                              "current_lag_reaction": 0.1},
    }})
    assert out["decision"]["gate_results"]["adaptation_gate"] is True
    assert out["decision"]["final_state"] == "active_watch"
    opp = out["opponent"]
    assert opp["adaptation"]["market_awareness_layer"] == 1
    assert opp["niche"]["classification"] in (
        "beachhead", "underpriced_expansion_platform",
    )
    assert opp["catalyst_plus_one"]["pre_positioning_value"] > 0


def test_orchestrator_handles_empty_section() -> None:
    report = assess_adaptive_opponent({})
    assert report["weapon_map"]["strongest_weapon"] == "none_established"
    assert report["weak_side"]["minimum_viable_pass"] is True
    assert report["catalyst_plus_one"] is None
    assert report["advisory_status"] == "ADVISORY_ONLY"
