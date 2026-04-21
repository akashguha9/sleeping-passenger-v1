from __future__ import annotations

from scripts.ambiguity_scorer import build_ambiguity_analysis


def _official_signals() -> list[dict]:
    return [
        {
            "source": "polymarket",
            "signal_type": "ANCHOR",
            "content": {
                "condition_id": "RTX-Q2",
                "question": "Will RTX beat Q2 expectations?",
                "outcome_prices": {"yes": 0.68, "no": 0.32},
                "volume": 120000,
            },
            "reliability_prior": 0.88,
            "timestamp": "2026-04-21T10:15:00+00:00",
            "freshness_remaining": 0.92,
            "raw_output": {},
        }
    ]


def _engagement_signals() -> list[dict]:
    return [
        {
            "source": "praw_reddit",
            "signal_type": "SYSTEM",
            "content": {
                "subreddit": "linkedinlunatics",
                "title": "Only real leaders can solve this impossible math trap. Thoughts?",
                "score": 1400,
                "num_comments": 420,
            },
            "reliability_prior": 0.45,
            "timestamp": "2026-04-21T11:15:00+00:00",
            "freshness_remaining": 0.95,
            "raw_output": {},
        },
        {
            "source": "feedparser",
            "signal_type": "SYSTEM",
            "content": {
                "title": "Viral leadership puzzle sparks debate",
                "summary": "Commenters disagree and keep sharing the prompt for engagement.",
            },
            "reliability_prior": 0.60,
            "timestamp": "2026-04-21T09:30:00+00:00",
            "freshness_remaining": 0.8,
            "raw_output": {},
        },
    ]


def test_build_ambiguity_analysis_low_ambiguity_case() -> None:
    payload = build_ambiguity_analysis(
        _official_signals(),
        supporting_features={
            "validation_score": 0.75,
            "engagement_feedback": 0.10,
            "identity_signal_score": 0.0,
            "cta_density": 0.0,
            "controversy_score": 0.0,
            "consequence_coupling": 0.40,
        },
    )

    assert payload["schema_version"] == "v1"
    assert payload["ambiguity_type"]["label"] == "low_ambiguity"
    assert payload["supporting_signals"]["ambiguity_score"] <= 0.15


def test_build_ambiguity_analysis_manipulative_case() -> None:
    payload = build_ambiguity_analysis(
        _engagement_signals(),
        supporting_features={
            "validation_score": 0.0,
            "engagement_feedback": 1.0,
            "identity_signal_score": 0.35,
            "cta_density": 1.0,
            "controversy_score": 0.1,
            "consequence_coupling": 0.0,
        },
    )

    assert payload["ambiguity_type"]["label"] == "manipulative_ambiguity"
    assert payload["supporting_signals"]["open_end_density"] > 0.0
    assert payload["supporting_signals"]["ambiguity_score"] > 0.15
