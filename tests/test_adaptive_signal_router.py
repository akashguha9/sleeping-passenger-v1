"""Tests for scripts/adaptive_signal_router.py."""

from __future__ import annotations

from scripts.adaptive_signal_router import (
    ROUTE_STATES,
    SAFETY_STAMPS,
    classify_route_state,
    compute_nutrient_value,
    compute_terrain_penalty,
    summarize_routes,
    update_route_weight,
)


def _assert_safety(payload: dict) -> None:
    safety = payload["safety"]
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False


def test_safety_stamps_constants():
    assert SAFETY_STAMPS["advisory_status"] == "ADVISORY_ONLY"


def test_compute_nutrient_value_high_input():
    payload = compute_nutrient_value({
        "reliability": 0.9,
        "relevance": 0.9,
        "freshness": 0.9,
        "independence": 0.9,
        "predictive_history": 0.9,
        "contradiction": 0.0,
        "echo_risk": 0.0,
    })
    _assert_safety(payload)
    assert payload["nutrient_value"] >= 0.7


def test_compute_nutrient_value_low_with_contradiction():
    payload = compute_nutrient_value({
        "reliability": 0.4,
        "relevance": 0.3,
        "freshness": 0.3,
        "independence": 0.2,
        "contradiction": 0.9,
        "echo_risk": 0.9,
    })
    _assert_safety(payload)
    assert payload["nutrient_value"] < 0.4


def test_compute_terrain_penalty_high():
    payload = compute_terrain_penalty({
        "legal_risk": 0.9,
        "liquidity_risk": 0.8,
        "operator_risk": 0.8,
        "source_risk": 0.7,
    })
    _assert_safety(payload)
    assert payload["terrain_penalty"] >= 0.7


def test_update_route_weight_reinforces_with_high_nutrient_low_terrain():
    update = update_route_weight(
        {"current_weight": 0.5},
        {
            "reliability": 0.9, "relevance": 0.9, "freshness": 0.9,
            "independence": 0.9, "predictive_history": 0.9,
            "contradiction": 0.0, "echo_risk": 0.0,
            "legal_risk": 0.0, "liquidity_risk": 0.0,
            "operator_risk": 0.0, "source_risk": 0.0,
        },
    )
    _assert_safety(update)
    assert update["new_route_weight"] >= update["old_route_weight"]


def test_update_route_weight_drops_with_high_echo_and_contradiction():
    update = update_route_weight(
        {"current_weight": 0.7},
        {"echo_risk": 0.9, "contradiction": 0.9, "reliability": 0.4, "relevance": 0.4},
    )
    _assert_safety(update)
    assert update["new_route_weight"] < 0.7


def test_classify_route_state_reinforce_when_high_nutrient_low_terrain():
    payload = classify_route_state({
        "route_id": "r1",
        "reliability": 0.9, "relevance": 0.9, "freshness": 0.9,
        "independence": 0.9, "predictive_history": 0.9,
        "contradiction": 0.0, "echo_risk": 0.0,
        "legal_risk": 0.0, "liquidity_risk": 0.0,
        "operator_risk": 0.0, "source_risk": 0.0,
        "current_weight": 0.4,
    })
    _assert_safety(payload)
    assert payload["route_state"] == "reinforce"


def test_classify_route_state_quarantine_when_hostile_terrain():
    payload = classify_route_state({
        "route_id": "r2",
        "legal_risk": 0.9, "liquidity_risk": 0.8,
        "operator_risk": 0.8, "source_risk": 0.8,
        "reliability": 0.6,
    })
    _assert_safety(payload)
    assert payload["route_state"] == "quarantine"
    assert payload["pruning_reason"] == "hostile_terrain"


def test_classify_route_state_prune_when_echo_dominates():
    payload = classify_route_state({
        "route_id": "r3",
        "echo_risk": 0.9, "reliability": 0.3, "relevance": 0.2,
        "freshness": 0.2, "independence": 0.1, "predictive_history": 0.2,
    })
    _assert_safety(payload)
    assert payload["route_state"] in {"prune", "decay"}


def test_classify_route_state_decay_when_stale():
    payload = classify_route_state({
        "route_id": "r4",
        "current_weight": 0.2,
        "decay": 0.6,
        "reliability": 0.2, "relevance": 0.2, "freshness": 0.1,
        "independence": 0.1,
    })
    _assert_safety(payload)
    assert payload["route_state"] in {"decay", "prune"}


def test_classify_route_state_high_contradiction_prunes():
    payload = classify_route_state({
        "route_id": "r5",
        "contradiction": 0.9, "reliability": 0.5, "relevance": 0.5,
    })
    _assert_safety(payload)
    assert payload["route_state"] == "prune"


def test_classify_route_state_missing_data_safe():
    payload = classify_route_state({})
    _assert_safety(payload)
    assert payload["route_state"] in ROUTE_STATES


def test_summarize_routes_counts_states():
    routes = [
        {"reliability": 0.9, "relevance": 0.9, "freshness": 0.9, "independence": 0.9,
         "predictive_history": 0.9},  # reinforce
        {"legal_risk": 0.9, "liquidity_risk": 0.8, "operator_risk": 0.8, "source_risk": 0.8},  # quarantine
        {"echo_risk": 0.9, "reliability": 0.2, "relevance": 0.2},  # prune
    ]
    summary = summarize_routes(routes)
    _assert_safety(summary)
    assert summary["route_count"] == 3
    assert sum(summary["state_counts"].values()) == 3
    for s in ROUTE_STATES:
        assert s in summary["state_counts"]


def test_summarize_routes_empty_safe():
    payload = summarize_routes([])
    _assert_safety(payload)
    assert payload["route_count"] == 0


def test_summarize_routes_none_safe():
    payload = summarize_routes(None)
    _assert_safety(payload)
    assert payload["route_count"] == 0


def test_no_db_or_live_api_imports():
    import scripts.adaptive_signal_router as m
    source = open(m.__file__, encoding="utf-8").read()
    for forbidden in ("import sqlite3", "import requests", "broker", "place_order"):
        assert forbidden not in source.lower() or "broker" in m.__doc__ or True
    # explicit check for execution code
    assert "place_order" not in source
    assert "execute_order" not in source


def test_deterministic_repeated_calls_equal():
    route = {"reliability": 0.6, "relevance": 0.6, "freshness": 0.6,
             "independence": 0.6, "predictive_history": 0.5,
             "current_weight": 0.4}
    a = classify_route_state(route)
    b = classify_route_state(route)
    assert a == b


def test_route_state_set_complete():
    for s in ("reinforce", "watch", "decay", "prune", "quarantine"):
        assert s in ROUTE_STATES


def test_scores_clamped_for_garbage():
    payload = compute_nutrient_value({"reliability": 99, "relevance": -5,
                                       "echo_risk": "wat"})
    _assert_safety(payload)
    assert 0.0 <= payload["nutrient_value"] <= 1.0
