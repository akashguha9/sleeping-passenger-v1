from __future__ import annotations

from scripts.behavioral_forensics import build_behavioral_forensics_output
from scripts.identity_mode_scorer import build_identity_mode_assessment


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
                "end_date": "2026-04-22T14:00:00+00:00",
            },
            "reliability_prior": 0.88,
            "timestamp": "2026-04-21T10:15:00+00:00",
            "freshness_remaining": 0.92,
            "raw_output": {},
        },
        {
            "source": "market_data",
            "signal_type": "ANCHOR",
            "content": {
                "symbol": "RTX",
                "price": 131.5,
                "implied_probability": 0.69,
                "volatility": 0.14,
            },
            "reliability_prior": 0.92,
            "timestamp": "2026-04-21T11:40:00+00:00",
            "freshness_remaining": 0.97,
            "raw_output": {},
        },
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
                "published": "2026-04-21T09:00:00+00:00",
                "source": "Example",
                "link": "https://example.com/viral-prompt",
            },
            "reliability_prior": 0.60,
            "timestamp": "2026-04-21T09:30:00+00:00",
            "freshness_remaining": 0.8,
            "raw_output": {},
        },
    ]


def test_behavioral_forensics_classifies_official_correctness_system() -> None:
    payload = build_behavioral_forensics_output(
        _official_signals(),
        entity_id="RTX",
        runtime_context={
            "policy_state": "RESTRICTED",
            "pre_entry_state": "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
            "has_open_position": False,
        },
    )

    assert payload["system_classification"]["label"] == "official_correctness_system"
    assert payload["hidden_objective"]["label"] in {"decision_usefulness", "correctness"}
    assert payload["ambiguity_analysis"]["schema_version"] == "v1"
    assert payload["ambiguity_type"]["label"] == "low_ambiguity"
    assert payload["identity_mode"] == build_identity_mode_assessment(
        supporting_features=payload["supporting_signals"]
    )["identity_mode"]
    assert payload["identity_mode"]["label"] == "epistemic"
    assert payload["supporting_signals"]["validation_score"] >= 0.5
    assert payload["supporting_signals"]["consequence_coupling"] >= 0.4


def test_behavioral_forensics_classifies_unofficial_engagement_system() -> None:
    payload = build_behavioral_forensics_output(
        _engagement_signals(),
        entity_id="BROAD",
        runtime_context={
            "policy_state": "UNKNOWN",
            "pre_entry_state": "NONE",
            "has_open_position": False,
        },
    )

    assert payload["system_classification"]["label"] == "unofficial_engagement_system"
    assert payload["hidden_objective"]["label"] in {"engagement", "distribution", "identity_signaling", "controversy"}
    assert payload["ambiguity_analysis"]["ambiguity_type"]["label"] == payload["ambiguity_type"]["label"]
    assert payload["ambiguity_type"]["label"] in {"manipulative_ambiguity", "unresolved_ambiguity"}
    assert payload["identity_mode"] == build_identity_mode_assessment(
        supporting_features=payload["supporting_signals"]
    )["identity_mode"]
    assert payload["identity_mode"]["label"] in {"identity_signaling", "mixed"}
    assert payload["supporting_signals"]["engagement_feedback"] > 0.4
    assert payload["supporting_signals"]["ambiguity_score"] > 0.2
