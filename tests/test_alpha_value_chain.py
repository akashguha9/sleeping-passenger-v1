"""Module E — Porter value-chain mapper invariants."""

from __future__ import annotations

from src.alpha.value_chain import ValueChainNode, map_value_chain, node_attractiveness


def _node(**overrides) -> ValueChainNode:
    base = dict(
        name="test_node",
        necessity_score=80,
        urgency_score=70,
        pricing_power_score=60,
        repeat_demand_score=75,
        bottleneck_strength=65,
        commoditization_risk=40,
        input_cost_risk=30,
    )
    base.update(overrides)
    return ValueChainNode(**base)


def test_attractiveness_is_bounded() -> None:
    assert 0.0 <= node_attractiveness(_node()) <= 100.0
    maxed = _node(
        necessity_score=100,
        urgency_score=100,
        pricing_power_score=100,
        repeat_demand_score=100,
        bottleneck_strength=100,
        commoditization_risk=0,
        input_cost_risk=0,
    )
    assert node_attractiveness(maxed) == 100.0


def test_zero_dimension_collapses_node() -> None:
    dead = _node(urgency_score=0)
    assert node_attractiveness(dead) == 0.0


def test_commoditization_risk_reduces_attractiveness() -> None:
    cheap = _node(commoditization_risk=0)
    commodity = _node(commoditization_risk=100)
    assert node_attractiveness(commodity) < node_attractiveness(cheap)


def test_out_of_range_inputs_are_clamped() -> None:
    weird = _node(necessity_score=500, commoditization_risk=-50)
    assert 0.0 <= node_attractiveness(weird) <= 100.0


def test_map_ranks_nodes_descending() -> None:
    strong = _node(name="bottleneck", bottleneck_strength=95, urgency_score=95)
    weak = _node(name="commodity", commoditization_risk=95, pricing_power_score=20)
    result = map_value_chain("water", [weak, strong])
    scores = [row["node_attractiveness"] for row in result["nodes"]]
    assert scores == sorted(scores, reverse=True)
    assert result["top_node"] == "bottleneck"
    assert result["node_count"] == 2


def test_map_accepts_plain_dict_nodes() -> None:
    result = map_value_chain(
        "water", [{"name": "valves", "urgency_score": 80.0}]
    )
    assert result["nodes"][0]["name"] == "valves"


def test_empty_chain_does_not_crash() -> None:
    result = map_value_chain("empty theme", [])
    assert result["node_count"] == 0
    assert result["top_node"] is None
