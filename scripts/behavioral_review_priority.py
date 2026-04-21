from __future__ import annotations

from typing import Any, Mapping, Sequence

try:
    from scripts.runtime_common import (
        BEHAVIORAL_REVIEW_PRIORITY_REPORT_PATH,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        BEHAVIORAL_REVIEW_PRIORITY_REPORT_PATH,
        write_json_atomic,
    )


SCHEMA_VERSION = "v1"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _count_values(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _count_flags(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for flag in row.get("attention_flags") or []:
            text = str(flag or "").upper()
            if not text:
                continue
            counts[text] = counts.get(text, 0) + 1
    return counts


def _review_priority(
    *,
    behavioral_label: str,
    hidden_objective: str,
    ambiguity_type: str,
    identity_mode: str,
    behavioral_heat: Mapping[str, Any],
) -> dict[str, Any]:
    heat_score = float(behavioral_heat.get("score", 0.0) or 0.0)
    heat_confidence = float(behavioral_heat.get("confidence", 0.0) or 0.0)
    score = heat_score * 0.45

    if behavioral_label == "unofficial_engagement_system":
        score += 0.18
    elif behavioral_label == "hybrid_system":
        score += 0.10

    if hidden_objective == "engagement":
        score += 0.18
    elif hidden_objective == "controversy":
        score += 0.16
    elif hidden_objective == "identity_signaling":
        score += 0.15
    elif hidden_objective == "distribution":
        score += 0.12
    elif hidden_objective == "conversion":
        score += 0.10

    if ambiguity_type == "manipulative_ambiguity":
        score += 0.15
    elif ambiguity_type == "unresolved_ambiguity":
        score += 0.08
    elif ambiguity_type == "productive_ambiguity":
        score += 0.05

    if identity_mode == "identity_signaling":
        score += 0.12
    elif identity_mode == "mixed":
        score += 0.06

    score = _clamp(score)
    if score >= 0.75:
        label = "urgent_review"
    elif score >= 0.50:
        label = "priority_review"
    elif score >= 0.25:
        label = "elevated_review"
    else:
        label = "routine_review"

    return {
        "label": label,
        "confidence": round(_clamp((heat_confidence * 0.60) + (score * 0.40)), 3),
        "score": round(score, 3),
    }


def _attention_flags(
    *,
    behavioral_label: str,
    hidden_objective: str,
    ambiguity_type: str,
    identity_mode: str,
    behavioral_heat: Mapping[str, Any],
) -> list[str]:
    flags: list[str] = []
    heat_label = str(behavioral_heat.get("label") or "").lower()
    if heat_label == "extreme_heat":
        flags.append("EXTREME_BEHAVIORAL_HEAT")
    elif heat_label == "high_heat":
        flags.append("HIGH_BEHAVIORAL_HEAT")
    elif heat_label == "elevated_heat":
        flags.append("ELEVATED_BEHAVIORAL_HEAT")

    if ambiguity_type == "manipulative_ambiguity":
        flags.append("MANIPULATIVE_AMBIGUITY")
    elif ambiguity_type == "unresolved_ambiguity":
        flags.append("UNRESOLVED_AMBIGUITY")

    if identity_mode == "identity_signaling":
        flags.append("IDENTITY_SIGNALING_DOMINANT")
    elif identity_mode == "mixed":
        flags.append("MIXED_IDENTITY_SIGNALING")

    if hidden_objective == "engagement":
        flags.append("ENGAGEMENT_OBJECTIVE")
    elif hidden_objective == "controversy":
        flags.append("CONTROVERSY_OBJECTIVE")
    elif hidden_objective == "distribution":
        flags.append("DISTRIBUTION_OBJECTIVE")
    elif hidden_objective == "conversion":
        flags.append("CONVERSION_OBJECTIVE")

    if behavioral_label == "unofficial_engagement_system":
        flags.append("UNOFFICIAL_SYSTEM")
    elif behavioral_label == "hybrid_system":
        flags.append("HYBRID_SYSTEM")
    return flags


def build_behavioral_review_priority_artifact(
    vocoder_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    for item in vocoder_artifact.get("entities") or []:
        if not isinstance(item, Mapping):
            continue
        forensics = item.get("behavioral_forensics")
        if not isinstance(forensics, Mapping):
            continue
        behavioral_label = str(
            ((forensics.get("system_classification") or {}).get("label")) or "unknown"
        )
        hidden_objective = str(
            ((forensics.get("hidden_objective") or {}).get("label")) or "unknown"
        )
        ambiguity_type = str(((forensics.get("ambiguity_type") or {}).get("label")) or "unknown")
        identity_mode = str(((forensics.get("identity_mode") or {}).get("label")) or "unknown")
        behavioral_heat = dict(forensics.get("behavioral_heat") or {})
        priority = _review_priority(
            behavioral_label=behavioral_label,
            hidden_objective=hidden_objective,
            ambiguity_type=ambiguity_type,
            identity_mode=identity_mode,
            behavioral_heat=behavioral_heat,
        )
        entities.append(
            {
                "entity_id": str(item.get("entity_id") or "").upper(),
                "review_priority": priority,
                "behavioral_label": behavioral_label,
                "hidden_objective": hidden_objective,
                "ambiguity_type": ambiguity_type,
                "identity_mode": identity_mode,
                "behavioral_heat": behavioral_heat,
                "attention_flags": _attention_flags(
                    behavioral_label=behavioral_label,
                    hidden_objective=hidden_objective,
                    ambiguity_type=ambiguity_type,
                    identity_mode=identity_mode,
                    behavioral_heat=behavioral_heat,
                ),
                "compressed_signal_context": {
                    "deployment_posture": str(
                        ((item.get("compressed_signal") or {}).get("deployment_posture")) or "UNKNOWN"
                    ),
                    "decision_signal": str(
                        ((item.get("compressed_signal") or {}).get("decision_signal")) or "UNKNOWN"
                    ),
                    "dominant_mode": str(
                        ((item.get("compressed_signal") or {}).get("dominant_mode")) or "UNKNOWN"
                    ),
                },
            }
        )

    entities.sort(
        key=lambda row: (
            -float((row.get("review_priority") or {}).get("score", 0.0) or 0.0),
            row.get("entity_id") or "",
        )
    )
    return {
        "artifact_kind": "behavioral_review_priority_artifact",
        "schema_version": SCHEMA_VERSION,
        "source_artifact_kind": str(vocoder_artifact.get("artifact_kind") or ""),
        "generated_at": str(vocoder_artifact.get("generated_at") or ""),
        "scenario": str(vocoder_artifact.get("scenario") or "LIVE"),
        "source_mode": str(vocoder_artifact.get("source_mode") or "UNKNOWN"),
        "entity_count": len(entities),
        "summary": {
            "review_priorities": _count_values(
                [item.get("review_priority", {}) for item in entities],
                "label",
            ),
            "attention_flags": _count_flags(entities),
            "top_review_entities": [item["entity_id"] for item in entities[:5]],
        },
        "entities": entities,
    }


def persist_behavioral_review_priority_artifact(
    artifact: Mapping[str, Any],
    *,
    path=None,
) -> None:
    write_json_atomic(path or BEHAVIORAL_REVIEW_PRIORITY_REPORT_PATH, dict(artifact))
