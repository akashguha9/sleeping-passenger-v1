from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


TEXT_FIELDS = ("text", "title", "summary", "question")
OPEN_END_PATTERNS = {
    "what do you think",
    "who wins",
    "is this",
    "are we",
    "could this",
    "maybe",
    "perhaps",
    "thoughts",
    "debate",
    "argue",
    "disagree",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _signal_texts(signal: Mapping[str, Any]) -> list[str]:
    content = signal.get("content") or {}
    texts: list[str] = []
    for field in TEXT_FIELDS:
        value = content.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            texts.append(text)
    return texts


def _joined_text(signals: Sequence[Mapping[str, Any]]) -> str:
    texts: list[str] = []
    for signal in signals:
        texts.extend(_signal_texts(signal))
    return " ".join(texts).lower()


def _normalized_count(text: str, patterns: set[str], normalizer: float) -> float:
    hits = sum(1 for pattern in patterns if pattern in text)
    return _clamp(hits / max(normalizer, 1.0))


def _raw_ambiguity_components(signals: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    text = _joined_text(signals)
    question_marks = text.count("?")
    open_end_hits = _normalized_count(text, OPEN_END_PATTERNS, 4.0)
    multi_outcome_hits = 0.0
    for signal in signals:
        content = signal.get("content") or {}
        if isinstance(content.get("outcome_prices"), dict) and len(content["outcome_prices"]) > 2:
            multi_outcome_hits += 1.0
        if content.get("question") and " or " in str(content.get("question")).lower():
            multi_outcome_hits += 0.5
    question_density = _clamp(question_marks / 4.0)
    multi_interpretation_score = _clamp(multi_outcome_hits / 2.0)
    ambiguity_score = _clamp(
        question_density * 0.35
        + open_end_hits * 0.45
        + multi_interpretation_score * 0.20
    )
    return {
        "question_density": round(question_density, 3),
        "open_end_density": round(open_end_hits, 3),
        "multi_interpretation_score": round(multi_interpretation_score, 3),
        "ambiguity_score": round(ambiguity_score, 3),
    }


def classify_ambiguity_type(features: Mapping[str, float]) -> dict[str, Any]:
    ambiguity = float(features.get("ambiguity_score", 0.0))
    validation = float(features.get("validation_score", 0.0))
    engagement = float(features.get("engagement_feedback", 0.0))
    identity = float(features.get("identity_signal_score", 0.0))
    cta_density = float(features.get("cta_density", 0.0))
    controversy = float(features.get("controversy_score", 0.0))
    consequence = float(features.get("consequence_coupling", 0.0))

    if ambiguity < 0.15:
        label = "low_ambiguity"
        confidence = _clamp(0.70 + (0.15 - ambiguity))
    elif validation >= 0.45 and consequence >= 0.30 and engagement < 0.45:
        label = "productive_ambiguity"
        confidence = _clamp(_average([ambiguity, validation, consequence]))
    elif engagement >= 0.45 and max(cta_density, identity, controversy) >= 0.20:
        label = "manipulative_ambiguity"
        confidence = _clamp(_average([ambiguity, engagement, max(cta_density, identity, controversy)]))
    else:
        label = "unresolved_ambiguity"
        confidence = _clamp(_average([ambiguity, 1.0 - abs(validation - engagement)]))

    return {
        "label": label,
        "confidence": round(confidence, 3),
        "score": round(ambiguity, 3),
    }


@dataclass(frozen=True)
class AmbiguityAnalysis:
    schema_version: str
    ambiguity_type: dict[str, Any]
    supporting_signals: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_ambiguity_analysis(
    signals: Sequence[Mapping[str, Any]],
    *,
    supporting_features: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    base_components = _raw_ambiguity_components(signals)
    merged_features = dict(supporting_features or {})
    merged_features["ambiguity_score"] = float(base_components["ambiguity_score"])
    analysis = AmbiguityAnalysis(
        schema_version="v1",
        ambiguity_type=classify_ambiguity_type(merged_features),
        supporting_signals={
            **base_components,
            "validation_score": round(float(merged_features.get("validation_score", 0.0)), 3),
            "engagement_feedback": round(float(merged_features.get("engagement_feedback", 0.0)), 3),
            "identity_signal_score": round(float(merged_features.get("identity_signal_score", 0.0)), 3),
            "cta_density": round(float(merged_features.get("cta_density", 0.0)), 3),
            "controversy_score": round(float(merged_features.get("controversy_score", 0.0)), 3),
            "consequence_coupling": round(float(merged_features.get("consequence_coupling", 0.0)), 3),
        },
    )
    return analysis.to_dict()
