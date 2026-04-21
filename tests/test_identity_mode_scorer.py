from __future__ import annotations

from scripts.identity_mode_scorer import build_identity_mode_assessment


def test_identity_mode_assessment_epistemic_case() -> None:
    payload = build_identity_mode_assessment(
        supporting_features={
            "identity_signal_score": 0.05,
            "validation_score": 0.65,
            "engagement_feedback": 0.05,
            "information_ratio": 1.0,
            "consequence_coupling": 0.5,
        }
    )

    assert payload["schema_version"] == "v1"
    assert payload["identity_mode"]["label"] == "epistemic"
    assert payload["supporting_signals"]["validation_score"] == 0.65


def test_identity_mode_assessment_identity_signaling_case() -> None:
    payload = build_identity_mode_assessment(
        supporting_features={
            "identity_signal_score": 0.45,
            "validation_score": 0.05,
            "engagement_feedback": 0.8,
            "information_ratio": 0.1,
            "consequence_coupling": 0.0,
        }
    )

    assert payload["identity_mode"]["label"] == "identity_signaling"


def test_identity_mode_assessment_mixed_case() -> None:
    payload = build_identity_mode_assessment(
        supporting_features={
            "identity_signal_score": 0.22,
            "validation_score": 0.28,
            "engagement_feedback": 0.3,
            "information_ratio": 0.3,
            "consequence_coupling": 0.1,
        }
    )

    assert payload["identity_mode"]["label"] == "mixed"


def test_identity_mode_assessment_unknown_case() -> None:
    payload = build_identity_mode_assessment(
        supporting_features={
            "identity_signal_score": 0.05,
            "validation_score": 0.05,
            "engagement_feedback": 0.05,
            "information_ratio": 0.05,
            "consequence_coupling": 0.0,
        }
    )

    assert payload["identity_mode"]["label"] == "unknown"
