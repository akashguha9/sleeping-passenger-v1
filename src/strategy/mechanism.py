"""Narrative-to-Mechanism Engine: no mechanism, no trade.

A narrative matters only if it changes economics. The engine scores the
declared transmission channels — cash flow, demand/supply, margins,
regulation, cost of capital, valuation multiple, risk — and hard-rejects
narratives that change none of them.

    Narrative_Value = Probability_Shock × Mechanism_Strength
    Trade_Eligibility = 0 if Mechanism_Validity = 0
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

MECHANISM_CHANNELS: tuple[str, ...] = (
    "cash_flow_impact",
    "demand_impact",
    "supply_impact",
    "margin_impact",
    "regulation_impact",
    "cost_of_capital_impact",
    "multiple_impact",
    "risk_impact",
)

# A channel below this is noise, not a mechanism.
CHANNEL_FLOOR = 0.15
# Mechanism validity requires at least one channel at or above this.
VALID_CHANNEL_THRESHOLD = 0.30


@dataclass(slots=True)
class MechanismAssessment:
    """Economic-mechanism verdict for one narrative."""

    narrative: str
    mechanism_valid: bool
    mechanism_strength: float
    narrative_value: float
    active_channels: list[str] = field(default_factory=list)
    transmission_path: str = ""
    investment_implication: str = ""
    rationale: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_mechanism(
    *,
    narrative: str,
    probability_shock: float = 0.0,
    cash_flow_impact: float = 0.0,
    demand_impact: float = 0.0,
    supply_impact: float = 0.0,
    margin_impact: float = 0.0,
    regulation_impact: float = 0.0,
    cost_of_capital_impact: float = 0.0,
    multiple_impact: float = 0.0,
    risk_impact: float = 0.0,
    transmission_path: str = "",
) -> MechanismAssessment:
    """Score how a narrative transmits into economics (0–1 channels).

    Hard rule: if no channel clears the validity threshold, the narrative
    is hype — mechanism_valid is False and narrative_value is zero.
    """
    channels = {
        "cash_flow_impact": normalized_score(cash_flow_impact),
        "demand_impact": normalized_score(demand_impact),
        "supply_impact": normalized_score(supply_impact),
        "margin_impact": normalized_score(margin_impact),
        "regulation_impact": normalized_score(regulation_impact),
        "cost_of_capital_impact": normalized_score(cost_of_capital_impact),
        "multiple_impact": normalized_score(multiple_impact),
        "risk_impact": normalized_score(risk_impact),
    }
    active = sorted(
        (name for name, value in channels.items() if value >= CHANNEL_FLOOR),
        key=lambda name: -channels[name],
    )
    valid = any(value >= VALID_CHANNEL_THRESHOLD for value in channels.values())

    # Strength: the two strongest channels carry the mechanism; a story
    # that weakly touches everything is not stronger than one that
    # decisively changes demand.
    ranked = sorted(channels.values(), reverse=True)
    strength = clamp01(0.7 * ranked[0] + 0.3 * ranked[1]) if valid else 0.0
    shock = normalized_score(probability_shock)
    narrative_value = shock * strength if valid else 0.0

    rationale: list[str] = []
    if not valid:
        rationale.append(
            "NO MECHANISM, NO TRADE — no economic channel clears "
            f"{VALID_CHANNEL_THRESHOLD}; narrative_value forced to 0"
        )
    else:
        rationale.append(
            f"mechanism carried by: {', '.join(active[:3])} "
            f"(strength {strength:.2f})"
        )
        rationale.append(
            f"narrative_value = shock {shock:.2f} × strength {strength:.2f} "
            f"= {narrative_value:.2f}"
        )

    implication = ""
    if valid and active:
        implication = (
            f"narrative '{narrative}' transmits primarily via "
            f"{active[0].replace('_', ' ')}"
        )

    return MechanismAssessment(
        narrative=str(narrative),
        mechanism_valid=valid,
        mechanism_strength=strength,
        narrative_value=narrative_value,
        active_channels=active,
        transmission_path=str(transmission_path),
        investment_implication=implication,
        rationale=rationale,
        raw_components={**channels, "probability_shock": shock},
    )
