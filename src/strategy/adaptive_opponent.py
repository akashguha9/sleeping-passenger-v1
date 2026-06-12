"""Adaptive Opponent Model: markets are adaptive opponents, not static
scoreboards.

The mentor does not wait for the ball — he predicts the return and
positions early. This module asks the mentor's questions about every
thesis:

    What is the strongest weapon, and is it already overused?
    Where is the weak side, and is attacking it profitable?
    Has the market already adapted to the edge (OAI)?
    Is the niche a beachhead or a cage?
    What market-awareness layer is this (single/double/triple blind)?
    What does the catalyst's first reaction set up?
    Is the game complete, or one weapon deep?

Distinct from ``src/simulator/triple_blind.py`` (bias hygiene): the
blind LAYERS here grade market awareness of an edge, not reviewer
blinding. Reuses existing physics: edge decay is the tyre half-life law,
second-order nodes are the exposure graph, bait-vs-breakout is the
underground engine. ADVISORY_ONLY throughout.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip, safe_div
from src.utils.validation_utils import normalized_score

# ---------------------------------------------------------------------------
# Weapon Map
# ---------------------------------------------------------------------------

WEAPON_CANDIDATES: tuple[str, ...] = (
    "product_dominance", "pricing_power", "margin_strength",
    "regulation_tailwind", "insider_accumulation",
    "prediction_market_signal", "customer_lock_in",
    "supply_chain_position", "narrative_momentum", "technical_setup",
    "capital_allocation",
)


@dataclass(slots=True)
class WeaponMap:
    """The strongest repeatable edge — and whether it is already overused."""

    strongest_weapon: str
    weapon_score: float
    durability: float
    overused: bool
    crowding_penalty: float
    runner_up: str = ""
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def map_weapons(
    strengths: dict[str, float],
    *,
    evidence_reliability: float = 0.5,
    durability: float = 0.5,
    crowding: float = 0.0,
) -> WeaponMap:
    """WeaponScore = EdgeStrength × EvidenceReliability × Durability −
    CrowdingPenalty. An overused weapon is a strength that the market
    already leans on — predictability is attack surface."""
    normalized = {
        k: normalized_score(v) for k, v in (strengths or {}).items() if v
    }
    if not normalized:
        return WeaponMap(
            strongest_weapon="none_established",
            weapon_score=0.0,
            durability=0.0,
            overused=False,
            crowding_penalty=0.0,
            rationale=["no strengths supplied — no weapon, no edge"],
        )
    ranked = sorted(normalized.items(), key=lambda kv: -kv[1])
    name, strength = ranked[0]
    crowd = normalized_score(crowding)
    penalty = 0.5 * crowd
    score = clamp01(
        strength * normalized_score(evidence_reliability, 0.5)
        * (0.5 + 0.5 * normalized_score(durability, 0.5)) - penalty
    ) * 10.0
    overused = crowd >= 0.6 and strength >= 0.6
    rationale = [
        f"strongest weapon: {name} ({strength:.2f}); score "
        f"{score:.1f}/10 after reliability/durability/crowding",
    ]
    if overused:
        rationale.append(
            "weapon is strong AND crowded — a strong shot becomes a "
            "weakness when it becomes predictable"
        )
    return WeaponMap(
        strongest_weapon=name,
        weapon_score=score,
        durability=normalized_score(durability, 0.5),
        overused=overused,
        crowding_penalty=penalty,
        runner_up=ranked[1][0] if len(ranked) > 1 else "",
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Weak-Side Exposure + Minimum Viable Weakness
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class WeakSideReport:
    """Where the thesis can be attacked, and whether attacking pays."""

    top_weakness: str
    exposure_score: float
    attack_roi: float
    classification: str  # fatal | exploitable_manageable | above_threshold
    minimum_viable_pass: bool
    weaknesses: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_weak_side(
    weaknesses: dict[str, float],
    *,
    attack_probability: float = 0.5,
    cost_to_exploit: float = 0.5,
    improving: bool = False,
) -> WeakSideReport:
    """WeakSideExposure = severity × attack probability; AttackROI =
    expected opponent gain − cost to exploit. A weakness does not need to
    become a strength — it needs to become expensive to attack."""
    normalized = {
        k: normalized_score(v) for k, v in (weaknesses or {}).items()
    }
    if not normalized:
        return WeakSideReport(
            top_weakness="none_declared",
            exposure_score=0.0,
            attack_roi=0.0,
            classification="above_threshold",
            minimum_viable_pass=True,
            rationale=["no weaknesses declared — verify, do not assume"],
        )
    top_name, severity = max(normalized.items(), key=lambda kv: kv[1])
    attack_p = normalized_score(attack_probability, 0.5)
    cost = normalized_score(cost_to_exploit, 0.5)
    exposure = clamp01(severity * attack_p) * 10.0
    attack_roi = severity * attack_p - cost
    if improving:
        attack_roi -= 0.15  # an improving weakness raises the attacker's cost

    if severity >= 0.8 and attack_roi > 0.2:
        classification = "fatal"
    elif attack_roi > 0.0:
        classification = "exploitable_manageable"
    else:
        classification = "above_threshold"
    viable = classification != "fatal"

    rationale = [
        f"top weakness: {top_name} (severity {severity:.2f}); attack ROI "
        f"{attack_roi:+.2f} (gain {severity * attack_p:.2f} − cost {cost:.2f}"
        + (", improving −0.15" if improving else "") + ")",
        (
            "weakness is expensive to attack — minimum viable threshold met"
            if attack_roi <= 0
            else "opponents profit from targeting this — raise the floor"
        ),
    ]
    return WeakSideReport(
        top_weakness=top_name,
        exposure_score=exposure,
        attack_roi=attack_roi,
        classification=classification,
        minimum_viable_pass=viable,
        weaknesses=normalized,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Niche: beachhead vs cage
# ---------------------------------------------------------------------------

NICHE_CLASSES: tuple[str, ...] = (
    "beachhead", "profitable_cage", "one_product_fragility",
    "overvalued_niche_narrative", "underpriced_expansion_platform",
)


@dataclass(slots=True)
class NicheVerdict:
    classification: str
    niche_score: float
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_niche(
    *,
    dominance: float = 0.0,
    expansion_potential: float = 0.0,
    execution_proof: float = 0.0,
    concentration_risk: float = 0.0,
    valuation_expectation_risk: float = 0.0,
) -> NicheVerdict:
    """NicheScore = Dominance × ExpansionPotential − ConcentrationRisk −
    ValuationExpectationRisk. A niche is a beachhead only if expansion is
    both possible and evidenced; good company ≠ good stock."""
    dom = normalized_score(dominance)
    exp = normalized_score(expansion_potential)
    proof = normalized_score(execution_proof)
    conc = normalized_score(concentration_risk)
    val = normalized_score(valuation_expectation_risk)
    score = clip(dom * exp + 0.3 * proof - 0.4 * conc - 0.4 * val, -1.0, 1.0)

    if dom >= 0.5 and exp >= 0.5 and proof >= 0.4:
        classification = (
            "underpriced_expansion_platform" if val <= 0.3 else "beachhead"
        )
    elif dom >= 0.5 and exp < 0.35 and val >= 0.6:
        classification = "overvalued_niche_narrative"
    elif dom >= 0.5 and exp < 0.35:
        classification = "profitable_cage"
    elif conc >= 0.7:
        classification = "one_product_fragility"
    else:
        classification = "profitable_cage" if dom >= 0.4 else (
            "one_product_fragility"
        )

    rationale = [
        f"dominance {dom:.2f} × expansion {exp:.2f} + proof {proof:.2f} − "
        f"concentration {conc:.2f} − valuation expectations {val:.2f} "
        f"= {score:+.2f} -> {classification}",
    ]
    if classification in ("profitable_cage", "overvalued_niche_narrative"):
        rationale.append(
            "quality without expandability: a good company priced for a "
            "second act it has not shown"
        )
    return NicheVerdict(
        classification=classification, niche_score=score, rationale=rationale
    )


# ---------------------------------------------------------------------------
# Opponent Adaptation Index + market-awareness blind layers
# ---------------------------------------------------------------------------

OAI_STATES: tuple[str, ...] = (
    "fresh_edge", "partially_recognized", "crowded_edge", "exhausted_edge",
    "anti_consensus_opportunity",
)


@dataclass(slots=True)
class AdaptationVerdict:
    oai: float
    state: str
    market_awareness_layer: int  # 1 single / 2 double / 3 triple blind
    layer_reasoning: str
    live_edge_fraction: float
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_adaptation(
    *,
    signal_strength: float = 0.0,
    repricing_observed: float = 0.0,
    crowding: float = 0.0,
    narrative_saturation: float = 0.0,
    second_order_node_unpriced: bool = False,
    consensus_against: bool = False,
    recognition_age_days: float = 0.0,
    edge_half_life_days: float = 30.0,
) -> AdaptationVerdict:
    """OAI = (repricing + crowding + saturation) / signal strength.

    Layer 1 (single blind): market unaware — hidden pattern.
    Layer 2 (double blind): market aware, counter-position incomplete.
    Layer 3 (triple blind): obvious trade crowded AND a neglected
    second/third-order node exists — bait the variation.
    LiveEdge = e^(−ln2 · age / half_life): edge decays once recognized.
    """
    signal = max(normalized_score(signal_strength), 1e-6)
    repricing = normalized_score(repricing_observed)
    crowd = normalized_score(crowding)
    saturation = normalized_score(narrative_saturation)
    oai = clip(safe_div(repricing + crowd + saturation, 3.0 * signal), 0.0, 3.0)

    live = 0.5 ** (
        max(float(recognition_age_days), 0.0)
        / max(float(edge_half_life_days), 1e-6)
    )

    if consensus_against and signal >= 0.5:
        state = "anti_consensus_opportunity"
    elif oai < 0.35:
        state = "fresh_edge"
    elif oai < 0.7:
        state = "partially_recognized"
    elif oai < 1.1:
        state = "crowded_edge"
    else:
        state = "exhausted_edge"

    if state in ("fresh_edge", "anti_consensus_opportunity"):
        layer, reasoning = 1, (
            "single blind: the pattern is hidden — the market does not "
            "know we know"
        )
    elif state in ("crowded_edge", "exhausted_edge") and (
        second_order_node_unpriced
    ):
        layer, reasoning = 3, (
            "triple blind: the obvious trade is crowded, the counter is "
            "becoming known — the edge lives in the neglected second/"
            "third-order node"
        )
    elif state == "partially_recognized":
        layer, reasoning = 2, (
            "double blind: the pattern is mutually known — the game is "
            "variation and counter-positioning"
        )
    else:
        layer, reasoning = 0, (
            "no blind-layer edge: crowded/exhausted with no neglected node"
        )

    rationale = [
        f"OAI {oai:.2f} -> {state}; live edge fraction {live:.2f} after "
        f"{recognition_age_days:.0f}d of recognition "
        f"(half-life {edge_half_life_days:.0f}d)",
        reasoning,
    ]
    return AdaptationVerdict(
        oai=oai,
        state=state,
        market_awareness_layer=layer,
        layer_reasoning=reasoning,
        live_edge_fraction=live,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Catalyst + 1 and Complete Game
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CatalystPlusOne:
    catalyst: str
    expected_first_mover: str
    expected_lagging_node: str
    first_reaction_probability: float
    pre_positioning_value: float
    confirmation_needed: str
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def model_catalyst_plus_one(
    *,
    catalyst: str,
    first_mover: str = "",
    lagging_node: str = "",
    first_reaction_probability: float = 0.5,
    expected_lag_repricing: float = 0.0,
    current_lag_reaction: float = 0.0,
    false_signal_risk: float = 0.3,
    confirmation_needed: str = "",
) -> CatalystPlusOne:
    """The serve creates a predictable return; the catalyst creates a
    predictable first reaction. Pre-positioning value lives in the LAGGING
    node: PPV = E[future repricing] − current reaction − error risk."""
    p_first = normalized_score(first_reaction_probability, 0.5)
    ppv = clip(
        p_first * normalized_score(expected_lag_repricing)
        - normalized_score(current_lag_reaction)
        - 0.5 * normalized_score(false_signal_risk),
        -1.0,
        1.0,
    )
    rationale = [
        f"catalyst '{catalyst}': first reaction in "
        f"{first_mover or 'the obvious node'} (p={p_first:.2f}); "
        f"pre-positioning value in {lagging_node or 'the lagging node'} "
        f"= {ppv:+.2f}",
        "anticipation beats reaction — the obvious node moves first, the "
        "hidden linked node may pay better",
    ]
    return CatalystPlusOne(
        catalyst=str(catalyst),
        expected_first_mover=str(first_mover),
        expected_lagging_node=str(lagging_node),
        first_reaction_probability=p_first,
        pre_positioning_value=ppv,
        confirmation_needed=str(confirmation_needed),
        rationale=rationale,
    )


def complete_game_score(capabilities: dict[str, float]) -> dict[str, object]:
    """CGS = mean(capabilities) − variance penalty: high capability with
    low variance is a complete game; one tall spike is a narrow weapon."""
    values = [normalized_score(v) for v in (capabilities or {}).values()]
    if not values:
        return {"score": 0.0, "balanced": False,
                "note": "no capabilities supplied"}
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    score = clamp01(mean - 1.5 * variance) * 10.0
    balanced = variance < 0.04 and mean >= 0.5
    return {
        "score": round(score, 2),
        "mean_capability": round(mean, 3),
        "variance": round(variance, 4),
        "balanced": balanced,
        "note": (
            "complete game — hard to punish" if balanced else
            "segmented game — a complete opponent punishes the gaps"
        ),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def assess_adaptive_opponent(section: dict) -> dict[str, object]:
    """Run the mentor's questions over one ``opponent`` payload section."""
    weapons = map_weapons(
        dict(section.get("strengths") or {}),
        evidence_reliability=normalized_score(
            section.get("evidence_reliability", 0.5), 0.5
        ),
        durability=normalized_score(section.get("durability", 0.5), 0.5),
        crowding=normalized_score(section.get("crowding", 0.0)),
    )
    weak_side = assess_weak_side(
        dict(section.get("weaknesses") or {}),
        attack_probability=normalized_score(
            section.get("attack_probability", 0.5), 0.5
        ),
        cost_to_exploit=normalized_score(
            section.get("cost_to_exploit", 0.5), 0.5
        ),
        improving=bool(section.get("weakness_improving", False)),
    )
    niche_section = dict(section.get("niche") or {})
    niche = classify_niche(**{
        k: float(v) for k, v in niche_section.items()
        if k in classify_niche.__kwdefaults__
    })
    adaptation_section = dict(section.get("adaptation") or {})
    adaptation = assess_adaptation(**{
        k: v for k, v in adaptation_section.items()
        if k in assess_adaptation.__kwdefaults__
    })
    catalyst_section = dict(section.get("catalyst_plus_one") or {})
    catalyst = (
        model_catalyst_plus_one(**{
            k: v for k, v in catalyst_section.items()
            if k in model_catalyst_plus_one.__kwdefaults__ or k == "catalyst"
        })
        if catalyst_section.get("catalyst")
        else None
    )
    game = complete_game_score(dict(section.get("capabilities") or {}))

    return {
        "weapon_map": weapons.to_dict(),
        "weak_side": weak_side.to_dict(),
        "niche": niche.to_dict(),
        "adaptation": adaptation.to_dict(),
        "catalyst_plus_one": catalyst.to_dict() if catalyst else None,
        "complete_game": game,
        "advisory_status": "ADVISORY_ONLY",
    }
