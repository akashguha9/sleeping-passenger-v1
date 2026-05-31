"""Tests — synthesis model-selection evidence block.

Proves the '# Model Selection / Frontier Resolver' block carries the required
per-provider metadata + quorum summary, and that the hard synthesis
instruction (no new BUY_CANDIDATE when quorum fails) is emitted. Advisory only.
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


def test_block_includes_required_per_provider_fields():
    ev = R.build_model_selection_evidence(env=_ALL_KEYS)
    md = ev["markdown"]
    assert "# Model Selection / Frontier Resolver" in md
    for provider in ("OPENAI", "ANTHROPIC", "XAI", "GOOGLE_GEMINI", "MISTRAL"):
        assert f"## {provider}" in md
    for field in (
        "selected_model:",
        "selected_model_score:",
        "capability_tier:",
        "provider_key_present:",
        "availability_status:",
        "fallback_used:",
        "fallback_reason:",
        "override_used:",
        "deprecated_model_blocked:",
        "participates_in_quorum:",
    ):
        assert field in md, f"missing field {field!r}"


def test_block_includes_quorum_summary_fields():
    ev = R.build_model_selection_evidence(env=_ALL_KEYS)
    md = ev["markdown"]
    for field in (
        "valid_provider_count:",
        "quorum_required_count:",
        "weighted_quorum_score:",
        "normalized_quorum:",
        "quorum_satisfied:",
    ):
        assert field in md


def test_block_states_availability_not_live_probed_offline():
    ev = R.build_model_selection_evidence(env=_ALL_KEYS, mode=R.MODE_OFFLINE_REGISTRY)
    assert "availability not live-probed" in ev["markdown"]


def test_block_emits_hard_instruction_when_quorum_fails():
    votes = {"OPENAI": True, "ANTHROPIC": True, "XAI": False,
             "GOOGLE_GEMINI": False, "MISTRAL": False}
    ev = R.build_model_selection_evidence(env=_ALL_KEYS, votes=votes)
    md = ev["markdown"]
    assert ev["quorum"]["quorum_satisfied"] is False
    assert "do NOT classify any new BUY_CANDIDATE" in md
    assert "WATCHLIST" in md and "DATA_INSUFFICIENT" in md


def test_block_mentions_provider_missing_from_quorum():
    env = {"OPENAI_API_KEY": "sk-a"}  # only one key
    ev = R.build_model_selection_evidence(env=env)
    md = ev["markdown"]
    # Providers with a key absent are flagged API_KEY_MISSING / not participating.
    assert "API_KEY_MISSING" in md
    assert "participates_in_quorum: False" in md


def test_block_mentions_fallback_reason_when_fallback():
    # Build a resolution where a fallback is forced via a live probe.
    def prober(model, env):
        if model.model_id == "claude-opus-4-8":
            return R.PROBE_RATE_LIMITED
        return R.PROBE_MODEL_AVAILABLE

    ev = R.build_model_selection_evidence(
        env=_ALL_KEYS, mode=R.MODE_LIVE_PROBE, prober=prober
    )
    md = ev["markdown"]
    assert "FALLBACK in effect" in md
    assert "RATE_LIMITED" in md


def test_resolution_carries_advisory_safety_stamps():
    ev = R.build_model_selection_evidence(env=_ALL_KEYS)
    res = ev["resolution"]
    assert res["advisory_only"] is True
    assert res["model_output_authority"] == "ADVISORY_ONLY"
    assert res["execution_gate"] == "LOCKED"
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
