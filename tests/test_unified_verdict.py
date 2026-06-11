"""The Stewards' Room: unified verdict, contradiction detection, and
strategy cross-examination — end-to-end proofs.

Doctrine under test: the most conservative engine wins; disagreement is
information (cited, never averaged away); strategy self-report is
cross-examined against the payload's own evidence; low credibility blocks
upgrades but never downgrades; and an operator can no longer act on
whichever engine happens to agree with them.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.unified_verdict import build_unified_verdict
from src.strategy.cross_exam import cross_examine_strategy
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD

# A strategy section that agrees with the physics verdict (clears its
# own gates, lands WATCHLIST-grade like the simulator's active_watch).
AGREEING_STRATEGY: dict = {
    "narrative": "grid capex supercycle",
    "base_quality": 0.7,
    "value_chain_position_score": 0.7,
    "mechanism": {"probability_shock": 0.5, "cash_flow_impact": 0.7,
                  "demand_impact": 0.6},
    "doctrine": {"evidence_source_count": 4, "value_chain_role_known": True,
                 "survival_threshold_crossed": True},
    "predator": {"traits": {"chokepoint_control": 0.8, "switching_costs": 0.7,
                            "flow_capture": 0.7},
                 "defensibility": 0.7},
    "competition": {"raw_performance": 0.6, "era_difficulty": 0.6,
                    "opponent_quality": 0.6, "evidence_confidence": 0.8},
    "node_payoff": {"probability_of_success": 0.65, "upside": 0.8,
                    "downside": 0.25, "food_chain_position": "toll_booth",
                    "pricing_power": 0.7, "dependency_control": 0.7,
                    "edge_half_life_months": 72,
                    "current_edge_strength": 0.7, "defensibility": 0.7,
                    "threshold_crossed": True,
                    "inflection_probability": 0.5, "inflection_impact": 0.6},
    "chess": {"declared_state": "rook", "mobility": 0.5},
    "underground": {"visibility": 0.7},
    "distribution": {"quality_percentile": 82, "fragility_percentile": 25},
    "backhand": {"bull_thesis": "durable toll flows",
                 "evidence_strength": 0.7, "weak_side_improvement": 0.6,
                 "bear_attacks": [
                     {"attack": "regulation", "severity": 0.6,
                      "defence_strength": 0.7,
                      "defence_response": "precedent"},
                 ]},
}


def _run(strategy: dict | None = None, **extra) -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    if strategy is not None:
        payload["strategy"] = copy.deepcopy(strategy)
    payload.update(extra)
    return evaluate_candidate_payload(payload)


BASE = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))


# --- 1. Happy path: agreeing engines, no contradiction, no demotion --------
def test_agreeing_engines_no_hold_no_demotion() -> None:
    out = _run(AGREEING_STRATEGY)
    unified = out["unified_verdict"]
    assert not unified["contradiction_hold"]
    assert unified["contradictions"] == []
    # WATCHLIST (rank 2) vs active_watch (rank 3): gap 1, conservative
    # nudge without a contradiction hold.
    assert unified["final_state"] in ("watchlist", "active_watch")
    assert "strategy" in unified["engines_present"]


# --- 2. Missing data: no strategy section -> identical behavior ------------
def test_missing_strategy_section_is_pure_passthrough() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    unified = out["unified_verdict"]
    assert out["decision"]["final_state"] == BASE["decision"]["final_state"]
    assert unified["final_state"] == unified["state_before_unification"]
    assert out["strategy"] is None
    assert out["strategy_cross_exam"] is None
    assert not unified["contradiction_hold"]


# --- 3. Contradictory engines: detected, cited, conservatively resolved ----
def test_physics_vs_strategy_contradiction_held_and_cited() -> None:
    out = _run({"narrative": "vibes", "mechanism": {"probability_shock": 0.9}})
    unified = out["unified_verdict"]
    assert unified["contradiction_hold"]
    kinds = [c["kind"] for c in unified["contradictions"]]
    assert "physics_vs_strategy" in kinds
    contradiction = unified["contradictions"][0]
    assert "simulator:" in contradiction["left"]
    assert "strategy:" in contradiction["right"]
    # Conservative-wins: the REJECT side prevails.
    assert out["decision"]["final_state"] == "reject"
    assert "CONTRADICTION_HOLD" in out["decision"]["reason_codes"]
    assert "UNIFIED_CONSERVATIVE_CAP" in out["decision"]["reason_codes"]


# --- 4. Adversarial: gamed self-report is cross-examined --------------------
def test_gamed_strategy_inputs_lose_credibility() -> None:
    gamed = {
        "narrative": "story",
        "mechanism": {"probability_shock": 0.95, "cash_flow_impact": 0.9},
        "doctrine": {"evidence_source_count": 9,
                     "value_chain_role_known": True},
        "predator": {"traits": {"hidden_assets": 0.95,
                                "low_visibility": 0.9}},
        "underground": {"visibility": 0.8},
        "backhand": {"bull_thesis": "x", "evidence_strength": 0.95,
                     "bear_attacks": [{"attack": "minor", "severity": 0.2,
                                       "defence_strength": 0.9}]},
    }
    out = _run(gamed)
    exam = out["strategy_cross_exam"]
    checks = [v["check"] for v in exam["violations"]]
    assert "hidden_asset_visibility_conflict" in checks
    assert "shock_overclaim" in checks  # 0.95 claimed vs 0.27 actual delta
    assert exam["credibility_factor"] < 0.5
    assert exam["can_upgrade_unified_verdict"] is False
    assert out["unified_verdict"]["strategy_upgrade_blocked"] is True


def test_evidence_overclaim_caught_when_payload_is_thin() -> None:
    thin = copy.deepcopy(STRONG_PAYLOAD)
    thin["narrative"] = {"mention_count": 1, "origin_count": 1,
                         "independent_origin_count": 1,
                         "source_quality": 0.5,
                         "narrative_velocity": 0.0,
                         "narrative_acceleration": 0.0}
    thin["signals"] = []
    thin["strategy"] = {"backhand": {"bull_thesis": "x",
                                     "evidence_strength": 0.95}}
    exam = cross_examine_strategy(thin)
    assert any(
        v.check == "evidence_strength_overclaim" for v in exam.violations
    )


def test_honest_self_report_keeps_full_credibility() -> None:
    out = _run(AGREEING_STRATEGY)
    exam = out["strategy_cross_exam"]
    assert exam["violations"] == []
    assert exam["credibility_factor"] == 1.0
    assert exam["can_upgrade_unified_verdict"] is True


# --- 5. Asymmetric credibility: blocked upgrade, allowed downgrade ----------
def test_low_credibility_blocks_upgrade_but_not_downgrade() -> None:
    from src.strategy.cross_exam import CrossExamReport, CrossExamViolation

    discredited = CrossExamReport(
        credibility_factor=0.1,
        can_upgrade_unified_verdict=False,
        violations=[CrossExamViolation(
            check="x", severity=0.9, claimed="a", contradicted_by="b",
        )],
        checks_run=4,
    )
    # Strategy says BUY (rank 4) while physics says watchlist (rank 2):
    # the discredited upgrade is ignored.
    blocked = build_unified_verdict(
        simulator_state="watchlist",
        simulator_score_100=40.0,
        strategy_result={"decision": {"decision_class": "BUY",
                                      "final_opportunity_score": 9.0}},
        cross_exam=discredited,
    )
    assert blocked.final_state == "watchlist"
    assert blocked.strategy_upgrade_blocked
    # Same discredited section saying REJECT still downgrades.
    downgraded = build_unified_verdict(
        simulator_state="watchlist",
        simulator_score_100=40.0,
        strategy_result={"decision": {"decision_class": "REJECT",
                                      "final_opportunity_score": 1.0}},
        cross_exam=discredited,
    )
    assert downgraded.final_state == "reject"


# --- 6. Consent vs strategy contradiction -----------------------------------
def test_extractive_revenue_blocks_strategy_buy() -> None:
    verdict = build_unified_verdict(
        simulator_state="buy_candidate",
        simulator_score_100=80.0,
        strategy_result={"decision": {"decision_class": "BUY",
                                      "final_opportunity_score": 9.0}},
        consent_revenue_label="extractive_risk",
    )
    kinds = [c.kind for c in verdict.contradictions]
    assert "consent_vs_strategy" in kinds
    assert verdict.final_state == "watchlist"
    assert verdict.contradiction_hold


def test_failed_crash_gate_blocks_strategy_buy() -> None:
    verdict = build_unified_verdict(
        simulator_state="watchlist",
        simulator_score_100=40.0,
        strategy_result={"decision": {"decision_class": "BUY",
                                      "final_opportunity_score": 9.0}},
        crash_gate_passed=False,
    )
    assert any(c.kind == "crash_vs_strategy" for c in verdict.contradictions)
    assert verdict.final_state == "watchlist"


# --- 7. Interrupt states outrank the stewards --------------------------------
def test_interrupt_states_pass_through_unification() -> None:
    verdict = build_unified_verdict(
        simulator_state="black_flag",
        simulator_score_100=90.0,
        strategy_result={"decision": {"decision_class": "BUY",
                                      "final_opportunity_score": 9.5}},
    )
    assert verdict.final_state == "black_flag"
    assert not verdict.contradiction_hold


# --- 8. Determinism, serializability, telemetry capture ----------------------
def test_unified_pipeline_is_deterministic_and_serializable() -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["strategy"] = copy.deepcopy(AGREEING_STRATEGY)
    first = evaluate_candidate_payload(copy.deepcopy(payload))
    second = evaluate_candidate_payload(copy.deepcopy(payload))
    first["telemetry"].pop("decision_time")
    second["telemetry"].pop("decision_time")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_telemetry_records_post_unification_state() -> None:
    out = _run({"narrative": "vibes",
                "mechanism": {"probability_shock": 0.9}})
    # Replay must see what the operator saw: the unified state.
    assert out["telemetry"]["final_state"] == out["decision"]["final_state"]
    assert out["telemetry"]["final_state"] == "reject"


# --- 9. API contract ----------------------------------------------------------
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


def test_http_evaluate_exposes_unified_verdict(client) -> None:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload["strategy"] = {"narrative": "vibes",
                           "mechanism": {"probability_shock": 0.9}}
    response = client.post("/simulator/evaluate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    unified = body["unified_verdict"]
    assert unified["contradiction_hold"] is True
    assert unified["contradictions"]
    assert body["decision"]["final_state"] == unified["final_state"]
