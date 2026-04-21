from __future__ import annotations

from scripts.behavioral_heat_scorer import build_behavioral_heat_assessment


def test_behavioral_heat_assessment_low_heat_case() -> None:
    payload = build_behavioral_heat_assessment(
        supporting_features={
            "engagement_feedback": 0.05,
            "cta_density": 0.0,
            "controversy_score": 0.0,
            "question_density": 0.0,
            "open_end_density": 0.0,
            "identity_signal_score": 0.02,
        }
    )

    assert payload["schema_version"] == "v1"
    assert payload["behavioral_heat"]["label"] == "low_heat"
    assert payload["supporting_signals"]["engagement_feedback"] == 0.05


def test_behavioral_heat_assessment_high_heat_case() -> None:
    payload = build_behavioral_heat_assessment(
        supporting_features={
            "engagement_feedback": 0.95,
            "cta_density": 0.8,
            "controversy_score": 0.55,
            "question_density": 0.5,
            "open_end_density": 0.75,
            "identity_signal_score": 0.4,
        }
    )

    assert payload["behavioral_heat"]["label"] in {"high_heat", "extreme_heat"}
    assert payload["behavioral_heat"]["score"] >= 0.38
