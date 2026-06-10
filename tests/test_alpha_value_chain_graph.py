"""Value-chain graph invariants and plumbing graph relationships."""

from __future__ import annotations

from src.alpha.plumbing_case_study import REQUIRED_NODE_NAMES
from src.alpha.value_chain_graph import (
    ValueChainGraphNode,
    build_plumbing_value_chain_graph,
    build_value_chain_graph,
    graph_node_attractiveness,
)


def _graph_index() -> dict[str, dict]:
    graph = build_plumbing_value_chain_graph()
    return {row["node_id"]: row for row in graph["nodes"]}


def test_attractiveness_bounded_and_collapses_on_dead_factor() -> None:
    node = ValueChainGraphNode(node_id="x", name="x")
    assert 0.0 <= graph_node_attractiveness(node) <= 100.0
    dead = ValueChainGraphNode(node_id="d", name="d", urgency_score=0.0)
    assert graph_node_attractiveness(dead) == 0.0


def test_failure_cost_and_replacement_cycle_lift_attractiveness() -> None:
    low = ValueChainGraphNode(
        node_id="low", name="low", failure_cost_score=10.0, replacement_cycle_score=10.0
    )
    high = ValueChainGraphNode(
        node_id="high", name="high", failure_cost_score=90.0, replacement_cycle_score=90.0
    )
    assert graph_node_attractiveness(high) > graph_node_attractiveness(low)


def test_substitution_risk_reduces_attractiveness() -> None:
    safe = ValueChainGraphNode(node_id="s", name="s", substitution_risk=0.0)
    risky = ValueChainGraphNode(node_id="r", name="r", substitution_risk=100.0)
    assert graph_node_attractiveness(risky) < graph_node_attractiveness(safe)


def test_dangling_edges_are_detected() -> None:
    graph = build_value_chain_graph(
        "test",
        [ValueChainGraphNode(node_id="a", name="a", children=["ghost"])],
    )
    assert not graph["graph_valid"]
    assert graph["dangling_edges"] == ["a.children -> ghost"]


def test_plumbing_graph_has_all_required_nodes_and_is_valid() -> None:
    graph = build_plumbing_value_chain_graph()
    node_ids = {row["node_id"] for row in graph["nodes"]}
    assert set(REQUIRED_NODE_NAMES) <= node_ids
    assert graph["graph_valid"]
    assert graph["edge_count"] > 0


def test_pipes_connect_to_fittings_and_valves() -> None:
    nodes = _graph_index()
    assert "fittings" in nodes["pipes"]["children"]
    assert "valves" in nodes["pipes"]["children"]


def test_valves_carry_control_safety_role_and_water_meter_link() -> None:
    nodes = _graph_index()
    assert "control" in nodes["valves"]["role"] or "safety" in nodes["valves"]["role"]
    assert "water_meters" in nodes["valves"]["children"]


def test_faucets_are_interface_layer() -> None:
    nodes = _graph_index()
    assert nodes["faucets"]["position"] == "interface"
    assert "sinks_showers_toilets" in nodes["faucets"]["children"]


def test_sealants_connect_to_emergency_repair() -> None:
    nodes = _graph_index()
    assert "emergency" in nodes["fixing_tape_sealants"]["role"]
    assert "plumbers_contractors" in nodes["fixing_tape_sealants"]["children"]


def test_tools_connect_to_plumbers() -> None:
    nodes = _graph_index()
    assert "plumbers_contractors" in nodes["wrenches_tools"]["children"]
    assert "wrenches_tools" in nodes["plumbers_contractors"]["parents"]


def test_leak_sensors_are_prevention_data_layer() -> None:
    nodes = _graph_index()
    assert nodes["smart_leak_sensors"]["position"] == "data_layer"
    assert "insurance_water_damage_prevention" in nodes["smart_leak_sensors"]["children"]


def test_insurance_is_risk_transfer_monetizing_failure_cost() -> None:
    nodes = _graph_index()
    insurance = nodes["insurance_water_damage_prevention"]
    assert insurance["position"] == "risk_transfer"
    assert insurance["failure_cost_score"] >= 90.0
    assert "plumbers_contractors" in insurance["captures_value_from"]


def test_top_nodes_explained_by_urgency_failure_cost_pricing() -> None:
    graph = build_plumbing_value_chain_graph()
    top = graph["nodes"][0]
    assert top["node_id"] == "plumbers_contractors"
    assert top["urgency_score"] >= 90.0
    assert top["failure_cost_score"] >= 85.0
    assert top["pricing_power_score"] >= 75.0


def test_bottom_nodes_explained_by_commoditization_and_input_risk() -> None:
    graph = build_plumbing_value_chain_graph()
    bottom = graph["nodes"][-1]
    assert bottom["node_id"] in ("raw_materials", "pipes")
    assert bottom["commoditization_risk"] >= 80.0
    assert bottom["input_cost_risk"] >= 60.0


def test_graph_nodes_ranked_descending_and_bounded() -> None:
    graph = build_plumbing_value_chain_graph()
    scores = [row["node_attractiveness"] for row in graph["nodes"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= score <= 100.0 for score in scores)
