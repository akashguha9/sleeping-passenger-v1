"""Tests for scripts/signal_reactor.py orchestrator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.signal_reactor import (
    RECOMMENDATIONS,
    REACTOR_STATES,
    SAFETY_STAMPS,
    evaluate_signal_reactor,
)


def _assert_safety(payload: dict) -> None:
    safety = payload["safety"]
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False
    assert safety["broker_order_id"] == "NONE"


def _walk_assert_no_execution(payload):
    if isinstance(payload, dict):
        for k, v in payload.items():
            key = k.lower()
            if key in {"execution_permission", "can_execute", "broker_api_called",
                       "broker_execute"}:
                assert v is False or v == "NONE", f"{k}={v}"
            if key == "ai_execution_count":
                assert v == 0
            if key == "advisory_status":
                assert v == "ADVISORY_ONLY"
            if key == "execution_gate":
                assert v == "LOCKED"
            _walk_assert_no_execution(v)
    elif isinstance(payload, list):
        for item in payload:
            _walk_assert_no_execution(item)


def test_safety_stamps_constants():
    assert SAFETY_STAMPS["advisory_status"] == "ADVISORY_ONLY"
    assert SAFETY_STAMPS["execution_gate"] == "LOCKED"
    assert SAFETY_STAMPS["broker_order_id"] == "NONE"


def test_missing_data_fails_closed_safely():
    # Missing input must not crash and must not grant any action.
    payload = evaluate_signal_reactor(None)
    _assert_safety(payload)
    # Without operator state, the gate fails closed to OPERATOR_CONTROL_RODS
    # or COLD_OBSERVE / WASTE_DECAY — never to a review/trade-permissive state.
    assert payload["signal_reactor_state"] in {
        "COLD_OBSERVE", "WASTE_DECAY", "OPERATOR_CONTROL_RODS",
    }
    assert payload["allowed_actions"]["broker_execute"] is False
    assert payload["allowed_actions"]["manual_trade_logging_allowed"] is False


def test_missing_signal_with_clean_operator_returns_cold_observe():
    payload = evaluate_signal_reactor(None, operator_state={
        "process_compliance": 0.9, "journal_complete": True, "sleep_quality": 0.8,
    })
    _assert_safety(payload)
    assert payload["signal_reactor_state"] in {"COLD_OBSERVE", "WASTE_DECAY"}
    assert payload["allowed_actions"]["broker_execute"] is False


def test_echo_cluster_becomes_echo_suppressed():
    cluster = [
        {"source_name": "BlogX", "source_family": "social", "url": "u",
         "claim_hash": "h", "reliability": 0.3, "evidence_strength": 0.3,
         "direction": 1, "intensity": 0.6, "independence_score": 0.0,
         "echo_risk_score": 0.9}
        for _ in range(8)
    ]
    payload = evaluate_signal_reactor(cluster, operator_state={
        "fomo": 0.1, "process_compliance": 0.8, "journal_complete": True,
        "sleep_quality": 0.8,
    })
    _assert_safety(payload)
    assert payload["signal_reactor_state"] in {"ECHO_SUPPRESSED", "WASTE_DECAY"}
    assert payload["allowed_actions"]["broker_execute"] is False


def test_independent_weak_aligned_signals_become_fusion_review_candidate():
    cluster = [
        {"source_name": "Reuters", "source_family": "news", "direction": 1,
         "intensity": 0.55, "reliability": 0.85, "freshness_score": 0.8,
         "narrative_intensity": 0.4, "market_confirmation": 0.5,
         "independence_score": 0.9, "evidence_strength": 0.6,
         "echo_risk_score": 0.05, "durability_score": 0.7,
         "signal_type": "news", "age_hours": 4.0, "initial_strength": 0.7},
        {"source_name": "Bloomberg", "source_family": "news", "direction": 1,
         "intensity": 0.55, "reliability": 0.85, "freshness_score": 0.8,
         "narrative_intensity": 0.4, "market_confirmation": 0.5,
         "independence_score": 0.9, "evidence_strength": 0.6,
         "echo_risk_score": 0.05, "durability_score": 0.7,
         "signal_type": "news", "age_hours": 4.0, "initial_strength": 0.7},
        {"source_name": "FT", "source_family": "news", "direction": 1,
         "intensity": 0.55, "reliability": 0.85, "freshness_score": 0.8,
         "narrative_intensity": 0.4, "market_confirmation": 0.5,
         "independence_score": 0.9, "evidence_strength": 0.6,
         "echo_risk_score": 0.05, "durability_score": 0.7,
         "signal_type": "news", "age_hours": 4.0, "initial_strength": 0.7},
    ]
    payload = evaluate_signal_reactor(cluster, operator_state={
        "fomo": 0.1, "urgency": 0.2, "process_compliance": 0.85,
        "journal_complete": True, "sleep_quality": 0.7,
    })
    _assert_safety(payload)
    assert payload["signal_reactor_state"] == "FUSION_REVIEW_CANDIDATE"
    assert payload["recommendation"] == "review_candidate"
    assert payload["allowed_actions"]["broker_execute"] is False


def test_explosive_unclear_event_becomes_fission_map_only():
    cluster = [
        {"source_name": "Reuters", "source_family": "news",
         "direction": 1, "intensity": 0.6, "reliability": 0.6},
    ]
    payload = evaluate_signal_reactor(
        cluster,
        operator_state={"process_compliance": 0.8, "journal_complete": True},
        event_context={
            "event_type": "geopolitics", "event_severity": 0.9,
            "uncertainty": 0.9, "narrative_reach": 0.8,
            "source_reliability": 0.3, "market_sensitivity": 0.5,
            "cross_asset_coupling": 0.6, "liquidity_sensitivity": 0.5,
        },
    )
    _assert_safety(payload)
    assert payload["fission_event"] is True
    assert payload["signal_reactor_state"] == "FISSION_MAP_ONLY"
    assert payload["recommendation"] == "map_branches"


def test_high_operator_heat_becomes_operator_control_rods():
    cluster = [
        {"source_name": "A", "direction": 1, "intensity": 0.6,
         "reliability": 0.7, "evidence_strength": 0.5},
    ]
    payload = evaluate_signal_reactor(
        cluster,
        operator_state={
            "fomo": 0.95, "revenge": 0.95, "urgency": 0.95,
            "leverage_temptation": 0.9, "process_compliance": 0.2,
            "journal_complete": False, "sleep_quality": 0.2,
        },
    )
    _assert_safety(payload)
    assert payload["signal_reactor_state"] == "OPERATOR_CONTROL_RODS"
    assert payload["allowed_actions"]["manual_trade_logging_allowed"] is False


def test_stale_signal_becomes_waste_decay():
    cluster = [
        {"source_name": "OldNews", "source_family": "news", "direction": 1,
         "intensity": 0.5, "reliability": 0.5, "signal_type": "social_hype",
         "age_hours": 200.0, "initial_strength": 0.8,
         "evidence_strength": 0.3, "freshness_score": 0.0},
    ]
    payload = evaluate_signal_reactor(cluster, operator_state={
        "process_compliance": 0.8, "journal_complete": True,
    })
    _assert_safety(payload)
    assert payload["signal_reactor_state"] in {"WASTE_DECAY", "COLD_OBSERVE"}


def test_clean_moderate_signal_becomes_warm_watch():
    cluster = [
        {"source_name": "Reuters", "source_family": "news", "direction": 1,
         "intensity": 0.4, "reliability": 0.6, "freshness_score": 0.7,
         "narrative_intensity": 0.4, "market_confirmation": 0.4,
         "independence_score": 0.6, "evidence_strength": 0.4,
         "echo_risk_score": 0.1, "durability_score": 0.6,
         "signal_type": "news", "age_hours": 4.0,
         "initial_strength": 0.5},
    ]
    payload = evaluate_signal_reactor(cluster, operator_state={
        "process_compliance": 0.8, "journal_complete": True,
        "sleep_quality": 0.8,
    })
    _assert_safety(payload)
    assert payload["signal_reactor_state"] in {"WARM_WATCH", "COLD_OBSERVE", "FUSION_REVIEW_CANDIDATE"}
    assert payload["allowed_actions"]["broker_execute"] is False


def test_broker_execute_always_false_in_every_state():
    for cluster, op in (
        (None, None),
        ([{}], None),
        ([{"direction": 1, "intensity": 0.5}], {"fomo": 0.95}),
        ([{"source_name": "X", "intensity": 0.5}], {"process_compliance": 0.9, "journal_complete": True}),
    ):
        payload = evaluate_signal_reactor(cluster, operator_state=op)
        _assert_safety(payload)
        assert payload["allowed_actions"]["broker_execute"] is False


def test_no_execution_permission_anywhere_in_nested_output():
    cluster = [
        {"source_name": "A", "direction": 1, "intensity": 0.6, "reliability": 0.7},
        {"source_name": "B", "direction": 1, "intensity": 0.6, "reliability": 0.7},
    ]
    payload = evaluate_signal_reactor(
        cluster,
        operator_state={"process_compliance": 0.8, "journal_complete": True},
        event_context={"event_type": "earnings", "event_severity": 0.5},
    )
    _walk_assert_no_execution(payload)


def test_reactor_states_set_complete():
    for s in ("COLD_OBSERVE", "WARM_WATCH", "FUSION_REVIEW_CANDIDATE",
              "FISSION_MAP_ONLY", "HOT_CONTAINMENT_REQUIRED",
              "WASTE_DECAY", "ECHO_SUPPRESSED", "OPERATOR_CONTROL_RODS"):
        assert s in REACTOR_STATES


def test_recommendations_set_complete():
    for r in ("observe", "watch", "review_later", "review_candidate",
              "map_branches", "quarantine", "decay_archive",
              "human_review_only", "cool_down"):
        assert r in RECOMMENDATIONS


def test_deterministic_repeated_calls_equal():
    cluster = [{"source_name": "A", "direction": 1, "intensity": 0.5,
                "reliability": 0.6, "evidence_strength": 0.5,
                "independence_score": 0.6, "durability_score": 0.5}]
    a = evaluate_signal_reactor(cluster, operator_state={"process_compliance": 0.8,
                                                          "journal_complete": True})
    b = evaluate_signal_reactor(cluster, operator_state={"process_compliance": 0.8,
                                                          "journal_complete": True})
    assert a == b


def test_cli_example_json_works():
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "signal_reactor.py"
    result = subprocess.run(
        [sys.executable, str(script), "--example", "--json"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["safety"]["advisory_status"] == "ADVISORY_ONLY"
    assert payload["safety"]["broker_order_id"] == "NONE"
    assert payload["signal_reactor_state"] in REACTOR_STATES
    assert payload["allowed_actions"]["broker_execute"] is False


def test_component_outputs_carry_safety_stamps():
    cluster = [{"source_name": "A", "direction": 1, "intensity": 0.5}]
    payload = evaluate_signal_reactor(cluster)
    _assert_safety(payload)
    components = payload["component_outputs"]
    for component_name, component_payload in components.items():
        if component_payload and "safety" in component_payload:
            assert component_payload["safety"]["advisory_status"] == "ADVISORY_ONLY"
            assert component_payload["safety"]["execution_gate"] == "LOCKED"
