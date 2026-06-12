"""Reality Anchoring + Simulacra layer: is the board real?

    RealityAnchor = directness + auditability + third-party confirmation
                    + cash-flow linkage − narrative dependency

Baudrillard's four layers classify what a signal IS:
    reflection        — faithfully represents reality
    distortion        — represents reality, bent
    masking_absence   — pretends a reality that is not there
    hyperreality      — belief about belief; the scoreboard IS the game

And the split the repo never had: tradeability is not investability.

    InvestmentScore  = fundamentals × reality_anchor × payoff_asymmetry
    TradeabilityScore = narrative_momentum × liquidity × reflexivity
    DangerScore      = hyperreality × leverage × weak_cash_flow × crowding

A hyperreal asset is not automatically rejected — it is classified as a
possible trade and a dangerous investment, with both numbers shown.
ADVISORY_ONLY throughout.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

SIMULACRA_LAYERS: tuple[str, ...] = (
    "reflection", "distortion", "masking_absence", "hyperreality",
)


@dataclass(slots=True)
class RealityAssessment:
    """Reality anchoring, simulacra layer, and the two-score split."""

    reality_anchor_score: float
    simulacra_layer: str
    investment_score: float
    tradeability_score: float
    danger_score: float
    hyperreality_penalty: float
    classification: str
    rationale: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def reality_anchor_score(
    *,
    directness: float = 0.0,
    auditability: float = 0.0,
    third_party_confirmation: float = 0.0,
    cash_flow_linkage: float = 0.0,
    narrative_dependency: float = 0.0,
) -> float:
    """RAS in [0, 1]: how close the evidence sits to verifiable reality."""
    return clamp01(
        0.25 * normalized_score(directness)
        + 0.25 * normalized_score(auditability)
        + 0.25 * normalized_score(third_party_confirmation)
        + 0.25 * normalized_score(cash_flow_linkage)
        - 0.5 * normalized_score(narrative_dependency)
    )


def _simulacra_layer(
    anchor: float, narrative_dependency: float, fundamentals: float
) -> str:
    """Classify the signal's relationship to reality."""
    if anchor >= 0.6:
        return "reflection"
    if anchor >= 0.35:
        return "distortion"
    # Weak anchor: is there any reality left underneath the story?
    if fundamentals >= 0.4:
        return "masking_absence" if narrative_dependency >= 0.5 else "distortion"
    return "hyperreality" if narrative_dependency >= 0.5 else "masking_absence"


def assess_reality(
    *,
    directness: float = 0.0,
    auditability: float = 0.0,
    third_party_confirmation: float = 0.0,
    cash_flow_linkage: float = 0.0,
    narrative_dependency: float = 0.0,
    fundamentals: float = 0.0,
    payoff_asymmetry: float = 0.5,
    narrative_momentum: float = 0.0,
    liquidity: float = 0.5,
    reflexivity: float = 0.0,
    leverage: float = 0.0,
    crowdedness: float = 0.0,
) -> RealityAssessment:
    """Anchor the thesis to reality and split investment from trade.

    All inputs are normalized [0, 1] research judgements. The output
    deliberately carries TWO scores plus a danger score — collapsing them
    into one number is exactly the error this module exists to prevent.
    """
    anchor = reality_anchor_score(
        directness=directness,
        auditability=auditability,
        third_party_confirmation=third_party_confirmation,
        cash_flow_linkage=cash_flow_linkage,
        narrative_dependency=narrative_dependency,
    )
    narrative_dep = normalized_score(narrative_dependency)
    funds = normalized_score(fundamentals)
    layer = _simulacra_layer(anchor, narrative_dep, funds)

    investment = clamp01(
        funds * (0.3 + 0.7 * anchor) * (0.5 + 0.5 * normalized_score(payoff_asymmetry))
    ) * 10.0
    tradeability = clamp01(
        normalized_score(narrative_momentum)
        * (0.4 + 0.6 * normalized_score(liquidity))
        * (0.6 + 0.4 * normalized_score(reflexivity))
    ) * 10.0
    weak_cash_flow = 1.0 - normalized_score(cash_flow_linkage)
    hyper = 1.0 if layer == "hyperreality" else (
        0.5 if layer == "masking_absence" else 0.0
    )
    danger = clamp01(
        hyper
        * (0.4 + 0.6 * normalized_score(leverage))
        * (0.4 + 0.6 * weak_cash_flow)
        * (0.4 + 0.6 * normalized_score(crowdedness))
    ) * 10.0
    hyperreality_penalty = clamp01(1.0 - anchor) * hyper

    if investment >= 5.5 and tradeability < 4.0:
        classification = "reality_anchored_opportunity"
        note = ("strong reality with weak narrative — boring evidence can "
                "beat exciting simulation")
    elif tradeability >= 5.5 and investment < 4.0:
        classification = "tradeable_but_dangerous"
        note = ("weak reality with strong narrative — possibly tradeable, "
                "dangerous as an investment; do not confuse the two")
    elif investment >= 5.5 and tradeability >= 5.5:
        classification = "aligned"
        note = "reality and narrative agree — rare and worth attention"
    else:
        classification = "weak_both"
        note = "neither reality nor narrative carries this thesis"

    rationale = [
        f"reality anchor {anchor:.2f} -> simulacra layer '{layer}'",
        f"investment {investment:.1f}/10 vs tradeability "
        f"{tradeability:.1f}/10 — {note}",
    ]
    if danger >= 5.0:
        rationale.append(
            f"danger {danger:.1f}/10: hyperreal, levered, cash-flow-weak, "
            "crowded — the configuration that breaks suddenly"
        )

    return RealityAssessment(
        reality_anchor_score=anchor,
        simulacra_layer=layer,
        investment_score=investment,
        tradeability_score=tradeability,
        danger_score=danger,
        hyperreality_penalty=hyperreality_penalty,
        classification=classification,
        rationale=rationale,
        raw_components={
            "directness": normalized_score(directness),
            "auditability": normalized_score(auditability),
            "third_party_confirmation": normalized_score(third_party_confirmation),
            "cash_flow_linkage": normalized_score(cash_flow_linkage),
            "narrative_dependency": narrative_dep,
            "fundamentals": funds,
        },
    )
