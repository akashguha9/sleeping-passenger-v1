"""Tests — model-quality-weighted quorum (Kanté Five-Model Frontier Resolver).

Proves the weighted quorum: at least 3 valid provider votes AND normalized
quorum >= 0.60; two high-quality models alone cannot satisfy quorum; three
valid providers can; a missing provider degrades synthesis. Advisory only.
"""
from __future__ import annotations

import pytest

from scripts import frontier_model_resolver as R

_ALL_KEYS = {
    "OPENAI_API_KEY": "sk-a",
    "ANTHROPIC_API_KEY": "sk-ant-b",
    "XAI_API_KEY": "xai-c",
    "GEMINI_API_KEY": "AIza-d",
    "MISTRAL_API_KEY": "mk-e",
}


def _resolution(env):
    return R.resolve_all(env=env)


def test_quorum_required_count_is_three():
    assert R.QUORUM_REQUIRED_COUNT == 3


def test_all_five_present_satisfies_quorum():
    res = _resolution(_ALL_KEYS)
    q = R.weighted_quorum(res)
    assert q["valid_provider_count"] == 5
    assert q["quorum_satisfied"] is True
    assert q["normalized_quorum"] == pytest.approx(1.0)


def test_two_high_quality_models_alone_cannot_satisfy_quorum():
    res = _resolution(_ALL_KEYS)
    # Only OpenAI + Anthropic produced usable output; the rest are silent.
    votes = {
        "OPENAI": True,
        "ANTHROPIC": True,
        "XAI": False,
        "GOOGLE_GEMINI": False,
        "MISTRAL": False,
    }
    q = R.weighted_quorum(res, votes)
    assert q["valid_provider_count"] == 2
    assert q["quorum_satisfied"] is False
    assert q["classification_downgraded_for_quorum"] is True


def test_three_valid_providers_can_satisfy_quorum():
    res = _resolution(_ALL_KEYS)
    votes = {
        "OPENAI": True,
        "ANTHROPIC": True,
        "XAI": True,
        "GOOGLE_GEMINI": False,
        "MISTRAL": False,
    }
    q = R.weighted_quorum(res, votes)
    assert q["valid_provider_count"] == 3
    # Three frontier models comfortably clear the 0.60 normalized threshold.
    assert q["normalized_quorum"] >= 0.60
    assert q["quorum_satisfied"] is True


def test_missing_provider_keys_degrade_quorum():
    # Only three providers have keys -> default vote = participation.
    env = {
        "OPENAI_API_KEY": "sk-a",
        "ANTHROPIC_API_KEY": "sk-ant-b",
        "XAI_API_KEY": "xai-c",
    }
    res = _resolution(env)
    q = R.weighted_quorum(res)  # default votes from participation
    assert q["valid_provider_count"] == 3
    assert q["quorum_satisfied"] is True
    # Drop to two keys -> degraded.
    env2 = {"OPENAI_API_KEY": "sk-a", "ANTHROPIC_API_KEY": "sk-ant-b"}
    q2 = R.weighted_quorum(_resolution(env2))
    assert q2["valid_provider_count"] == 2
    assert q2["quorum_satisfied"] is False


def test_single_frontier_model_cannot_carry_panel():
    res = _resolution(_ALL_KEYS)
    votes = {
        "OPENAI": True,
        "ANTHROPIC": False,
        "XAI": False,
        "GOOGLE_GEMINI": False,
        "MISTRAL": False,
    }
    q = R.weighted_quorum(res, votes)
    # Even though OpenAI is the highest-weight model, one vote < 3 required.
    assert q["valid_provider_count"] == 1
    assert q["quorum_satisfied"] is False


def test_invented_executable_candidate_invalidates_vote():
    res = _resolution(_ALL_KEYS)
    votes = {
        "OPENAI": {"model_output_present": True, "output_advisory_safe": True,
                   "no_invented_executable_candidate": False},
        "ANTHROPIC": True,
        "XAI": True,
        "GOOGLE_GEMINI": False,
        "MISTRAL": False,
    }
    q = R.weighted_quorum(res, votes)
    # OpenAI vote is invalidated (it invented an executable candidate).
    assert q["per_provider_vote"]["OPENAI"]["valid_provider_vote"] is False
    assert q["valid_provider_count"] == 2
    assert q["quorum_satisfied"] is False


def test_unsafe_output_invalidates_vote():
    res = _resolution(_ALL_KEYS)
    votes = {
        "OPENAI": {"model_output_present": True, "output_advisory_safe": False},
        "ANTHROPIC": True,
        "XAI": True,
        "GOOGLE_GEMINI": True,
        "MISTRAL": False,
    }
    q = R.weighted_quorum(res, votes)
    assert q["per_provider_vote"]["OPENAI"]["valid_provider_vote"] is False
    assert q["valid_provider_count"] == 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
