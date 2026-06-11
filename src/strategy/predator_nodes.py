"""Apex Predator Node Classifier: dominance is node-specific.

Do not ask which predator is strongest; ask which game each predator is
playing. Companies are classified by strategic role from declared trait
scores — deterministic weighted matching, never self-labels.

    Node_Fit = Weapon_Node_Match + Payoff_Asymmetry + Defensibility
               + Mobility − Node_Fragility
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

# Node -> (weighted trait signature, economic role, node-specific risks).
# Traits are normalized [0, 1] company characteristics.
NODE_SIGNATURES: dict[str, dict[str, object]] = {
    "orca": {
        "traits": {"network_effects": 0.35, "ecosystem_control": 0.30,
                   "coordination_leverage": 0.20, "retention": 0.15},
        "role": "coalition dominance / platform / operating system",
        "risks": ["antitrust pressure", "ecosystem revolt", "coordination decay"],
    },
    "great_white": {
        "traits": {"catalyst_dependence": 0.40, "strike_asymmetry": 0.35,
                   "timing_sensitivity": 0.25},
        "role": "event-driven ambush / catalyst opportunity",
        "risks": ["missed strike", "catalyst slippage", "binary outcomes"],
    },
    "tiger_shark": {
        "traits": {"diversification": 0.40, "opportunism": 0.35,
                   "adaptability": 0.25},
        "role": "opportunistic generalist / diversified optionality",
        "risks": ["lack of focus", "mediocre everywhere", "capital sprawl"],
    },
    "sperm_whale": {
        "traits": {"deep_specialization": 0.45, "resource_depth": 0.35,
                   "long_cycle_tolerance": 0.20},
        "role": "deep-tech / deep-resource specialist",
        "risks": ["long payback", "technology leapfrog", "funding droughts"],
    },
    "giant_squid": {
        "traits": {"hidden_assets": 0.45, "low_visibility": 0.30,
                   "asymmetric_upside": 0.25},
        "role": "hidden asset / undercovered asymmetry",
        "risks": ["never discovered", "value trap", "weak governance cover"],
    },
    "bluefin_tuna": {
        "traits": {"execution_speed": 0.45, "operational_efficiency": 0.35,
                   "cycle_velocity": 0.20},
        "role": "velocity / execution machine",
        "risks": ["execution stumble", "speed commoditized", "margin erosion"],
    },
    "elephant_seal": {
        "traits": {"asset_scarcity": 0.45, "incumbency": 0.35,
                   "balance_sheet_mass": 0.20},
        "role": "asset fortress / scarce incumbent",
        "risks": ["asset obsolescence", "regulated returns", "stranded assets"],
    },
    "leopard_seal": {
        "traits": {"niche_control": 0.45, "interface_position": 0.35,
                   "boundary_expertise": 0.20},
        "role": "niche / boundary / interface controller",
        "risks": ["niche shrinks", "interface bypassed", "platform absorption"],
    },
    "crocodile": {
        "traits": {"chokepoint_control": 0.45, "switching_costs": 0.30,
                   "flow_capture": 0.25},
        "role": "chokepoint / toll-gate business",
        "risks": ["route rerouted", "regulation of tolls", "traffic decline"],
    },
}

PREDATOR_NODES: tuple[str, ...] = tuple(NODE_SIGNATURES)

# A classification below this confidence is reported as unclassified —
# forcing a node on weak traits is the metaphor-overfit failure mode.
MIN_NODE_CONFIDENCE = 0.35


@dataclass(slots=True)
class NodeClassification:
    """Strategic-role verdict for one company."""

    predator_node: str
    node_confidence: float
    dominant_weapon: str
    economic_role: str
    node_specific_risks: list[str] = field(default_factory=list)
    node_fit_score: float = 0.0
    secondary_node: str = ""
    all_node_scores: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_predator_node(
    traits: dict[str, float],
    *,
    payoff_asymmetry: float = 0.0,
    defensibility: float = 0.0,
    mobility: float = 0.0,
    node_fragility: float = 0.0,
) -> NodeClassification:
    """Classify by weighted trait match; weak matches stay unclassified."""
    normalized = {k: normalized_score(v) for k, v in (traits or {}).items()}
    scores: dict[str, float] = {}
    for node, signature in NODE_SIGNATURES.items():
        weights: dict[str, float] = signature["traits"]  # type: ignore[assignment]
        scores[node] = sum(
            weight * normalized.get(trait, 0.0)
            for trait, weight in weights.items()
        )

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_node, best_score = ranked[0]
    second_node, second_score = ranked[1]
    # Confidence: absolute match strength × separation from the runner-up.
    separation = clamp01((best_score - second_score) / max(best_score, 1e-9))
    confidence = clamp01(best_score * (0.6 + 0.4 * separation))

    if confidence < MIN_NODE_CONFIDENCE:
        return NodeClassification(
            predator_node="unclassified",
            node_confidence=confidence,
            dominant_weapon="none_established",
            economic_role="insufficient trait evidence for a node",
            node_fit_score=0.0,
            all_node_scores={k: round(v, 4) for k, v in scores.items()},
            rationale=[
                f"best match '{best_node}' at confidence {confidence:.2f} "
                f"< {MIN_NODE_CONFIDENCE} — refusing to force a node on "
                "weak traits (metaphor-overfit guard)"
            ],
        )

    signature = NODE_SIGNATURES[best_node]
    weights: dict[str, float] = signature["traits"]  # type: ignore[assignment]
    weapon = max(weights, key=lambda t: weights[t] * normalized.get(t, 0.0))
    fit = clamp01(
        best_score
        + 0.3 * normalized_score(payoff_asymmetry)
        + 0.3 * normalized_score(defensibility)
        + 0.2 * normalized_score(mobility)
        - 0.5 * normalized_score(node_fragility)
    )

    return NodeClassification(
        predator_node=best_node,
        node_confidence=confidence,
        dominant_weapon=weapon,
        economic_role=str(signature["role"]),
        node_specific_risks=list(signature["risks"]),  # type: ignore[arg-type]
        node_fit_score=fit,
        secondary_node=second_node if second_score >= 0.25 else "",
        all_node_scores={k: round(v, 4) for k, v in scores.items()},
        rationale=[
            f"node '{best_node}' (confidence {confidence:.2f}), dominant "
            f"weapon: {weapon}; fit {fit:.2f} after asymmetry/defensibility/"
            "mobility/fragility adjustments",
        ],
    )
