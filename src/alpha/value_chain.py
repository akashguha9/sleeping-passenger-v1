"""Module E — Porter value-chain mapper.

A broad truth ("humans need water") is not an investment until it is
mapped to the upstream/downstream nodes that actually capture profit.

    Node Attractiveness =
        (Necessity x Urgency x PricingPower x RepeatDemand x BottleneckStrength)
        / (1 + CommoditizationRisk + InputCostRisk)

All node inputs are 0-100.  The multiplicative numerator is folded with a
geometric mean so a single dead dimension (e.g. zero urgency) still
collapses the node, while the result stays interpretable on 0-100.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.math_utils import clip

VALID_POSITIONS = (
    "upstream_raw_materials",
    "upstream_components",
    "midstream_assembly",
    "midstream_distribution",
    "downstream_interface",
    "downstream_service",
    "downstream_prevention",
    "downstream_risk_transfer",
)

_ATTRACTIVENESS_INPUTS = (
    "necessity_score",
    "urgency_score",
    "pricing_power_score",
    "repeat_demand_score",
    "bottleneck_strength",
)
_RISK_INPUTS = ("commoditization_risk", "input_cost_risk")
_NEUTRAL = 50.0


@dataclass(slots=True)
class ValueChainNode:
    """One profit-capture node in a theme's value chain (inputs 0-100)."""

    name: str
    position: str = "midstream_assembly"
    role: str = ""
    necessity_score: float = _NEUTRAL
    urgency_score: float = _NEUTRAL
    pricing_power_score: float = _NEUTRAL
    repeat_demand_score: float = _NEUTRAL
    bottleneck_strength: float = _NEUTRAL
    commoditization_risk: float = _NEUTRAL
    input_cost_risk: float = _NEUTRAL
    candidate_company_types: list[str] = field(default_factory=list)


def node_attractiveness(node: ValueChainNode) -> float:
    """Score a node 0-100 using the bottleneck/urgency capture formula."""
    fractions = [
        clip(getattr(node, key), 0.0, 100.0) / 100.0
        for key in _ATTRACTIVENESS_INPUTS
    ]
    product = 1.0
    for fraction in fractions:
        product *= fraction
    geometric_mean = product ** (1.0 / len(fractions))
    denominator = 1.0 + sum(
        clip(getattr(node, key), 0.0, 100.0) / 100.0 for key in _RISK_INPUTS
    )
    return clip(100.0 * geometric_mean / denominator, 0.0, 100.0)


def score_node(node: ValueChainNode) -> dict[str, object]:
    """Serialize one node with its computed attractiveness."""
    attractiveness = node_attractiveness(node)
    return {
        "name": node.name,
        "position": node.position,
        "role": node.role,
        "necessity_score": clip(node.necessity_score, 0.0, 100.0),
        "urgency_score": clip(node.urgency_score, 0.0, 100.0),
        "pricing_power_score": clip(node.pricing_power_score, 0.0, 100.0),
        "repeat_demand_score": clip(node.repeat_demand_score, 0.0, 100.0),
        "bottleneck_strength": clip(node.bottleneck_strength, 0.0, 100.0),
        "commoditization_risk": clip(node.commoditization_risk, 0.0, 100.0),
        "input_cost_risk": clip(node.input_cost_risk, 0.0, 100.0),
        "node_attractiveness": attractiveness,
        "candidate_company_types": list(node.candidate_company_types),
    }


def map_value_chain(
    theme: str, nodes: list[ValueChainNode] | list[dict[str, object]]
) -> dict[str, object]:
    """Map a theme into scored nodes, ranked by attractiveness.

    Accepts ``ValueChainNode`` instances or plain dicts with the same
    field names (unknown dict keys are rejected by the dataclass, keeping
    the input surface explicit).
    """
    parsed: list[ValueChainNode] = []
    for raw in nodes:
        parsed.append(raw if isinstance(raw, ValueChainNode) else ValueChainNode(**raw))
    scored = sorted(
        (score_node(node) for node in parsed),
        key=lambda row: row["node_attractiveness"],
        reverse=True,
    )
    return {
        "theme": theme,
        "node_count": len(scored),
        "nodes": scored,
        "top_node": scored[0]["name"] if scored else None,
        "explanation": [
            f"Theme '{theme}' decomposed into {len(scored)} value-chain node(s).",
            "Attractiveness = geometric mean of necessity, urgency, pricing "
            "power, repeat demand, and bottleneck strength, divided by "
            "(1 + commoditization risk + input cost risk).",
            "The alpha is not the theme; it is the node that captures the leak.",
        ],
    }
