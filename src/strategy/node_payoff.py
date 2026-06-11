"""Node Payoff Layer Matrix: a good node can still be a bad bet.

Five layers decide whether a strategic node is worth playing:

    1. Casino:     EV = p·Upside − (1−p)·Downside − Cost_of_Waiting
    2. Food chain: pricing power vs supplier/customer power
    3. Half-life:  Durable_Edge = Strength × Half_Life_Factor × Defensibility
    4. Threshold:  no threshold, no buy — uncrossed caps everything
    5. Inflection: probability × impact × evidence confidence

    Node_Adjusted_Score = EV + Food_Chain + Durable_Edge + Threshold
                          + Inflection − Decay_Risk − Fragility
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import normalized_score

FOOD_CHAIN_POSITIONS: tuple[str, ...] = (
    "predator", "prey", "toll_booth", "symbiont", "parasite",
    "scavenger", "supplier", "keystone",
)

# Edge half-life reference: 36 months of half-life ≈ full durability credit.
EDGE_HALF_LIFE_REFERENCE_MONTHS = 36.0


@dataclass(slots=True)
class NodePayoffMatrix:
    """Full five-layer payoff verdict for one company's node."""

    # Casino layer
    casino_ev: float
    probability_of_success: float
    upside: float
    downside: float
    cost_of_waiting: float
    casino_ev_score: float
    # Food chain layer
    food_chain_position: str
    food_chain_power_score: float
    # Half-life layer
    edge_type: str
    current_edge_strength: float
    edge_half_life_months: float
    defensibility: float
    decay_risk: float
    durable_edge_value: float
    # Threshold layer
    threshold_condition: str
    threshold_crossed: bool
    threshold_readiness_score: float
    missing_thresholds: list[str] = field(default_factory=list)
    # Inflection layer
    inflection_candidate: str = ""
    inflection_probability: float = 0.0
    inflection_impact: float = 0.0
    inflection_value: float = 0.0
    # Composite
    node_adjusted_score: float = 0.0
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def casino_expected_value(
    *,
    probability_of_success: float,
    upside: float,
    downside: float,
    cost_of_waiting: float = 0.0,
) -> float:
    """EV in payoff units (upside/downside are positive magnitudes)."""
    p = normalized_score(probability_of_success)
    return (
        p * max(float(upside), 0.0)
        - (1.0 - p) * max(float(downside), 0.0)
        - max(float(cost_of_waiting), 0.0)
    )


def food_chain_power(
    *,
    position: str,
    pricing_power: float = 0.0,
    dependency_control: float = 0.0,
    supplier_power_against_us: float = 0.0,
    customer_power_against_us: float = 0.0,
) -> float:
    """Food-chain power in [0, 1]; prey-like positions are capped low."""
    base = clamp01(
        0.4 * normalized_score(pricing_power)
        + 0.3 * normalized_score(dependency_control)
        + 0.3
        - 0.25 * normalized_score(supplier_power_against_us)
        - 0.25 * normalized_score(customer_power_against_us)
    )
    pos = str(position).strip().lower()
    if pos in ("prey", "parasite", "scavenger"):
        return min(base, 0.35)
    if pos in ("toll_booth", "keystone"):
        return clamp01(base + 0.15)
    return base


def evaluate_node_payoff(
    *,
    probability_of_success: float = 0.0,
    upside: float = 0.0,
    downside: float = 0.0,
    cost_of_waiting: float = 0.0,
    food_chain_position: str = "supplier",
    pricing_power: float = 0.0,
    dependency_control: float = 0.0,
    supplier_power_against_us: float = 0.0,
    customer_power_against_us: float = 0.0,
    edge_type: str = "unspecified",
    current_edge_strength: float = 0.0,
    edge_half_life_months: float = 0.0,
    defensibility: float = 0.0,
    threshold_condition: str = "",
    threshold_crossed: bool = False,
    missing_thresholds: list[str] | None = None,
    inflection_candidate: str = "",
    inflection_probability: float = 0.0,
    inflection_impact: float = 0.0,
    inflection_evidence_confidence: float = 0.5,
    fragility: float = 0.0,
) -> NodePayoffMatrix:
    """Score the five payoff layers and compose the node-adjusted score."""
    ev = casino_expected_value(
        probability_of_success=probability_of_success,
        upside=upside,
        downside=downside,
        cost_of_waiting=cost_of_waiting,
    )
    # Normalize EV to [0, 1]: EV of +1 payoff unit saturates; negative -> 0.
    ev_score = clamp01(ev) if ev > 0 else 0.0

    chain_power = food_chain_power(
        position=food_chain_position,
        pricing_power=pricing_power,
        dependency_control=dependency_control,
        supplier_power_against_us=supplier_power_against_us,
        customer_power_against_us=customer_power_against_us,
    )

    half_life = max(float(edge_half_life_months), 0.0)
    # Exponential saturation: 36-month half-life earns ~63% of full credit.
    half_life_factor = 1.0 - math.exp(-half_life / EDGE_HALF_LIFE_REFERENCE_MONTHS)
    durable_edge = clamp01(
        normalized_score(current_edge_strength)
        * half_life_factor
        * (0.5 + 0.5 * normalized_score(defensibility))
    )
    decay_risk = clamp01(
        normalized_score(current_edge_strength) * (1.0 - half_life_factor)
    )

    threshold_readiness = 1.0 if threshold_crossed else clamp01(
        0.5 - 0.1 * len(missing_thresholds or [])
    )

    inflection_value = (
        normalized_score(inflection_probability)
        * normalized_score(inflection_impact)
        * normalized_score(inflection_evidence_confidence)
    )

    score = clip(
        ev_score
        + chain_power
        + durable_edge
        + threshold_readiness
        + inflection_value
        - decay_risk
        - normalized_score(fragility),
        0.0,
        5.0,
    ) / 5.0 * 10.0

    rationale = [
        f"casino EV {ev:+.2f} (score {ev_score:.2f}); food-chain "
        f"'{food_chain_position}' power {chain_power:.2f}; durable edge "
        f"{durable_edge:.2f} (half-life {half_life:.0f}mo); threshold "
        f"{'crossed' if threshold_crossed else 'NOT crossed'}; inflection "
        f"{inflection_value:.2f}",
    ]
    if ev <= 0 and upside > 0:
        rationale.append(
            "exciting upside with non-positive expected value — the casino "
            "layer rejects excitement without odds"
        )
    if not threshold_crossed:
        rationale.append("no threshold, no buy — watchlist ceiling applies")
    if str(food_chain_position).lower() in ("prey", "parasite"):
        rationale.append("prey-like food-chain position caps hierarchy power")

    return NodePayoffMatrix(
        casino_ev=ev,
        probability_of_success=normalized_score(probability_of_success),
        upside=max(float(upside), 0.0),
        downside=max(float(downside), 0.0),
        cost_of_waiting=max(float(cost_of_waiting), 0.0),
        casino_ev_score=ev_score,
        food_chain_position=str(food_chain_position).lower(),
        food_chain_power_score=chain_power,
        edge_type=str(edge_type),
        current_edge_strength=normalized_score(current_edge_strength),
        edge_half_life_months=half_life,
        defensibility=normalized_score(defensibility),
        decay_risk=decay_risk,
        durable_edge_value=durable_edge,
        threshold_condition=str(threshold_condition),
        threshold_crossed=bool(threshold_crossed),
        threshold_readiness_score=threshold_readiness,
        missing_thresholds=list(missing_thresholds or []),
        inflection_candidate=str(inflection_candidate),
        inflection_probability=normalized_score(inflection_probability),
        inflection_impact=normalized_score(inflection_impact),
        inflection_value=inflection_value,
        node_adjusted_score=score,
        rationale=rationale,
    )
