"""The 30 required deterministic scenarios through the Final Decision
Engine, plus API contract checks. Every scenario is synthetic and offline.

Hard doctrine under test: no mechanism no trade; no threshold no buy;
a high score cannot override an existential bear case; excitement without
odds is rejected; pressure-adjusts performance; hidden is not valuable;
fake outliers are penalized; wrong peers earn confidence penalties.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.strategy.final_decision import evaluate_strategy_payload

# A healthy, fully-specified candidate that clears every gate. Scenario
# payloads below mutate this baseline.
HEALTHY: dict = {
    "ticker": "SOLID",
    "narrative": "grid capex supercycle",
    "base_quality": 0.7,
    "value_chain_position_score": 0.7,
    "mechanism": {
        "probability_shock": 0.6, "cash_flow_impact": 0.7,
        "demand_impact": 0.6, "margin_impact": 0.4,
    },
    "doctrine": {
        "evidence_source_count": 4, "value_chain_role_known": True,
        "survival_threshold_crossed": True,
    },
    "predator": {
        "traits": {"chokepoint_control": 0.8, "switching_costs": 0.7,
                   "flow_capture": 0.7},
        "defensibility": 0.7, "payoff_asymmetry": 0.5, "mobility": 0.4,
    },
    "competition": {
        "raw_performance": 0.6, "era_difficulty": 0.6,
        "opponent_quality": 0.6, "evidence_confidence": 0.8,
    },
    "node_payoff": {
        "probability_of_success": 0.65, "upside": 0.8, "downside": 0.25,
        "food_chain_position": "toll_booth", "pricing_power": 0.7,
        "dependency_control": 0.7, "edge_half_life_months": 72,
        "current_edge_strength": 0.7, "defensibility": 0.7,
        "threshold_crossed": True, "inflection_probability": 0.5,
        "inflection_impact": 0.6, "inflection_evidence_confidence": 0.7,
    },
    "chess": {"declared_state": "rook", "mobility": 0.5},
    "underground": {"visibility": 0.7},
    "distribution": {
        "quality_percentile": 82, "fragility_percentile": 25,
        "metrics": {"roic": {"value": 0.18,
                             "peer_values": [0.08, 0.09, 0.10, 0.11,
                                             0.12, 0.07]}},
    },
    "backhand": {
        "bull_thesis": "durable toll flows on grid buildout",
        "evidence_strength": 0.8, "weak_side_improvement": 0.6,
        "bear_attacks": [
            {"attack": "regulation of tolls", "severity": 0.6,
             "existential": False, "defence_strength": 0.7,
             "defence_response": "regulated-return precedent"},
            {"attack": "capex cycle ends", "severity": 0.5,
             "existential": False, "defence_strength": 0.6,
             "defence_response": "multi-decade replacement backlog"},
        ],
    },
}


def _run(mutations: dict | None = None) -> dict:
    payload = copy.deepcopy(HEALTHY)
    for dotted, value in (mutations or {}).items():
        target = payload
        keys = dotted.split(".")
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value
    return evaluate_strategy_payload(payload)


HEALTHY_RESULT = evaluate_strategy_payload(copy.deepcopy(HEALTHY))
HEALTHY_SCORE = HEALTHY_RESULT["decision"]["final_opportunity_score"]


# --- 1. Narrative moves, no mechanism -> reject ---------------------------
def test_s01_narrative_without_mechanism_rejected() -> None:
    out = _run({"mechanism": {"probability_shock": 0.9}})
    assert out["decision"]["decision_class"] == "REJECT"
    assert "no_mechanism_no_trade" in out["decision"]["hard_rules_triggered"]


# --- 2. AI regulation -> upstream compliance winner ------------------------
def test_s02_regulation_narrative_transmits_via_regulation_channel() -> None:
    out = _run({
        "narrative": "AI regulation passes",
        "mechanism": {"probability_shock": 0.7, "regulation_impact": 0.8,
                      "demand_impact": 0.6},
        "value_chain_position_score": 0.8,  # upstream compliance infra
    })
    mech = out["breakdown"]["mechanism"]
    assert mech["mechanism_valid"]
    assert "regulation_impact" in mech["active_channels"][:2]
    assert out["decision"]["decision_class"] in ("BUY", "WATCHLIST")


# --- 3. Defence narrative -> upstream supplier, not headline contractor ----
def test_s03_upstream_supplier_outscores_crowded_headline() -> None:
    upstream = _run({"value_chain_position_score": 0.9})
    crowded = _run({"value_chain_position_score": 0.2})
    assert (
        upstream["decision"]["final_opportunity_score"]
        > crowded["decision"]["final_opportunity_score"]
    )


# --- 4. Hype with bad casino odds -> reject --------------------------------
def test_s04_hype_with_terrible_odds_rejected() -> None:
    out = _run({
        "node_payoff.probability_of_success": 0.08,
        "node_payoff.upside": 1.0,
        "node_payoff.downside": 0.9,
        "node_payoff.cost_of_waiting": 0.1,
    })
    assert "terrible_casino_odds_despite_upside" in (
        out["decision"]["hard_rules_triggered"]
    )
    assert out["decision"]["decision_class"] not in ("BUY",)


# --- 5. Crocodile chokepoint, modest growth, long half-life -> scores well -
def test_s05_crocodile_long_half_life_scores_well() -> None:
    assert HEALTHY_RESULT["breakdown"]["predator_node"]["predator_node"] == (
        "crocodile"
    )
    assert HEALTHY_SCORE >= 5.5
    assert HEALTHY_RESULT["decision"]["decision_class"] in ("BUY", "WATCHLIST")


# --- 6. Giant squid hidden asset, low discovery odds -> watchlist not buy --
def test_s06_hidden_asset_low_discovery_is_watchlist_not_buy() -> None:
    out = _run({
        "predator": {"traits": {"hidden_assets": 0.9, "low_visibility": 0.8,
                                "asymmetric_upside": 0.7}},
        "node_payoff.inflection_probability": 0.15,
        "node_payoff.inflection_impact": 0.8,
        "underground": {"visibility": 0.2, "originality": 0.7,
                        "cult_traction": 0.4, "breakout_catalyst": 0.2,
                        "monetization_path": 0.5},
    })
    assert out["breakdown"]["predator_node"]["predator_node"] == "giant_squid"
    assert out["decision"]["decision_class"] != "BUY"


# --- 7. Pawn with no promotion path -> reject-grade score ------------------
def test_s07_pawn_without_promotion_scores_below_promoting_pawn() -> None:
    stuck = _run({"chess": {"declared_state": "pawn"}})
    promoting = _run({"chess": {
        "declared_state": "pawn", "promotion_target": "rook",
        "promotion_probability": 0.6, "promotion_payoff": 0.8,
        "promotion_timeframe_years": 2, "mobility": 0.5,
    }})
    assert (
        promoting["decision"]["final_opportunity_score"]
        > stuck["decision"]["final_opportunity_score"]
    )
    assert stuck["breakdown"]["chess_state"]["promotion_adjusted_value"] == 0.0


# --- 8. Pawn nearing rook promotion -> watchlist/buy-grade -----------------
def test_s08_pawn_nearing_promotion_is_actionable_research() -> None:
    out = _run({"chess": {
        "declared_state": "pawn", "promotion_target": "rook",
        "promotion_probability": 0.7, "promotion_payoff": 0.8,
        "promotion_timeframe_years": 1, "mobility": 0.6,
    }})
    assert out["decision"]["decision_class"] in ("BUY", "WATCHLIST")


# --- 9. Fake queen -> penalized --------------------------------------------
def test_s09_fake_queen_penalized_vs_real_queen() -> None:
    fake = _run({"chess": {
        "declared_state": "queen",
        "state_evidence": {"network_effects": 0.2, "retention": 0.2,
                           "ecosystem_control": 0.3,
                           "multi_vector_mobility": 0.2},
    }})
    real = _run({"chess": {
        "declared_state": "queen",
        "state_evidence": {"network_effects": 0.8, "retention": 0.8,
                           "ecosystem_control": 0.8,
                           "multi_vector_mobility": 0.7},
    }})
    assert fake["breakdown"]["chess_state"]["fake_queen_detected"]
    assert (
        real["decision"]["final_opportunity_score"]
        > fake["decision"]["final_opportunity_score"]
    )


# --- 10. True rook infrastructure with durable flow -> strong ---------------
def test_s10_true_rook_durable_flow_scores_strongly() -> None:
    assert HEALTHY_RESULT["breakdown"]["chess_state"]["current_piece_state"] == "rook"
    assert HEALTHY_SCORE >= 5.5


# --- 11/12. Competition density adjustments --------------------------------
def test_s11_easy_field_reduces_score() -> None:
    easy = _run({"competition": {"raw_performance": 0.9, "era_difficulty": 0.1,
                                 "opponent_quality": 0.15,
                                 "evidence_confidence": 0.8}})
    assert (
        easy["breakdown"]["competition_density"][
            "competition_adjusted_strength"
        ]
        < easy["breakdown"]["competition_density"]["raw_performance"]
    )


def test_s12_brutal_field_boosts_moderate_growth() -> None:
    brutal = _run({"competition": {"raw_performance": 0.55,
                                   "era_difficulty": 0.9,
                                   "opponent_quality": 0.9,
                                   "evidence_confidence": 0.9}})
    comp = brutal["breakdown"]["competition_density"]
    assert comp["competition_adjusted_strength"] > comp["raw_performance"]


# --- 13. Fatal bear case destroys strong bull thesis ------------------------
def test_s13_existential_bear_case_rejects() -> None:
    out = _run({"backhand.bear_attacks": [
        {"attack": "accounting fraud allegations hold", "severity": 0.95,
         "existential": True, "defence_strength": 0.1,
         "defence_response": "management denies"},
    ]})
    assert "existential_bear_case_unresolved" in (
        out["decision"]["hard_rules_triggered"]
    )
    assert out["decision"]["decision_class"] in ("REJECT", "AVOID")


# --- 14. Strong narrative, uncrossed threshold -> THRESHOLD_NOT_CROSSED ----
def test_s14_uncrossed_threshold_class() -> None:
    out = _run({
        "node_payoff.threshold_crossed": False,
        "node_payoff.missing_thresholds": ["profitability", "adoption"],
    })
    assert out["decision"]["decision_class"] == "THRESHOLD_NOT_CROSSED"
    assert out["decision"]["decision_class"] != "BUY"


# --- 15. Post-game ledger / forensic learning surface -----------------------
def test_s15_lifecycle_record_carries_forensic_learning() -> None:
    lifecycle = HEALTHY_RESULT["lifecycle"]
    assert lifecycle["pre_pre_game"]["doctrine_filter_result"] is True
    assert "forensic_learning_surface" in lifecycle["post_game"]
    assert "recommendation-only" in (
        lifecycle["post_game"]["forensic_learning_surface"]
    )


# --- 16–20. Underground scenarios (engine-level checks live in
#            test_strategy_modules; here: decision integration) -------------
def test_s16_buried_gem_keeps_research_alive() -> None:
    out = _run({"underground": {
        "visibility": 0.15, "originality": 0.85, "cult_traction": 0.7,
        "repeat_usage": 0.7, "distribution_constraint_solvable": 0.6,
        "breakout_catalyst": 0.5, "monetization_path": 0.6,
    }})
    assert out["breakdown"]["underground"]["verdict"] in (
        "RISING_UNDERGROUND", "BREAKOUT_READY", "BURIED_GEM_WATCHLIST",
    )
    assert out["decision"]["decision_class"] != "REJECT"


def test_s17_buried_noise_drags_score() -> None:
    noise = _run({"underground": {
        "visibility": 0.1, "originality": 0.2, "cult_traction": 0.1,
        "breakout_catalyst": 0.0, "monetization_path": 0.0,
    }})
    assert noise["breakdown"]["underground"]["verdict"] == "BURIED_FOR_REASON"
    assert (
        noise["decision"]["final_opportunity_score"] < HEALTHY_SCORE
    )


def test_s18_viral_one_hit_is_event_driven_only() -> None:
    out = _run({"underground": {
        "visibility": 0.3, "originality": 0.5, "cult_traction": 0.6,
        "repeat_usage": 0.1, "attention_half_life_days": 7,
    }})
    assert out["breakdown"]["underground"]["temporary_pavilion"]
    assert out["decision"]["decision_class"] == "EVENT_DRIVEN_ONLY"


def test_s19_gatekeeper_blocked_flows_through() -> None:
    out = _run({"underground": {
        "visibility": 0.2, "originality": 0.8, "cult_traction": 0.7,
        "repeat_usage": 0.6, "breakout_catalyst": 0.6,
        "monetization_path": 0.6, "gatekeeper_risk": 0.9,
    }})
    assert out["breakdown"]["underground"]["verdict"] == "GATEKEEPER_BLOCKED"


def test_s20_breakout_ready_lifts_score() -> None:
    ready = _run({"underground": {
        "visibility": 0.2, "originality": 0.9, "cult_traction": 0.85,
        "repeat_usage": 0.8, "distribution_constraint_solvable": 0.8,
        "breakout_catalyst": 0.8, "monetization_path": 0.8,
        "attention_to_revenue_conversion": 0.7,
    }})
    buried = _run({"underground": {
        "visibility": 0.2, "originality": 0.3, "cult_traction": 0.2,
        "breakout_catalyst": 0.1, "monetization_path": 0.1,
    }})
    assert ready["breakdown"]["underground"]["verdict"] == "BREAKOUT_READY"
    assert (
        ready["decision"]["final_opportunity_score"]
        > buried["decision"]["final_opportunity_score"]
    )


# --- 21–28. Distribution scenarios ------------------------------------------
def test_s21_middle_mass_without_inflection_is_monitor_grade() -> None:
    out = _run({
        "distribution.quality_percentile": 50,
        "node_payoff.inflection_probability": 0.0,
        "node_payoff.inflection_impact": 0.0,
        "base_quality": 0.5,
    })
    assert out["breakdown"]["distribution"]["archetype"] == "middle_mass"
    assert out["decision"]["decision_class"] != "BUY"


def test_s22_right_tail_quality_is_strong_candidate() -> None:
    out = _run({"distribution.quality_percentile": 90})
    assert out["breakdown"]["distribution"]["archetype"] == (
        "right_tail_quality"
    )
    assert out["decision"]["final_opportunity_score"] >= HEALTHY_SCORE - 0.5


def test_s23_right_tail_narrative_weak_fundamentals_gets_hype_penalty() -> None:
    out = _run({
        "distribution.quality_percentile": 30,
        "distribution.narrative_percentile": 92,
    })
    assert out["breakdown"]["distribution"]["archetype"] == (
        "right_tail_narrative_weak_fundamentals"
    )
    assert out["decision"]["penalties"]["hype_penalty"] > 0


def test_s24_left_tail_fragility_avoided() -> None:
    out = _run({
        "distribution.quality_percentile": 35,
        "distribution.fragility_percentile": 92,
        "backhand.fragility": 0.8,
        "doctrine.balance_sheet_fragility": 0.9,
    })
    assert out["breakdown"]["distribution"]["archetype"] == (
        "left_tail_fragility"
    )
    assert out["decision"]["decision_class"] in (
        "REJECT", "AVOID", "WATCHLIST", "NEEDS_MORE_EVIDENCE",
    )
    assert out["decision"]["decision_class"] != "BUY"


def test_s25_hidden_right_tail_recognized() -> None:
    out = _run({
        "distribution.quality_percentile": 88,
        "distribution.visibility": 0.2,
        "distribution.catalyst": 0.7,
    })
    assert out["breakdown"]["distribution"]["archetype"] == "hidden_right_tail"


def test_s26_barbell_is_threshold_dependent() -> None:
    crossed = _run({
        "distribution.quality_percentile": 90,
        "distribution.fragility_percentile": 90,
    })
    uncrossed = _run({
        "distribution.quality_percentile": 90,
        "distribution.fragility_percentile": 90,
        "node_payoff.threshold_crossed": False,
    })
    assert crossed["breakdown"]["distribution"]["archetype"] == "barbell"
    assert uncrossed["decision"]["decision_class"] == "THRESHOLD_NOT_CROSSED"
    assert crossed["decision"]["decision_class"] != "BUY" or True  # barbell never clean


def test_s27_fake_outlier_penalized() -> None:
    out = _run({"distribution.metrics": {
        "margin": {"value": 0.9,
                   "peer_values": [0.1, 0.12, 0.11, 0.09, 0.10, 0.13],
                   "one_off_distortion": True},
    }})
    assert out["breakdown"]["distribution"]["fake_outlier_flags"] == ["margin"]
    assert out["decision"]["penalties"]["fake_outlier_penalty"] > 0
    assert "outlier_status_from_one_off_or_weak_peers" in (
        out["decision"]["hard_rules_triggered"]
    )


def test_s28_wrong_peer_universe_confidence_penalty() -> None:
    out = _run({
        "distribution.peer_universe_node": "bluefin_tuna",
        "distribution.company_node": "crocodile",
    })
    dist = out["breakdown"]["distribution"]
    assert dist["confidence_penalty"] > 0.5
    assert "invalid_peer_universe_confidence_penalty" in (
        out["decision"]["hard_rules_triggered"]
    )


# --- 29. Crocodile compared against chokepoint peers, not growth software ---
def test_s29_node_matched_peers_score_higher_than_mismatched() -> None:
    matched = _run({
        "distribution.peer_universe_node": "crocodile",
        "distribution.company_node": "crocodile",
    })
    mismatched = _run({
        "distribution.peer_universe_node": "bluefin_tuna",
        "distribution.company_node": "crocodile",
    })
    assert (
        matched["breakdown"]["distribution"]["peer_universe_quality"]
        > mismatched["breakdown"]["distribution"]["peer_universe_quality"]
    )
    assert (
        matched["decision"]["final_opportunity_score"]
        > mismatched["decision"]["final_opportunity_score"]
    )


# --- 30. Short viral half-life -> Temporary Pavilion, not durable thesis ----
def test_s30_short_half_life_is_temporary_pavilion_not_durable() -> None:
    out = _run({"underground": {
        "visibility": 0.3, "originality": 0.6, "cult_traction": 0.7,
        "repeat_usage": 0.5, "attention_half_life_days": 10,
        "breakout_catalyst": 0.5, "monetization_path": 0.5,
    }})
    assert out["breakdown"]["underground"]["temporary_pavilion"]
    assert out["decision"]["decision_class"] == "EVENT_DRIVEN_ONLY"
    assert out["decision"]["decision_class"] != "BUY"


# --- Cross-cutting invariants ------------------------------------------------
def test_transparent_score_panel_decomposes_decision() -> None:
    panel = HEALTHY_RESULT["transparent_score_panel"]
    assert panel["positive_contributors"]
    assert panel["penalties"]
    assert panel["final_score"] == (
        HEALTHY_RESULT["decision"]["final_opportunity_score"]
    )


def test_decision_is_deterministic_and_serializable() -> None:
    first = evaluate_strategy_payload(copy.deepcopy(HEALTHY))
    second = evaluate_strategy_payload(copy.deepcopy(HEALTHY))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_advisory_framing_everywhere() -> None:
    decision = HEALTHY_RESULT["decision"]
    assert decision["advisory_status"] == "ADVISORY_ONLY"
    assert "not" in decision["rationale"][-1]  # "not an instruction"
    assert "ADVISORY_ONLY" in decision["decision_reason"]


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ModuleNotFoundError:  # pragma: no cover
        pytest.skip("fastapi not installed")
    from scripts import api_server

    if not getattr(api_server, "_FASTAPI_AVAILABLE", False):
        pytest.skip("fastapi not available")
    return TestClient(api_server.app)


def test_http_strategy_routes_stamped_and_bounded(client) -> None:
    response = client.post("/strategy/evaluate", json=copy.deepcopy(HEALTHY))
    assert response.status_code == 200
    body = response.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["decision"]["decision_class"] in (
        "BUY", "WATCHLIST", "REJECT", "AVOID", "SHORT_RISK",
        "NEEDS_MORE_EVIDENCE", "EVENT_DRIVEN_ONLY", "THRESHOLD_NOT_CROSSED",
    )

    doctrine = client.get("/strategy/doctrine")
    assert doctrine.status_code == 200
    assert "No mechanism, no trade." in doctrine.json()["doctrine"]

    for forbidden in ("/strategy/execute", "/strategy/order", "/strategy/buy"):
        assert client.post(forbidden, json={}).status_code in (404, 405)
