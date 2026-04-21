from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def classify_behavioral_heat(features: Mapping[str, float]) -> dict[str, Any]:
    engagement = float(features.get("engagement_feedback", 0.0))
    cta_density = float(features.get("cta_density", 0.0))
    controversy = float(features.get("controversy_score", 0.0))
    question_density = float(features.get("question_density", 0.0))
    open_end_density = float(features.get("open_end_density", 0.0))
    identity = float(features.get("identity_signal_score", 0.0))
    validation = float(features.get("validation_score", 0.0))
    consequence = float(features.get("consequence_coupling", 0.0))

    heat_score = _clamp(
        engagement * 0.18
        + cta_density * 0.24
        + controversy * 0.18
        + question_density * 0.06
        + open_end_density * 0.14
        + identity * 0.20
    )
    amplification_cues = max(cta_density, controversy, open_end_density, identity, question_density * 0.5)
    if validation >= 0.55 and consequence >= 0.35 and amplification_cues < 0.18:
        heat_score = _clamp(heat_score * 0.55)
    elif validation >= 0.45 and amplification_cues < 0.12:
        heat_score = _clamp(heat_score * 0.70)

    if heat_score < 0.18:
        label = "low_heat"
        confidence = _clamp(0.72 + (0.18 - heat_score))
    elif heat_score < 0.38:
        label = "elevated_heat"
        confidence = _clamp(_average([heat_score, max(engagement, cta_density, controversy)]))
    elif heat_score < 0.62:
        label = "high_heat"
        confidence = _clamp(_average([heat_score, engagement, max(cta_density, controversy, identity)]))
    else:
        label = "extreme_heat"
        confidence = _clamp(
            _average([heat_score, engagement, max(cta_density, controversy), max(open_end_density, question_density)])
        )

    return {
        "label": label,
        "confidence": round(confidence, 3),
        "score": round(heat_score, 3),
    }


@dataclass(frozen=True)
class BehavioralHeatAssessment:
    schema_version: str
    behavioral_heat: dict[str, Any]
    supporting_signals: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_behavioral_heat_assessment(
    *,
    supporting_features: Mapping[str, float],
) -> dict[str, Any]:
    assessment = BehavioralHeatAssessment(
        schema_version="v1",
        behavioral_heat=classify_behavioral_heat(supporting_features),
        supporting_signals={
            "engagement_feedback": round(float(supporting_features.get("engagement_feedback", 0.0)), 3),
            "cta_density": round(float(supporting_features.get("cta_density", 0.0)), 3),
            "controversy_score": round(float(supporting_features.get("controversy_score", 0.0)), 3),
            "question_density": round(float(supporting_features.get("question_density", 0.0)), 3),
            "open_end_density": round(float(supporting_features.get("open_end_density", 0.0)), 3),
            "identity_signal_score": round(float(supporting_features.get("identity_signal_score", 0.0)), 3),
        },
    )
    return assessment.to_dict()
