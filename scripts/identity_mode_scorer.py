from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def classify_identity_mode(features: Mapping[str, float]) -> dict[str, Any]:
    identity = float(features.get("identity_signal_score", 0.0))
    validation = float(features.get("validation_score", 0.0))
    engagement = float(features.get("engagement_feedback", 0.0))
    information_ratio = float(features.get("information_ratio", 0.0))
    consequence = float(features.get("consequence_coupling", 0.0))

    if identity < 0.15 and max(validation, information_ratio, consequence) >= 0.35:
        label = "epistemic"
        confidence = _clamp(_average([max(validation, information_ratio), consequence or validation]))
    elif identity >= 0.30 and engagement >= 0.35:
        label = "identity_signaling"
        confidence = _clamp(_average([identity, engagement]))
    elif identity >= 0.18 and (validation >= 0.20 or engagement >= 0.25):
        label = "mixed"
        confidence = _clamp(_average([identity, max(validation, engagement)]))
    else:
        label = "unknown"
        confidence = _clamp(max(identity, validation, engagement) * 0.75)

    return {
        "label": label,
        "confidence": round(confidence, 3),
        "score": round(identity, 3),
    }


@dataclass(frozen=True)
class IdentityModeAssessment:
    schema_version: str
    identity_mode: dict[str, Any]
    supporting_signals: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_identity_mode_assessment(
    *,
    supporting_features: Mapping[str, float],
) -> dict[str, Any]:
    assessment = IdentityModeAssessment(
        schema_version="v1",
        identity_mode=classify_identity_mode(supporting_features),
        supporting_signals={
            "identity_signal_score": round(float(supporting_features.get("identity_signal_score", 0.0)), 3),
            "validation_score": round(float(supporting_features.get("validation_score", 0.0)), 3),
            "engagement_feedback": round(float(supporting_features.get("engagement_feedback", 0.0)), 3),
            "information_ratio": round(float(supporting_features.get("information_ratio", 0.0)), 3),
            "consequence_coupling": round(float(supporting_features.get("consequence_coupling", 0.0)), 3),
        },
    )
    return assessment.to_dict()
