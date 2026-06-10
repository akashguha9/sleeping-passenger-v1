"""The Plumbing Alpha Case Study — deterministic output invariants."""

from __future__ import annotations

import json

from src.alpha import ADVISORY_DISCLAIMER
from src.alpha.plumbing_case_study import (
    REQUIRED_NODE_NAMES,
    build_plumbing_case_study,
)


def test_case_study_is_deterministic() -> None:
    first = json.dumps(build_plumbing_case_study(), sort_keys=True)
    second = json.dumps(build_plumbing_case_study(), sort_keys=True)
    assert first == second


def test_all_required_nodes_present() -> None:
    case_study = build_plumbing_case_study()
    node_names = {row["name"] for row in case_study["value_chain"]["nodes"]}
    assert set(REQUIRED_NODE_NAMES) <= node_names
    assert len(REQUIRED_NODE_NAMES) == 13


def test_plumbing_is_food_chain_heavy() -> None:
    case_study = build_plumbing_case_study()
    layer = case_study["casino_food_chain"]
    assert layer["classification"] == "food_chain_heavy"
    assert layer["food_chain_score"] > layer["casino_score"]


def test_half_life_is_civilizational() -> None:
    case_study = build_plumbing_case_study()
    assert case_study["half_life"]["signal_type"] == "human_necessity"
    assert case_study["half_life"]["half_life_days"] > 3650


def test_residual_utility_is_high_with_positive_alpha_proxy() -> None:
    residual = build_plumbing_case_study()["residual_utility"]
    assert residual["residual_utility_score"] > 60.0
    assert residual["residual_alpha_proxy"] > 0


def test_embedded_proof_classifies_substrate() -> None:
    proof = build_plumbing_case_study()["embedded_proof"]
    assert proof["classification"] == "substrate"


def test_urgency_nodes_outrank_commodity_nodes() -> None:
    case_study = build_plumbing_case_study()
    scores = {
        row["name"]: row["node_attractiveness"]
        for row in case_study["value_chain"]["nodes"]
    }
    # Labour scarcity / urgency pricing beats commodity feedstock.
    assert scores["plumbers_contractors"] > scores["raw_materials"]
    assert scores["distributors_hardware_stores"] > scores["pipes"]


def test_every_node_has_an_advisory_verdict_and_note() -> None:
    case_study = build_plumbing_case_study()
    verdicts = {row["node"]: row for row in case_study["advisory_verdicts_by_node"]}
    for name in REQUIRED_NODE_NAMES:
        assert name in verdicts
        assert verdicts[name]["recommended_container"]
        assert verdicts[name]["conceptual_note"]


def test_opportunity_score_bounded_with_verdict() -> None:
    opportunity = build_plumbing_case_study()["opportunity_score"]
    assert 0.0 <= opportunity["opportunity_score"] <= 100.0
    assert opportunity["advisory_verdict"]


def test_disclaimer_and_no_guarantee_language() -> None:
    case_study = build_plumbing_case_study()
    assert case_study["disclaimer"] == ADVISORY_DISCLAIMER
    text = json.dumps(case_study).lower()
    for forbidden in ("guaranteed return", "place order", "broker api", "auto-trade"):
        assert forbidden not in text


def test_case_study_is_json_serializable() -> None:
    assert json.loads(json.dumps(build_plumbing_case_study()))
