"""Game Archetype Classifier: identify the game before choosing the move.

Eight archetypes, each a different decision environment with its own
signal-interpretation weights — the same signal means different things in
different games (a hot narrative is fuel in a SHASN game and a hazard in
a Pallanguzhi game). A thesis is a NESTED STACK: one game per layer
(macro / sector / company / signal / reality), never a single label.

Weak feature matches stay unclassified — forcing an archetype onto thin
features is the metaphor-overfit failure mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

# Archetype -> (weighted feature signature, decision-environment summary,
# signal interpretation modifiers). Features are normalized [0, 1] thesis
# characteristics supplied by the operator/pipeline.
GAME_SIGNATURES: dict[str, dict[str, object]] = {
    "snakes_and_ladders": {
        "features": {"exogenous_shock_dependence": 0.5,
                     "binary_event_exposure": 0.3, "path_dependence": 0.2},
        "environment": "fate: exogenous shocks, catalysts, traps; almost "
                       "no meaningful move choice",
        "interpretation": {"narrative_weight": 0.6, "fundamental_weight": 0.8,
                           "catalyst_weight": 1.4, "hyperreality_amplifier": 1.0},
    },
    "ludo": {
        "features": {"optionality_after_signal": 0.4, "position_choice": 0.3,
                     "capture_opportunities": 0.3},
        "environment": "stochastic strategy: randomness creates options, "
                       "the edge is the choice after the roll",
        "interpretation": {"narrative_weight": 0.9, "fundamental_weight": 1.0,
                           "catalyst_weight": 1.1, "hyperreality_amplifier": 1.0},
    },
    "chaturanga": {
        "features": {"competitive_intensity": 0.5, "moat_contest": 0.3,
                     "counter_move_exposure": 0.2},
        "environment": "pure strategy: minimax, moats, competitor response",
        "interpretation": {"narrative_weight": 0.7, "fundamental_weight": 1.2,
                           "catalyst_weight": 0.9, "hyperreality_amplifier": 1.0},
    },
    "bagh_bandi": {
        "features": {"power_asymmetry": 0.4, "containment_pressure": 0.35,
                     "coordination_dynamics": 0.25},
        "environment": "predator-prey: power vs mobility vs coordination "
                       "(incumbent/startup, regulator/company, short/crowd)",
        "interpretation": {"narrative_weight": 0.8, "fundamental_weight": 1.0,
                           "catalyst_weight": 1.0, "hyperreality_amplifier": 1.1},
    },
    "pallanguzhi": {
        "features": {"cash_flow_centrality": 0.45, "working_capital_cycles": 0.3,
                     "supply_chain_flow": 0.25},
        "environment": "resource flow: cash conversion, inventory, "
                       "balance-sheet circulation",
        "interpretation": {"narrative_weight": 0.5, "fundamental_weight": 1.4,
                           "catalyst_weight": 0.8, "hyperreality_amplifier": 1.3},
    },
    "carrom": {
        "features": {"execution_sensitivity": 0.5, "liquidity_constraints": 0.3,
                     "timing_criticality": 0.2},
        "environment": "execution: a good thesis can still fail through "
                       "slippage, timing, and liquidity",
        "interpretation": {"narrative_weight": 0.7, "fundamental_weight": 1.0,
                           "catalyst_weight": 1.0, "hyperreality_amplifier": 1.0},
    },
    "shasn": {
        "features": {"regulatory_exposure": 0.4, "narrative_dependence": 0.3,
                     "coalition_dynamics": 0.3},
        "environment": "politics: regulation, coalitions, constituencies, "
                       "narrative as a resource",
        "interpretation": {"narrative_weight": 1.3, "fundamental_weight": 0.8,
                           "catalyst_weight": 1.2, "hyperreality_amplifier": 1.2},
    },
    "simulacra": {
        "features": {"belief_about_belief": 0.45, "reflexivity": 0.3,
                     "narrative_dependence": 0.25},
        "environment": "hyperreality: price moves on belief about belief; "
                       "the scoreboard may be more real than the game",
        "interpretation": {"narrative_weight": 1.4, "fundamental_weight": 0.6,
                           "catalyst_weight": 1.0, "hyperreality_amplifier": 1.5},
    },
}

GAME_ARCHETYPES: tuple[str, ...] = tuple(GAME_SIGNATURES)
THESIS_LAYERS: tuple[str, ...] = (
    "macro", "sector", "company", "signal", "reality",
)
MIN_GAME_CONFIDENCE = 0.30


@dataclass(slots=True)
class GameClassification:
    """One layer's classified decision environment."""

    layer: str
    game: str
    confidence: float
    environment: str
    interpretation: dict[str, float] = field(default_factory=dict)
    runner_up: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class GameStack:
    """The nested-games verdict: one game per thesis layer."""

    layers: list[GameClassification] = field(default_factory=list)
    dominant_game: str = "unclassified"
    blended_interpretation: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["layers"] = [l.to_dict() for l in self.layers]
        return payload


def classify_game(
    features: dict[str, float], *, layer: str = "company"
) -> GameClassification:
    """Classify one layer's decision environment from its features."""
    normalized = {k: normalized_score(v) for k, v in (features or {}).items()}
    scores: dict[str, float] = {}
    for game, signature in GAME_SIGNATURES.items():
        weights: dict[str, float] = signature["features"]  # type: ignore[assignment]
        scores[game] = sum(
            weight * normalized.get(feature, 0.0)
            for feature, weight in weights.items()
        )
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    runner_up, second_score = ranked[1]
    separation = clamp01(
        (best_score - second_score) / max(best_score, 1e-9)
    )
    confidence = clamp01(best_score * (0.6 + 0.4 * separation))

    if confidence < MIN_GAME_CONFIDENCE:
        return GameClassification(
            layer=str(layer),
            game="unclassified",
            confidence=confidence,
            environment="insufficient features to name the game — refusing "
                        "to force an archetype (metaphor-overfit guard)",
            interpretation={"narrative_weight": 1.0, "fundamental_weight": 1.0,
                            "catalyst_weight": 1.0,
                            "hyperreality_amplifier": 1.0},
        )

    signature = GAME_SIGNATURES[best]
    return GameClassification(
        layer=str(layer),
        game=best,
        confidence=confidence,
        environment=str(signature["environment"]),
        interpretation=dict(signature["interpretation"]),  # type: ignore[arg-type]
        runner_up=runner_up if second_score >= 0.2 else "",
    )


def classify_game_stack(
    layer_features: dict[str, dict[str, float]],
) -> GameStack:
    """Classify every supplied thesis layer; blend interpretation weights.

    ``layer_features`` maps layer name (macro/sector/company/signal/
    reality) to that layer's feature dict. Blending is confidence-weighted
    so an uncertain layer pulls interpretation toward neutral 1.0.
    """
    layers: list[GameClassification] = []
    for layer in THESIS_LAYERS:
        features = (layer_features or {}).get(layer)
        if isinstance(features, dict) and features:
            layers.append(classify_game(features, layer=layer))

    if not layers:
        return GameStack(
            rationale=["no layer features supplied — game stack empty; "
                       "interpretation stays neutral"],
        )

    classified = [l for l in layers if l.game != "unclassified"]
    dominant = (
        max(classified, key=lambda l: l.confidence).game
        if classified else "unclassified"
    )

    # Confidence-weighted blend of interpretation modifiers; missing
    # confidence dilutes toward neutral.
    keys = ("narrative_weight", "fundamental_weight", "catalyst_weight",
            "hyperreality_amplifier")
    blended: dict[str, float] = {}
    for key in keys:
        weighted = sum(
            l.confidence * l.interpretation.get(key, 1.0) for l in layers
        )
        total_confidence = sum(l.confidence for l in layers)
        neutral_mass = max(len(layers) - total_confidence, 0.0)
        blended[key] = round(
            (weighted + neutral_mass * 1.0) / len(layers), 4
        )

    rationale = [
        "nested game stack: "
        + ", ".join(f"{l.layer}={l.game}({l.confidence:.2f})" for l in layers),
        f"dominant game: {dominant}; the same signal is interpreted "
        "through the blended game weights, not absolutely",
    ]
    return GameStack(
        layers=layers,
        dominant_game=dominant,
        blended_interpretation=blended,
        rationale=rationale,
    )
