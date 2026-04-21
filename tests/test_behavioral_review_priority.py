from __future__ import annotations

from scripts.behavioral_review_priority import build_behavioral_review_priority_artifact


def _sample_vocoder_artifact() -> dict:
    return {
        "artifact_kind": "signal_vocoder_runtime_artifact",
        "generated_at": "2026-04-21T12:00:00+00:00",
        "scenario": "LIVE",
        "source_mode": "SYNTHETIC_RUNTIME_FALLBACK",
        "entities": [
            {
                "entity_id": "RTX",
                "compressed_signal": {
                    "deployment_posture": "BLOCKED",
                    "decision_signal": "MONITOR",
                    "dominant_mode": "DAFT_PUNK",
                },
                "behavioral_forensics": {
                    "system_classification": {"label": "official_correctness_system"},
                    "hidden_objective": {"label": "decision_usefulness"},
                    "ambiguity_type": {"label": "low_ambiguity"},
                    "identity_mode": {"label": "epistemic"},
                    "behavioral_heat": {"label": "low_heat", "confidence": 0.9, "score": 0.0},
                },
            },
            {
                "entity_id": "BROAD",
                "compressed_signal": {
                    "deployment_posture": "MONITOR",
                    "decision_signal": "MONITOR",
                    "dominant_mode": "KANYE",
                },
                "behavioral_forensics": {
                    "system_classification": {"label": "unofficial_engagement_system"},
                    "hidden_objective": {"label": "engagement"},
                    "ambiguity_type": {"label": "manipulative_ambiguity"},
                    "identity_mode": {"label": "identity_signaling"},
                    "behavioral_heat": {"label": "extreme_heat", "confidence": 0.88, "score": 0.81},
                },
            },
        ],
    }


def test_behavioral_review_priority_artifact_ranks_high_heat_engagement_entities_first() -> None:
    artifact = build_behavioral_review_priority_artifact(_sample_vocoder_artifact())

    assert artifact["artifact_kind"] == "behavioral_review_priority_artifact"
    assert artifact["source_artifact_kind"] == "signal_vocoder_runtime_artifact"
    assert artifact["entity_count"] == 2
    assert [item["entity_id"] for item in artifact["entities"]] == ["BROAD", "RTX"]
    assert artifact["entities"][0]["review_priority"]["label"] in {"priority_review", "urgent_review"}
    assert "ENGAGEMENT_OBJECTIVE" in artifact["entities"][0]["attention_flags"]
    assert "EXTREME_BEHAVIORAL_HEAT" in artifact["entities"][0]["attention_flags"]
    assert artifact["entities"][1]["review_priority"]["label"] == "routine_review"
    assert artifact["summary"]["top_review_entities"] == ["BROAD", "RTX"]


def test_behavioral_review_priority_artifact_skips_entities_without_forensics() -> None:
    payload = _sample_vocoder_artifact()
    payload["entities"].append(
        {
            "entity_id": "UNG",
            "compressed_signal": {"deployment_posture": "BLOCKED", "decision_signal": "EXIT", "dominant_mode": "HBFS"},
        }
    )

    artifact = build_behavioral_review_priority_artifact(payload)

    assert artifact["entity_count"] == 2
    assert [item["entity_id"] for item in artifact["entities"]] == ["BROAD", "RTX"]
