"""Plumbing case study v3: full-stack pipeline demonstration."""

from __future__ import annotations

import json

from src.alpha.plumbing_case_study import (
    REQUIRED_NODE_NAMES,
    build_plumbing_case_study_v3,
)

_REQUIRED_PROFILES = ("plumbers_contractors", "valves", "smart_leak_sensors")
_PROFILE_FIELDS = (
    "casino_score",
    "food_chain_score",
    "residual_utility_class",
    "embedded_proof_class",
    "node_attractiveness",
    "triangulation_class",
    "trap_flags",
    "why_not_higher",
    "why_not_lower",
    "advisory_verdict",
    "advisory_container",
)


def test_v3_keeps_v1_surface_and_adds_stack() -> None:
    case_study = build_plumbing_case_study_v3()
    assert case_study["version"] == "v3"
    node_names = {row["name"] for row in case_study["value_chain"]["nodes"]}
    assert set(REQUIRED_NODE_NAMES) <= node_names
    for key in (
        "narrative_snapshot",
        "prediction_market_stub",
        "filing_excerpt_parse",
        "calibration_state",
        "node_profiles",
        "autopsy",
    ):
        assert key in case_study


def test_three_required_node_profiles_with_all_fields() -> None:
    profiles = build_plumbing_case_study_v3()["node_profiles"]
    for node_id in _REQUIRED_PROFILES:
        assert node_id in profiles
        for field in _PROFILE_FIELDS:
            assert field in profiles[node_id], (node_id, field)


def test_profile_logic_matches_framework_expectations() -> None:
    profiles = build_plumbing_case_study_v3()["node_profiles"]
    plumbers = profiles["plumbers_contractors"]
    sensors = profiles["smart_leak_sensors"]
    valves = profiles["valves"]
    # Plumbers: urgency/failure-cost reality, minimal casino energy.
    assert plumbers["residual_utility_class"] == "apex_necessity"
    assert plumbers["food_chain_score"] > plumbers["casino_score"]
    # Sensors: stronger narrative/catalyst, weaker proof and economics.
    assert sensors["casino_score"] > plumbers["casino_score"]
    assert sensors["opportunity_score"] < plumbers["opportunity_score"]
    assert sensors["embedded_proof_class"] != "substrate"
    # Valves: bottleneck strength between the two.
    assert valves["residual_utility_class"] == "apex_necessity"


def test_calibration_state_is_honest_in_isolated_environment() -> None:
    state = build_plumbing_case_study_v3()["calibration_state"]
    # Tests run against an isolated journal DB: no fabricated history.
    assert state["calibration_support"] == 0.0
    assert state["usable_records"] == 0


def test_uncalibrated_state_keeps_all_profile_verdicts_research_grade() -> None:
    profiles = build_plumbing_case_study_v3()["node_profiles"]
    for profile in profiles.values():
        assert profile["advisory_verdict"] in (
            "ignore",
            "watchlist",
            "deep_research",
            "avoid_trap",
            "event_trade_only",
        )


def test_autopsy_attached_and_advisory() -> None:
    autopsy = build_plumbing_case_study_v3()["autopsy"]
    assert autopsy["value_chain_node"] == "plumbers_contractors"
    assert autopsy["next_evidence_to_collect"]
    assert "Advisory-only" in autopsy["disclaimer"]


def test_v3_is_json_safe_and_free_of_execution_language() -> None:
    case_study = build_plumbing_case_study_v3()
    text = json.dumps(case_study).lower()
    for forbidden in ("guaranteed return", "place order", "broker api", "buy now"):
        assert forbidden not in text


def test_v3_deterministic_under_isolated_journal() -> None:
    first = json.dumps(build_plumbing_case_study_v3(), sort_keys=True)
    second = json.dumps(build_plumbing_case_study_v3(), sort_keys=True)
    assert first == second
