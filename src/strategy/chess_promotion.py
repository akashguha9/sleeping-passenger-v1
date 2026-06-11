"""Dynamic Table System: a company is a current state plus possible
state transitions.

Piece states map to business archetypes (pawn/knight/bishop/rook/queen,
king as survival constraint). Promotion is option value; demotion is the
mirror risk; and self-declared queens are validated by evidence — the
fake-queen guard demotes "platforms" without retention, ecosystem,
network effects, and multi-vector mobility.

    Promotion_Adjusted_Value = p_promotion × payoff × time_discount
                               − blocker − dilution − execution
    Dynamic_Table_Score = current_strength + mobility
                          + promotion_value − demotion_risk

Distinct from ``scripts/chess_archetype_decision_layer.py``, which
classifies *signals*; this models *company* state transitions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import normalized_score

PIECE_STATES: tuple[str, ...] = (
    "pawn", "knight", "bishop", "rook", "queen", "king",
)

# Base strength of each piece state in [0, 1].
PIECE_STRENGTH: dict[str, float] = {
    "pawn": 0.15,
    "knight": 0.40,
    "bishop": 0.45,
    "rook": 0.65,
    "queen": 0.90,
    "king": 0.30,  # survival-critical constraint, not an attacker
}

VALID_PROMOTIONS: dict[str, tuple[str, ...]] = {
    "pawn": ("knight", "bishop", "rook", "queen"),
    "knight": ("queen",),
    "bishop": ("queen",),
    "rook": ("queen",),
    "queen": (),
    "king": (),
}

VALID_DEMOTIONS: dict[str, tuple[str, ...]] = {
    "queen": ("rook", "pawn"),
    "rook": ("pawn",),
    "bishop": ("pawn",),
    "knight": ("pawn",),
    "pawn": (),
    "king": (),
}

# Queen status must be earned by evidence, not self-labels.
QUEEN_EVIDENCE: tuple[str, ...] = (
    "network_effects", "ecosystem_control", "multi_vector_mobility",
    "retention",
)
QUEEN_EVIDENCE_FLOOR = 0.5


@dataclass(slots=True)
class ChessStateAssessment:
    """Dynamic-table verdict for one company."""

    current_piece_state: str
    declared_piece_state: str
    current_piece_confidence: float
    fake_queen_detected: bool
    current_piece_strength: float
    possible_promotion_paths: list[str] = field(default_factory=list)
    promotion_target: str = ""
    promotion_probability: float = 0.0
    promotion_payoff: float = 0.0
    promotion_adjusted_value: float = 0.0
    demotion_risk: float = 0.0
    piece_mobility_score: float = 0.0
    dynamic_table_score: float = 0.0
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate_queen(evidence: dict[str, float]) -> tuple[bool, list[str]]:
    """Queen status requires all four evidence pillars at the floor."""
    missing = [
        pillar
        for pillar in QUEEN_EVIDENCE
        if normalized_score(evidence.get(pillar, 0.0)) < QUEEN_EVIDENCE_FLOOR
    ]
    return (not missing), missing


def assess_chess_state(
    *,
    declared_state: str = "pawn",
    state_evidence: dict[str, float] | None = None,
    promotion_target: str = "",
    promotion_probability: float = 0.0,
    promotion_payoff: float = 0.0,
    promotion_timeframe_years: float = 3.0,
    blocker_risk: float = 0.0,
    dilution_risk: float = 0.0,
    execution_risk: float = 0.0,
    demotion_risk: float = 0.0,
    mobility: float = 0.0,
) -> ChessStateAssessment:
    """Score current state plus credible state transitions.

    ``state_evidence`` carries the pillars backing the declared state
    (for queens: network_effects, ecosystem_control,
    multi_vector_mobility, retention).
    """
    declared = str(declared_state).strip().lower()
    if declared not in PIECE_STATES:
        declared = "pawn"
    evidence = {k: normalized_score(v) for k, v in (state_evidence or {}).items()}

    rationale: list[str] = []
    state = declared
    fake_queen = False
    if declared == "queen":
        is_queen, missing = _validate_queen(evidence)
        if not is_queen:
            fake_queen = True
            # A failed queen with route control is a rook; otherwise bishop.
            state = "rook" if evidence.get("ecosystem_control", 0.0) >= 0.4 else "bishop"
            rationale.append(
                f"FAKE QUEEN: declared platform lacks {', '.join(missing)} — "
                f"reclassified as {state}"
            )

    evidence_mean = (
        sum(evidence.values()) / len(evidence) if evidence else 0.0
    )
    confidence = clamp01(0.4 + 0.6 * evidence_mean) if evidence else 0.3
    strength = PIECE_STRENGTH[state]

    target = str(promotion_target).strip().lower()
    valid_paths = list(VALID_PROMOTIONS[state])
    p_promotion = normalized_score(promotion_probability)
    payoff = normalized_score(promotion_payoff)
    if target and target not in valid_paths:
        rationale.append(
            f"promotion path {state} -> {target} is not a valid transition; "
            "option value voided"
        )
        target, p_promotion, payoff = "", 0.0, 0.0
    if not target and valid_paths and p_promotion > 0:
        rationale.append("promotion probability supplied without a target — voided")
        p_promotion, payoff = 0.0, 0.0

    # Time discount: 10% a year on the promotion option.
    years = max(float(promotion_timeframe_years), 0.0)
    time_discount = 0.9 ** years
    promotion_value = clamp01(
        p_promotion * payoff * time_discount
        - 0.3 * normalized_score(blocker_risk)
        - 0.3 * normalized_score(dilution_risk)
        - 0.3 * normalized_score(execution_risk)
    )

    demotion = normalized_score(demotion_risk)
    if state in ("queen", "rook") and demotion > 0:
        rationale.append(
            f"strong piece with demotion risk {demotion:.2f} — dominance is "
            "a state, not a property"
        )

    mobility_score = normalized_score(mobility)
    table_score = clip(
        strength + 0.3 * mobility_score + promotion_value - 0.5 * demotion,
        0.0,
        2.0,
    ) / 2.0 * 10.0

    if state == "pawn" and promotion_value > 0.2:
        rationale.append(
            "pawn with credible promotion path — option value carries the "
            "thesis (a pawn nearing promotion can outrank a static bishop)"
        )
    if state == "pawn" and promotion_value == 0.0:
        rationale.append("pawn with no credible promotion path — static weakness")

    return ChessStateAssessment(
        current_piece_state=state,
        declared_piece_state=declared,
        current_piece_confidence=confidence,
        fake_queen_detected=fake_queen,
        current_piece_strength=strength,
        possible_promotion_paths=valid_paths,
        promotion_target=target,
        promotion_probability=p_promotion,
        promotion_payoff=payoff,
        promotion_adjusted_value=promotion_value,
        demotion_risk=demotion,
        piece_mobility_score=mobility_score,
        dynamic_table_score=table_score,
        rationale=rationale,
    )
