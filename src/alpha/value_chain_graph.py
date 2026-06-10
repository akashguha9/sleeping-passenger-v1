"""Value-chain graph: nodes with edges, evidence links, and failure-cost math.

Extends the flat Porter mapper (``value_chain.py``) with explicit graph
relationships — who feeds whom, who captures value from whom, who passes
cost to whom — and a deeper attractiveness formula:

    Node Attractiveness =
      100 × normalize(
        Necessity × Urgency × PricingPower × RepeatDemand
        × BottleneckStrength × FailureCost × ReplacementCycle
        /
        (1 + CommoditizationRisk + InputCostRisk + SubstitutionRisk)
      )

implemented as a geometric mean of the seven positive factors divided by
the risk denominator, so one dead dimension still collapses a node while
the scale stays 0-100.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.math_utils import clip

GRAPH_POSITIONS = (
    "upstream",
    "midstream",
    "downstream",
    "interface",
    "service",
    "data_layer",
    "risk_transfer",
)

_POSITIVE_FACTORS = (
    "necessity_score",
    "urgency_score",
    "pricing_power_score",
    "repeat_demand_score",
    "bottleneck_strength",
    "failure_cost_score",
    "replacement_cycle_score",
)
_RISK_FACTORS = ("commoditization_risk", "input_cost_risk", "substitution_risk")
_NEUTRAL = 50.0


@dataclass(slots=True)
class ValueChainGraphNode:
    """One node in a theme's value-chain graph (all scores 0-100)."""

    node_id: str
    name: str
    position: str = "midstream"
    role: str = ""
    parents: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    captures_value_from: list[str] = field(default_factory=list)
    passes_cost_to: list[str] = field(default_factory=list)
    necessity_score: float = _NEUTRAL
    urgency_score: float = _NEUTRAL
    pricing_power_score: float = _NEUTRAL
    repeat_demand_score: float = _NEUTRAL
    bottleneck_strength: float = _NEUTRAL
    failure_cost_score: float = _NEUTRAL
    replacement_cycle_score: float = _NEUTRAL
    commoditization_risk: float = _NEUTRAL
    input_cost_risk: float = _NEUTRAL
    substitution_risk: float = _NEUTRAL
    evidence_links: list[str] = field(default_factory=list)
    candidate_company_types: list[str] = field(default_factory=list)


def graph_node_attractiveness(node: ValueChainGraphNode) -> float:
    """Score a graph node 0-100 with failure-cost/replacement-cycle math."""
    product = 1.0
    for key in _POSITIVE_FACTORS:
        product *= clip(getattr(node, key), 0.0, 100.0) / 100.0
    geometric_mean = product ** (1.0 / len(_POSITIVE_FACTORS))
    denominator = 1.0 + sum(
        clip(getattr(node, key), 0.0, 100.0) / 100.0 for key in _RISK_FACTORS
    )
    return clip(100.0 * geometric_mean / denominator, 0.0, 100.0)


def _serialize_node(node: ValueChainGraphNode) -> dict[str, object]:
    return {
        "node_id": node.node_id,
        "name": node.name,
        "position": node.position,
        "role": node.role,
        "parents": list(node.parents),
        "children": list(node.children),
        "captures_value_from": list(node.captures_value_from),
        "passes_cost_to": list(node.passes_cost_to),
        "necessity_score": clip(node.necessity_score, 0.0, 100.0),
        "urgency_score": clip(node.urgency_score, 0.0, 100.0),
        "pricing_power_score": clip(node.pricing_power_score, 0.0, 100.0),
        "repeat_demand_score": clip(node.repeat_demand_score, 0.0, 100.0),
        "bottleneck_strength": clip(node.bottleneck_strength, 0.0, 100.0),
        "failure_cost_score": clip(node.failure_cost_score, 0.0, 100.0),
        "replacement_cycle_score": clip(node.replacement_cycle_score, 0.0, 100.0),
        "commoditization_risk": clip(node.commoditization_risk, 0.0, 100.0),
        "input_cost_risk": clip(node.input_cost_risk, 0.0, 100.0),
        "substitution_risk": clip(node.substitution_risk, 0.0, 100.0),
        "node_attractiveness": graph_node_attractiveness(node),
        "evidence_links": list(node.evidence_links),
        "candidate_company_types": list(node.candidate_company_types),
    }


def build_value_chain_graph(
    theme: str, nodes: list[ValueChainGraphNode]
) -> dict[str, object]:
    """Assemble and validate a value-chain graph, ranked by attractiveness."""
    known_ids = {node.node_id for node in nodes}
    dangling_edges: list[str] = []
    for node in nodes:
        for edge_kind in ("parents", "children", "captures_value_from", "passes_cost_to"):
            for target in getattr(node, edge_kind):
                if target not in known_ids:
                    dangling_edges.append(f"{node.node_id}.{edge_kind} -> {target}")
    serialized = sorted(
        (_serialize_node(node) for node in nodes),
        key=lambda row: row["node_attractiveness"],
        reverse=True,
    )
    edge_count = sum(
        len(node.parents) + len(node.children) for node in nodes
    )
    return {
        "theme": theme,
        "node_count": len(serialized),
        "edge_count": edge_count,
        "nodes": serialized,
        "top_node": serialized[0]["node_id"] if serialized else None,
        "dangling_edges": dangling_edges,
        "graph_valid": not dangling_edges,
        "explanation": [
            f"Theme '{theme}': {len(serialized)} node(s), {edge_count} "
            "parent/child edge(s).",
            "Attractiveness adds failure cost and replacement cycle to the "
            "Porter formula and divides by commoditization, input-cost, and "
            "substitution risk.",
        ],
    }


def build_plumbing_value_chain_graph() -> dict[str, object]:
    """Deterministic plumbing graph: the 13 case-study nodes with edges.

    Edge semantics: ``children`` = who this node feeds/serves downstream;
    ``captures_value_from`` = whose spending this node monetizes;
    ``passes_cost_to`` = who absorbs this node's cost increases.
    Parameters are illustrative framework inputs, not researched
    financial estimates.
    """
    nodes = [
        ValueChainGraphNode(
            node_id="raw_materials", name="raw materials", position="upstream",
            role="copper, PVC, brass, steel feedstock",
            children=["pipes", "valves", "fittings", "faucets"],
            passes_cost_to=["pipes", "valves", "fittings", "faucets"],
            necessity_score=90, urgency_score=35, pricing_power_score=30,
            repeat_demand_score=70, bottleneck_strength=45,
            failure_cost_score=30, replacement_cycle_score=40,
            commoditization_risk=85, input_cost_risk=70, substitution_risk=40,
            evidence_links=["commodity price indices", "producer filings"],
            candidate_company_types=["metal producers", "resin manufacturers"],
        ),
        ValueChainGraphNode(
            node_id="pipes", name="pipes", position="upstream",
            role="bulk water transport inside the structure",
            parents=["raw_materials"],
            children=["fittings", "valves", "plumbers_contractors"],
            captures_value_from=["distributors_hardware_stores"],
            passes_cost_to=["plumbers_contractors"],
            necessity_score=95, urgency_score=50, pricing_power_score=35,
            repeat_demand_score=65, bottleneck_strength=50,
            failure_cost_score=70, replacement_cycle_score=35,
            commoditization_risk=80, input_cost_risk=60, substitution_risk=35,
            evidence_links=["building-products revenue segments"],
            candidate_company_types=["pipe extruders"],
        ),
        ValueChainGraphNode(
            node_id="valves", name="valves", position="midstream",
            role="flow control and safety; failure cost is flooding",
            parents=["raw_materials", "pipes"],
            children=["plumbers_contractors", "water_meters"],
            captures_value_from=["distributors_hardware_stores"],
            necessity_score=92, urgency_score=75, pricing_power_score=60,
            repeat_demand_score=70, bottleneck_strength=70,
            failure_cost_score=85, replacement_cycle_score=55,
            commoditization_risk=45, input_cost_risk=45, substitution_risk=30,
            evidence_links=["flow-control segment disclosures"],
            candidate_company_types=["flow-control specialists"],
        ),
        ValueChainGraphNode(
            node_id="fittings", name="fittings", position="midstream",
            role="joints and couplings; every run needs many",
            parents=["raw_materials", "pipes"],
            children=["plumbers_contractors"],
            necessity_score=90, urgency_score=60, pricing_power_score=50,
            repeat_demand_score=80, bottleneck_strength=55,
            failure_cost_score=70, replacement_cycle_score=50,
            commoditization_risk=55, input_cost_risk=45, substitution_risk=35,
            candidate_company_types=["fitting manufacturers"],
        ),
        ValueChainGraphNode(
            node_id="faucets", name="faucets", position="interface",
            role="visible user interface; carries aesthetic premium",
            parents=["raw_materials"],
            children=["sinks_showers_toilets"],
            captures_value_from=["distributors_hardware_stores"],
            necessity_score=85, urgency_score=55, pricing_power_score=70,
            repeat_demand_score=60, bottleneck_strength=40,
            failure_cost_score=45, replacement_cycle_score=60,
            commoditization_risk=50, input_cost_risk=40, substitution_risk=40,
            candidate_company_types=["branded fixture makers"],
        ),
        ValueChainGraphNode(
            node_id="sinks_showers_toilets", name="sinks/showers/toilets",
            position="interface", role="fixtures; renovation-cycle demand",
            parents=["faucets"],
            children=["plumbers_contractors"],
            necessity_score=88, urgency_score=45, pricing_power_score=55,
            repeat_demand_score=55, bottleneck_strength=35,
            failure_cost_score=50, replacement_cycle_score=45,
            commoditization_risk=55, input_cost_risk=45, substitution_risk=35,
            candidate_company_types=["sanitaryware manufacturers"],
        ),
        ValueChainGraphNode(
            node_id="fixing_tape_sealants", name="fixing tape/sealants",
            position="service", role="emergency repair consumable",
            children=["plumbers_contractors"],
            captures_value_from=["insurance_water_damage_prevention"],
            necessity_score=80, urgency_score=90, pricing_power_score=65,
            repeat_demand_score=85, bottleneck_strength=45,
            failure_cost_score=80, replacement_cycle_score=85,
            commoditization_risk=60, input_cost_risk=30, substitution_risk=40,
            candidate_company_types=["adhesives/sealant makers"],
        ),
        ValueChainGraphNode(
            node_id="wrenches_tools", name="wrenches/tools", position="service",
            role="enablement layer; professional trust",
            children=["plumbers_contractors"],
            necessity_score=75, urgency_score=55, pricing_power_score=60,
            repeat_demand_score=50, bottleneck_strength=40,
            failure_cost_score=40, replacement_cycle_score=35,
            commoditization_risk=50, input_cost_risk=35, substitution_risk=30,
            candidate_company_types=["professional tool brands"],
        ),
        ValueChainGraphNode(
            node_id="plumbers_contractors", name="plumbers/contractors",
            position="service", role="labour scarcity and urgency pricing",
            parents=["pipes", "valves", "fittings", "sinks_showers_toilets",
                     "fixing_tape_sealants", "wrenches_tools"],
            captures_value_from=["insurance_water_damage_prevention"],
            passes_cost_to=["insurance_water_damage_prevention"],
            necessity_score=95, urgency_score=95, pricing_power_score=80,
            repeat_demand_score=85, bottleneck_strength=85,
            failure_cost_score=90, replacement_cycle_score=70,
            commoditization_risk=25, input_cost_risk=50, substitution_risk=20,
            evidence_links=["trade-labour wage statistics"],
            candidate_company_types=["home-services platforms"],
        ),
        ValueChainGraphNode(
            node_id="distributors_hardware_stores",
            name="distributors/hardware stores", position="midstream",
            role="inventory and access power; the shelf when it floods",
            children=["pipes", "valves", "fittings", "faucets",
                      "fixing_tape_sealants", "wrenches_tools"],
            captures_value_from=["plumbers_contractors"],
            necessity_score=85, urgency_score=80, pricing_power_score=65,
            repeat_demand_score=90, bottleneck_strength=70,
            failure_cost_score=60, replacement_cycle_score=75,
            commoditization_risk=35, input_cost_risk=40, substitution_risk=30,
            evidence_links=["specialty-distribution revenue segments"],
            candidate_company_types=["specialty distributors"],
        ),
        ValueChainGraphNode(
            node_id="smart_leak_sensors", name="smart leak sensors",
            position="data_layer", role="prevention/data layer; growth sidecar",
            children=["insurance_water_damage_prevention", "water_meters"],
            captures_value_from=["insurance_water_damage_prevention"],
            necessity_score=55, urgency_score=60, pricing_power_score=70,
            repeat_demand_score=55, bottleneck_strength=50,
            failure_cost_score=75, replacement_cycle_score=50,
            commoditization_risk=40, input_cost_risk=35, substitution_risk=45,
            candidate_company_types=["IoT water-monitoring firms"],
        ),
        ValueChainGraphNode(
            node_id="water_meters", name="water meters", position="data_layer",
            role="measurement; utility-mandated replacement cycles",
            parents=["valves", "smart_leak_sensors"],
            necessity_score=80, urgency_score=50, pricing_power_score=65,
            repeat_demand_score=70, bottleneck_strength=65,
            failure_cost_score=55, replacement_cycle_score=80,
            commoditization_risk=35, input_cost_risk=40, substitution_risk=25,
            candidate_company_types=["metering technology firms"],
        ),
        ValueChainGraphNode(
            node_id="insurance_water_damage_prevention",
            name="insurance/water-damage prevention", position="risk_transfer",
            role="failure-cost monetization layer",
            parents=["smart_leak_sensors"],
            captures_value_from=["plumbers_contractors", "fixing_tape_sealants"],
            necessity_score=75, urgency_score=70, pricing_power_score=70,
            repeat_demand_score=90, bottleneck_strength=55,
            failure_cost_score=95, replacement_cycle_score=90,
            commoditization_risk=40, input_cost_risk=55, substitution_risk=25,
            evidence_links=["water-damage claims statistics"],
            candidate_company_types=["property insurers"],
        ),
    ]
    return build_value_chain_graph("residential plumbing and water access", nodes)
