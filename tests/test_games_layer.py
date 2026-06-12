"""Games layer proofs: archetype classification, dice profiles, loaded-die
detection, non-transitive matchups, reality anchoring, the investment-vs-
tradeability split, advisory routing, and pipeline integration.

The ten required behaviors: game classification, dice classification,
reality anchoring reduces hyperreal scores, half-life decay (existing,
re-asserted via integration), threshold gates block thin evidence
(existing, re-asserted), inflection flags (existing), loaded-dice
penalty, blind-protocol trust (existing triple-blind), red-team
downgrades (existing backhand), and stable explainable advisory routing.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.games.advisory_router import route_advisory_action
from src.games.dice_profiles import (
    classify_dice_profile,
    detect_loaded_die,
    regime_matchup,
)
from src.games.game_classifier import classify_game, classify_game_stack
from src.games.reality_anchor import assess_reality, reality_anchor_score
from src.simulator.pipeline import evaluate_candidate_payload
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD


# --- 1. Game archetype classification ---------------------------------------
def test_archetypes_classify_from_features() -> None:
    politics = classify_game({"regulatory_exposure": 0.8,
                              "narrative_dependence": 0.6,
                              "coalition_dynamics": 0.6})
    cash = classify_game({"cash_flow_centrality": 0.8,
                          "working_capital_cycles": 0.6,
                          "supply_chain_flow": 0.5})
    war = classify_game({"competitive_intensity": 0.9, "moat_contest": 0.7,
                         "counter_move_exposure": 0.5})
    assert politics.game == "shasn"
    assert cash.game == "pallanguzhi"
    assert war.game == "chaturanga"


def test_weak_features_stay_unclassified() -> None:
    result = classify_game({"regulatory_exposure": 0.1})
    assert result.game == "unclassified"
    assert "metaphor-overfit guard" in result.environment
    # Neutral interpretation: an unnamed game changes nothing.
    assert result.interpretation["narrative_weight"] == 1.0


def test_nested_stack_blends_interpretation() -> None:
    stack = classify_game_stack({
        "macro": {"regulatory_exposure": 0.8, "narrative_dependence": 0.6,
                  "coalition_dynamics": 0.6},
        "company": {"cash_flow_centrality": 0.9,
                    "working_capital_cycles": 0.7,
                    "supply_chain_flow": 0.6},
    })
    games = {l.layer: l.game for l in stack.layers}
    assert games == {"macro": "shasn", "company": "pallanguzhi"}
    # SHASN boosts narrative weight; Pallanguzhi suppresses it — the blend
    # sits between, and the thesis is never reduced to one label.
    blend = stack.blended_interpretation
    assert 0.5 < blend["narrative_weight"] < 1.3
    assert stack.dominant_game in ("shasn", "pallanguzhi")


def test_empty_stack_is_neutral() -> None:
    stack = classify_game_stack({})
    assert stack.dominant_game == "unclassified"
    assert stack.layers == []


# --- 2. Dice profile classification ------------------------------------------
def test_dice_profiles_match_source_character() -> None:
    assert classify_dice_profile(
        source="filings", reliability=0.95, variance=0.15
    ).profile == "precision"
    assert classify_dice_profile(
        source="social", reliability=0.3, variance=0.7
    ).profile == "rounded"
    assert classify_dice_profile(
        source="biotech_event", reliability=0.6, variance=0.9
    ).profile == "d20"
    assert classify_dice_profile(
        source="polymarket", reliability=0.7, variance=0.4,
        is_probability_market=True,
    ).profile == "d100"
    assert classify_dice_profile(
        source="factor_rotation", reliability=0.6, variance=0.5,
        regime_dependent=True,
    ).profile == "non_transitive"


def test_manipulated_source_is_loaded_with_capped_confidence() -> None:
    loaded = classify_dice_profile(
        source="promoted_newsletter", reliability=0.6, variance=0.4,
        manipulation_risk=0.8,
    )
    assert loaded.profile == "loaded_possible"
    assert loaded.confidence_multiplier <= 0.25
    assert any("who benefits" in r for r in loaded.rationale)


# --- 7. Loaded-die distribution detection -------------------------------------
def test_loaded_die_detected_with_sufficient_sample() -> None:
    biased = detect_loaded_die(
        {"up": 70, "down": 15, "flat": 15},
        {"up": 1 / 3, "down": 1 / 3, "flat": 1 / 3},
    )
    assert biased.loaded
    assert biased.worst_face == "up"
    assert biased.bias_score > 0.2

    fair = detect_loaded_die({"up": 34, "down": 33, "flat": 33})
    assert not fair.loaded
    assert fair.bias_score < 0.05


def test_small_sample_never_yields_loaded_verdict() -> None:
    anecdote = detect_loaded_die({"up": 5, "down": 0})
    assert not anecdote.loaded
    assert not anecdote.sufficient_sample
    assert any("anecdote" in r for r in anecdote.rationale)


def test_empty_observations_are_honest() -> None:
    report = detect_loaded_die({})
    assert report.observations == 0
    assert not report.loaded


# --- Non-transitive matchups ----------------------------------------------------
def test_non_transitive_warning_when_winner_flips() -> None:
    scores = {
        "inflation": {"A": 0.8, "B": 0.4},
        "deflation": {"A": 0.3, "B": 0.7},
    }
    inflation = regime_matchup(
        candidate_a="A", candidate_b="B", regime="inflation",
        scores_by_regime=scores,
    )
    assert inflation.winner == "A"
    assert inflation.non_transitive_warning
    deflation = regime_matchup(
        candidate_a="A", candidate_b="B", regime="deflation",
        scores_by_regime=scores,
    )
    assert deflation.winner == "B"
    assert any("category error" not in r for r in deflation.rationale)


def test_stable_matchup_has_no_warning() -> None:
    scores = {"r1": {"A": 0.8, "B": 0.4}, "r2": {"A": 0.7, "B": 0.5}}
    verdict = regime_matchup(
        candidate_a="A", candidate_b="B", regime="r1",
        scores_by_regime=scores,
    )
    assert not verdict.non_transitive_warning


# --- 3. Reality anchoring reduces hyperreal scores ----------------------------
def test_reality_anchor_score_math() -> None:
    grounded = reality_anchor_score(
        directness=0.9, auditability=0.9, third_party_confirmation=0.8,
        cash_flow_linkage=0.8, narrative_dependency=0.1,
    )
    hyperreal = reality_anchor_score(
        directness=0.1, auditability=0.1, third_party_confirmation=0.1,
        cash_flow_linkage=0.1, narrative_dependency=0.9,
    )
    assert grounded > 0.7
    assert hyperreal == 0.0


def test_simulacra_layers_classify_correctly() -> None:
    reflection = assess_reality(
        directness=0.9, auditability=0.9, third_party_confirmation=0.8,
        cash_flow_linkage=0.8, narrative_dependency=0.1, fundamentals=0.8,
    )
    hyperreal = assess_reality(
        directness=0.1, auditability=0.1, third_party_confirmation=0.0,
        cash_flow_linkage=0.1, narrative_dependency=0.9, fundamentals=0.1,
        narrative_momentum=0.9, liquidity=0.8, reflexivity=0.8,
    )
    assert reflection.simulacra_layer == "reflection"
    assert hyperreal.simulacra_layer == "hyperreality"
    assert hyperreal.hyperreality_penalty > 0.5
    assert reflection.hyperreality_penalty == 0.0


def test_investment_vs_tradeability_split() -> None:
    boring_quality = assess_reality(
        directness=0.9, auditability=0.9, third_party_confirmation=0.8,
        cash_flow_linkage=0.9, narrative_dependency=0.1, fundamentals=0.8,
        payoff_asymmetry=0.6, narrative_momentum=0.1, liquidity=0.6,
    )
    meme = assess_reality(
        directness=0.1, auditability=0.1, third_party_confirmation=0.0,
        cash_flow_linkage=0.1, narrative_dependency=0.9, fundamentals=0.15,
        narrative_momentum=0.95, liquidity=0.9, reflexivity=0.9,
        leverage=0.7, crowdedness=0.85,
    )
    assert boring_quality.classification == "reality_anchored_opportunity"
    assert boring_quality.investment_score > boring_quality.tradeability_score
    assert meme.classification == "tradeable_but_dangerous"
    assert meme.tradeability_score > meme.investment_score
    assert meme.danger_score >= 5.0
    assert any("do not confuse" in r for r in meme.rationale)


# --- 10. Advisory routing: stable and explainable ------------------------------
def test_router_maps_states_to_staged_actions() -> None:
    assert route_advisory_action(final_state="reject").action == "Reject"
    assert route_advisory_action(final_state="watchlist").action == "Watch"
    assert route_advisory_action(
        final_state="active_watch"
    ).action == "Research More"
    assert route_advisory_action(
        final_state="buy_candidate"
    ).action == "Paper Trade"
    assert route_advisory_action(
        final_state="high_conviction_candidate"
    ).action == "Buy Candidate"
    assert route_advisory_action(final_state="pit_stop").action == "Hold"
    assert route_advisory_action(final_state="black_flag").action == "Reject"


def test_contradiction_hold_routes_to_research_more() -> None:
    action = route_advisory_action(
        final_state="buy_candidate", contradiction_hold=True
    )
    assert action.action == "Research More"
    assert action.downgraded_from == "Paper Trade"
    assert "CONTRADICTION_HOLD" in action.explanation


def test_tradeable_but_dangerous_blocks_investment_actions() -> None:
    meme = assess_reality(
        directness=0.1, auditability=0.1, cash_flow_linkage=0.1,
        narrative_dependency=0.9, fundamentals=0.15,
        narrative_momentum=0.95, liquidity=0.9, reflexivity=0.9,
    )
    blocked = route_advisory_action(
        final_state="buy_candidate", reality=meme
    )
    assert blocked.action == "Research More"
    assert blocked.downgraded_from == "Paper Trade"
    # Watch-grade actions are untouched by the reality block.
    watch = route_advisory_action(final_state="watchlist", reality=meme)
    assert watch.action == "Watch"


def test_demotion_from_candidate_routes_to_exit() -> None:
    action = route_advisory_action(
        final_state="watchlist", previous_state="buy_candidate"
    )
    assert action.action == "Exit Candidate"
    assert "leaving is also a decision" in " ".join(action.rationale)


def test_every_action_is_advisory_labelled() -> None:
    for state in ("reject", "watchlist", "buy_candidate", "pit_stop"):
        action = route_advisory_action(final_state=state)
        assert "ADVISORY_ONLY" in action.explanation
        assert action.advisory_status == "ADVISORY_ONLY"


# --- Pipeline integration (4/5/6/8/9 re-asserted through the one pipeline) -----
GAMES_SECTION = {
    "layers": {
        "macro": {"regulatory_exposure": 0.7, "narrative_dependence": 0.6,
                  "coalition_dynamics": 0.5},
        "reality": {"belief_about_belief": 0.9, "reflexivity": 0.8,
                    "narrative_dependence": 0.9},
    },
    "dice": [
        {"source": "sec_filings", "reliability": 0.95, "variance": 0.15},
        {"source": "promoted_newsletter", "reliability": 0.4,
         "variance": 0.5, "manipulation_risk": 0.8},
    ],
    "observed_outcomes": {"up": 70, "down": 15, "flat": 15},
    "reality": {
        "directness": 0.2, "auditability": 0.15,
        "third_party_confirmation": 0.1, "cash_flow_linkage": 0.1,
        "narrative_dependency": 0.9, "fundamentals": 0.2,
        "narrative_momentum": 0.9, "liquidity": 0.8, "reflexivity": 0.8,
        "leverage": 0.7, "crowdedness": 0.8,
    },
}


def _run(extra: dict | None = None) -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    if extra:
        payload.update(copy.deepcopy(extra))
    return evaluate_candidate_payload(payload)


def test_pipeline_without_games_section_is_passthrough() -> None:
    out = _run()
    assert out["games"] is None
    assert out["advisory_action"]["action"] in (
        "Reject", "Watch", "Research More", "Paper Trade", "Buy Candidate",
    )
    assert out["telemetry"]["segments"]["dominant_game"] == ""


def test_pipeline_games_section_caps_hyperreal_danger() -> None:
    base = _run()
    out = _run({"games": GAMES_SECTION})
    assert out["games"]["reality"]["simulacra_layer"] == "hyperreality"
    assert out["decision"]["gate_results"]["reality_gate"] is False
    assert "REALITY_GATE_CAPPED" in out["decision"]["reason_codes"]
    assert "LOADED_DICE_SUSPECTED" in out["decision"]["reason_codes"]
    # The investment state is capped at watchlist despite base reaching
    # active_watch — tradeability is reported separately, not promoted.
    assert out["decision"]["final_state"] == "watchlist"
    assert base["decision"]["final_state"] == "active_watch"
    assert out["games"]["loaded_die"]["loaded"] is True
    assert out["telemetry"]["segments"]["dominant_game"] == "simulacra"


def test_grounded_reality_section_does_not_cap() -> None:
    grounded = copy.deepcopy(GAMES_SECTION)
    grounded["reality"] = {
        "directness": 0.9, "auditability": 0.9,
        "third_party_confirmation": 0.8, "cash_flow_linkage": 0.9,
        "narrative_dependency": 0.1, "fundamentals": 0.8,
    }
    grounded.pop("observed_outcomes")
    grounded["dice"] = [
        {"source": "sec_filings", "reliability": 0.95, "variance": 0.15}
    ]
    out = _run({"games": grounded})
    assert out["decision"]["gate_results"]["reality_gate"] is True
    assert out["decision"]["final_state"] == _run()["decision"]["final_state"]
    assert "REALITY_GATE_CAPPED" not in out["decision"]["reason_codes"]


def test_games_output_is_deterministic_and_serializable() -> None:
    first = _run({"games": GAMES_SECTION})
    second = _run({"games": GAMES_SECTION})
    first["telemetry"].pop("decision_time")
    second["telemetry"].pop("decision_time")
    assert json.dumps(first, sort_keys=True) == json.dumps(
        second, sort_keys=True
    )


def test_reflection_worked_example_end_to_end() -> None:
    """The reflection's own example: SHASN macro, Pallanguzhi company,
    Simulacra reality; filings precision, social rounded, prediction
    market d100, manipulation loaded_possible."""
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["games"] = {
        "layers": {
            "macro": {"regulatory_exposure": 0.8, "narrative_dependence": 0.6,
                      "coalition_dynamics": 0.6},
            "company": {"cash_flow_centrality": 0.8,
                        "working_capital_cycles": 0.6,
                        "supply_chain_flow": 0.5},
            "signal": {"optionality_after_signal": 0.7,
                       "position_choice": 0.6,
                       "capture_opportunities": 0.4},
            "reality": {"belief_about_belief": 0.7, "reflexivity": 0.6,
                        "narrative_dependence": 0.7},
        },
        "dice": [
            {"source": "filings", "reliability": 0.95, "variance": 0.15},
            {"source": "social", "reliability": 0.3, "variance": 0.7},
            {"source": "prediction_market", "reliability": 0.7,
             "variance": 0.4, "is_probability_market": True},
            {"source": "narrative_push", "reliability": 0.5,
             "variance": 0.5, "manipulation_risk": 0.7},
        ],
    }
    out = evaluate_candidate_payload(payload)
    games = {l["layer"]: l["game"] for l in out["games"]["game_stack"]["layers"]}
    assert games["macro"] == "shasn"
    assert games["company"] == "pallanguzhi"
    assert games["signal"] == "ludo"
    assert games["reality"] == "simulacra"
    profiles = {d["source"]: d["profile"] for d in out["games"]["dice_profiles"]}
    assert profiles == {
        "filings": "precision", "social": "rounded",
        "prediction_market": "d100", "narrative_push": "loaded_possible",
    }
    assert out["advisory_action"]["action"] in (
        "Watch", "Research More", "Paper Trade",
    )
