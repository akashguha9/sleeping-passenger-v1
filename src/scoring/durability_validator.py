"""Durability scoring for signals that must survive beyond the first spike."""

from __future__ import annotations

from src.models.market import MarketSnapshot
from src.models.scores import ScoreResult
from src.utils.math_utils import clip
from src.utils.validation_utils import normalized_score


def score_durability(snapshot: MarketSnapshot | dict[str, object]) -> ScoreResult:
    """Compute DS.

    DS = clip(
        0.25 * Persistence
      + 0.25 * StressSurvival
      + 0.20 * CrossSourceConfirmation
      + 0.15 * TimeStability
      + 0.15 * ContradictionResistance,
      0, 1
    )
    """
    payload = snapshot.to_dict() if isinstance(snapshot, MarketSnapshot) else dict(snapshot)
    persistence = normalized_score(payload.get("persistence", 0.0))
    stress_survival = normalized_score(payload.get("stress_survival", 0.0))
    confirmation = normalized_score(payload.get("cross_source_confirmation", 0.0))
    stability = normalized_score(payload.get("time_stability", 0.0))
    contradiction_resistance = normalized_score(payload.get("contradiction_resistance", 0.0))
    score = clip(
        0.25 * persistence
        + 0.25 * stress_survival
        + 0.20 * confirmation
        + 0.15 * stability
        + 0.15 * contradiction_resistance,
        0.0,
        1.0,
    )
    reasons: list[str] = []
    if score >= 0.60:
        reasons.append("DURABLE_SIGNAL")
    if score < 0.45:
        reasons.append("LOW_DURABILITY")
    if persistence < 0.35 and stability < 0.35:
        reasons.append("ONE_SHOT_SPIKE")
    return ScoreResult(
        score=score,
        explanation=f"DS={score:.3f} from persistence {persistence:.2f} and stress survival {stress_survival:.2f}.",
        reason_codes=reasons,
        raw_components={
            "persistence": persistence,
            "stress_survival": stress_survival,
            "cross_source_confirmation": confirmation,
            "time_stability": stability,
            "contradiction_resistance": contradiction_resistance,
        },
    )
