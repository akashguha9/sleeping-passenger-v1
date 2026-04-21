from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping, Sequence

try:
    from scripts.ambiguity_scorer import build_ambiguity_analysis
except ModuleNotFoundError:
    from ambiguity_scorer import build_ambiguity_analysis

TEXT_FIELDS = ("text", "title", "summary", "question")
ANCHOR_SOURCES = {"kalshi", "polymarket", "market_data"}
ENGAGEMENT_SOURCES = {"praw_reddit", "grok_x"}
INFORMATION_SOURCES = {"feedparser", "newspaper3k"}

ENGAGEMENT_PATTERNS = {
    "thoughts", "agree", "disagree", "comment", "reply", "share",
    "hot take", "drop", "viral", "debate", "what do you think",
}
IDENTITY_PATTERNS = {
    "leaders", "founders", "smart people", "real traders", "serious investors",
    "high iq", "winners", "losers", "alpha", "cope", "virtue",
}
CONTROVERSY_PATTERNS = {
    "fake", "fraud", "scam", "outrage", "controversial", "disaster",
    "rigged", "broken", "idiot", "insane", "bubble",
}
LEARNING_PATTERNS = {
    "how", "why", "explain", "guide", "lesson", "learn", "walkthrough",
    "breakdown", "analysis", "framework",
}
CONVERSION_PATTERNS = {
    "buy", "sell", "join", "subscribe", "sign up", "register",
    "click", "follow", "enter now",
}
HOOK_PATTERNS = {
    "inevitable", "unstoppable", "massive", "explosive", "panic", "squeeze",
    "trap", "comeback", "scandal", "reversal",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


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


def _source_ratio(signals: Sequence[Mapping[str, Any]], sources: set[str]) -> float:
    if not signals:
        return 0.0
    hits = sum(1 for signal in signals if str(signal.get("source") or "").lower() in sources)
    return _clamp(hits / len(signals))


def _validation_structure_score(signals: Sequence[Mapping[str, Any]], runtime_context: Mapping[str, Any]) -> float:
    hits = 0.0
    for signal in signals:
        content = signal.get("content") or {}
        if any(content.get(field) is not None for field in ("yes_price", "probability", "implied_probability")):
            hits += 1.0
        if content.get("outcome_prices") is not None:
            hits += 1.0
        if any(content.get(field) is not None for field in ("market_id", "condition_id", "price", "volatility")):
            hits += 0.5
    if str(runtime_context.get("pre_entry_state") or "NONE").upper() != "NONE":
        hits += 1.0
    if str(runtime_context.get("policy_state") or "UNKNOWN").upper() != "UNKNOWN":
        hits += 0.5
    return _clamp(hits / max(len(signals) + 1.5, 1.0))


def _engagement_feedback_score(signals: Sequence[Mapping[str, Any]]) -> float:
    samples: list[float] = []
    for signal in signals:
        content = signal.get("content") or {}
        score = _safe_float(content.get("score")) or 0.0
        comments = _safe_float(content.get("num_comments")) or 0.0
        engagement = _safe_float(content.get("engagement")) or 0.0
        volume = _safe_float(content.get("volume")) or 0.0
        samples.append(
            max(
                score / 1000.0,
                comments / 250.0,
                engagement / 10000.0,
                volume / 200000.0,
            )
        )
    return _clamp(max(samples, default=0.0))


def _identity_signal_score(text: str) -> float:
    pronoun_density = _clamp(len(re.findall(r"\b(i|we|they|real|smart|elite|serious)\b", text)) / 8.0)
    pattern_density = _normalized_count(text, IDENTITY_PATTERNS, 4.0)
    return _clamp((pronoun_density * 0.45) + (pattern_density * 0.55))


def _consequence_coupling_score(signals: Sequence[Mapping[str, Any]], runtime_context: Mapping[str, Any]) -> float:
    score = 0.0
    if bool(runtime_context.get("has_open_position")):
        score += 0.35
    if str(runtime_context.get("pre_entry_state") or "NONE").upper() != "NONE":
        score += 0.25
    if str(runtime_context.get("policy_state") or "UNKNOWN").upper() != "UNKNOWN":
        score += 0.15
    if _source_ratio(signals, ANCHOR_SOURCES) > 0:
        score += 0.15
    if _validation_structure_score(signals, runtime_context) > 0.5:
        score += 0.10
    return _clamp(score)


def _class_scores(signals: Sequence[Mapping[str, Any]], runtime_context: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    text = _joined_text(signals)
    anchor_ratio = _source_ratio(signals, ANCHOR_SOURCES)
    engagement_ratio = _source_ratio(signals, ENGAGEMENT_SOURCES)
    information_ratio = _source_ratio(signals, INFORMATION_SOURCES)
    validation_score = _validation_structure_score(signals, runtime_context)
    engagement_feedback = _engagement_feedback_score(signals)
    identity_score = _identity_signal_score(text)
    hook_density = _normalized_count(text, HOOK_PATTERNS, 5.0)
    cta_density = _normalized_count(text, ENGAGEMENT_PATTERNS | CONVERSION_PATTERNS, 5.0)
    controversy_score = _normalized_count(text, CONTROVERSY_PATTERNS, 4.0)
    learning_score = _normalized_count(text, LEARNING_PATTERNS, 4.0)
    consequence_coupling = _consequence_coupling_score(signals, runtime_context)
    ambiguity_analysis = build_ambiguity_analysis(
        signals,
        supporting_features={
            "validation_score": validation_score,
            "engagement_feedback": engagement_feedback,
            "identity_signal_score": identity_score,
            "cta_density": cta_density,
            "controversy_score": controversy_score,
            "consequence_coupling": consequence_coupling,
        },
    )
    ambiguity_score = float(ambiguity_analysis["supporting_signals"]["ambiguity_score"])

    official = _clamp(
        validation_score * 0.35
        + anchor_ratio * 0.25
        + consequence_coupling * 0.20
        + learning_score * 0.10
        + (1.0 - engagement_feedback) * 0.10
    )
    unofficial = _clamp(
        engagement_feedback * 0.25
        + engagement_ratio * 0.20
        + ambiguity_score * 0.15
        + identity_score * 0.15
        + cta_density * 0.15
        + controversy_score * 0.10
    )
    hybrid = _clamp(min(official, unofficial) * 1.3 + anchor_ratio * engagement_ratio * 0.4)
    unknown = _clamp(0.55 - max(official, unofficial, hybrid))

    classes = {
        "official_correctness_system": round(official, 3),
        "unofficial_engagement_system": round(unofficial, 3),
        "hybrid_system": round(hybrid, 3),
        "unknown": round(unknown, 3),
    }
    features = {
        "anchor_ratio": round(anchor_ratio, 3),
        "engagement_ratio": round(engagement_ratio, 3),
        "information_ratio": round(information_ratio, 3),
        "validation_score": round(validation_score, 3),
        "engagement_feedback": round(engagement_feedback, 3),
        "ambiguity_score": round(ambiguity_score, 3),
        "identity_signal_score": round(identity_score, 3),
        "hook_density": round(hook_density, 3),
        "cta_density": round(cta_density, 3),
        "controversy_score": round(controversy_score, 3),
        "learning_signal_score": round(learning_score, 3),
        "consequence_coupling": round(consequence_coupling, 3),
        "ambiguity_analysis": ambiguity_analysis,
    }
    return classes, features


def _objective_scores(
    classes: Mapping[str, float],
    features: Mapping[str, float],
) -> dict[str, float]:
    validation = float(features["validation_score"])
    ambiguity = float(features["ambiguity_score"])
    engagement_feedback = float(features["engagement_feedback"])
    identity_signal = float(features["identity_signal_score"])
    cta_density = float(features["cta_density"])
    controversy = float(features["controversy_score"])
    learning_signal = float(features["learning_signal_score"])
    consequence_coupling = float(features["consequence_coupling"])
    anchor_ratio = float(features["anchor_ratio"])
    hook_density = float(features["hook_density"])
    information_ratio = float(features["information_ratio"])

    scores = {
        "correctness": _clamp(validation * 0.45 + anchor_ratio * 0.20 + consequence_coupling * 0.20 + (1.0 - ambiguity) * 0.15),
        "learning": _clamp(learning_signal * 0.55 + information_ratio * 0.25 + (1.0 - identity_signal) * 0.20),
        "engagement": _clamp(engagement_feedback * 0.35 + cta_density * 0.20 + ambiguity * 0.15 + float(classes["unofficial_engagement_system"]) * 0.30),
        "identity_signaling": _clamp(identity_signal * 0.45 + controversy * 0.15 + cta_density * 0.15 + float(classes["unofficial_engagement_system"]) * 0.25),
        "controversy": _clamp(controversy * 0.45 + ambiguity * 0.20 + identity_signal * 0.15 + hook_density * 0.20),
        "retention": _clamp(engagement_feedback * 0.30 + cta_density * 0.20 + hook_density * 0.20 + ambiguity * 0.10 + float(classes["hybrid_system"]) * 0.20),
        "conversion": _clamp(cta_density * 0.45 + hook_density * 0.20 + consequence_coupling * 0.20 + validation * 0.15),
        "distribution": _clamp(hook_density * 0.35 + engagement_feedback * 0.20 + ambiguity * 0.15 + cta_density * 0.15 + float(classes["unofficial_engagement_system"]) * 0.15),
        "decision_usefulness": _clamp(consequence_coupling * 0.35 + validation * 0.25 + anchor_ratio * 0.20 + float(classes["official_correctness_system"]) * 0.20),
    }
    return {key: round(value, 3) for key, value in scores.items()}


def _dominant_label(scores: Mapping[str, float]) -> tuple[str, float]:
    if not scores:
        return "unknown", 0.0
    label = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
    return label, float(scores[label])


def _classification_label(scores: Mapping[str, float]) -> tuple[str, float]:
    official = float(scores.get("official_correctness_system", 0.0))
    unofficial = float(scores.get("unofficial_engagement_system", 0.0))
    hybrid = float(scores.get("hybrid_system", 0.0))
    if hybrid >= 0.45 or (official >= 0.35 and unofficial >= 0.35):
        return "hybrid_system", hybrid
    if official >= 0.40 and official >= unofficial + 0.10:
        return "official_correctness_system", official
    if unofficial >= 0.40 and unofficial >= official + 0.10:
        return "unofficial_engagement_system", unofficial
    return _dominant_label(scores)

def _identity_mode(features: Mapping[str, float]) -> dict[str, Any]:
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
class BehavioralForensicsOutput:
    schema_version: str
    entity_id: str
    system_classification: dict[str, Any]
    hidden_objective: dict[str, Any]
    ambiguity_analysis: dict[str, Any]
    ambiguity_type: dict[str, Any]
    identity_mode: dict[str, Any]
    supporting_signals: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_behavioral_forensics_output(
    signals: Sequence[Mapping[str, Any]],
    *,
    entity_id: str,
    runtime_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_context = dict(runtime_context or {})
    classes, features = _class_scores(signals, resolved_context)
    dominant_class, class_confidence = _classification_label(classes)
    objective_scores = _objective_scores(classes, features)
    dominant_objective, objective_confidence = _dominant_label(objective_scores)
    ambiguity_analysis = dict(features["ambiguity_analysis"])

    evidence: list[str] = []
    if features["validation_score"] >= 0.5:
        evidence.append("explicit validation structure detected")
    if features["engagement_feedback"] >= 0.4:
        evidence.append("high engagement-loop density detected")
    if features["ambiguity_score"] >= 0.35:
        evidence.append("ambiguity-rich prompt structure detected")
    if features["identity_signal_score"] >= 0.3:
        evidence.append("identity-signaling cues detected")
    if features["consequence_coupling"] >= 0.4:
        evidence.append("runtime consequence coupling detected")

    output = BehavioralForensicsOutput(
        schema_version="v1",
        entity_id=str(entity_id).upper(),
        system_classification={
            "label": dominant_class,
            "confidence": round(class_confidence, 3),
            "scores": classes,
            "evidence": evidence,
        },
        hidden_objective={
            "label": dominant_objective,
            "confidence": round(objective_confidence, 3),
            "scores": objective_scores,
        },
        ambiguity_analysis=ambiguity_analysis,
        ambiguity_type=dict(ambiguity_analysis["ambiguity_type"]),
        identity_mode=_identity_mode(features),
        supporting_signals={
            key: value for key, value in features.items() if key != "ambiguity_analysis"
        },
    )
    return output.to_dict()
