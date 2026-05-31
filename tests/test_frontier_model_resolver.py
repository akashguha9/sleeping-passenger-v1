"""Tests — frontier model resolver selection, fallback, override, modes.

Proves: highest-score selection, deprecated blocking, missing-key honest
degrade (no crash), valid/invalid override, explicit (never silent) fallback,
offline mode makes no network call, live probe disabled by default.
Advisory only; no broker, no execution.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from scripts import frontier_model_registry as reg
from scripts import frontier_model_resolver as R

_ALL_KEYS = {
    "OPENAI_API_KEY": "sk-aaaaaaaaaaaaaaaaaaaa",
    "ANTHROPIC_API_KEY": "sk-ant-bbbbbbbbbbbbbbbbbbbb",
    "XAI_API_KEY": "xai-cccccccccccccccccccc",
    "GEMINI_API_KEY": "AIzadddddddddddddddddddd",
    "MISTRAL_API_KEY": "mk-eeeeeeeeeeeeeeeeeeee",
}


def _openai():
    return reg.load_registry().provider("OPENAI")


def test_best_model_selected_by_highest_frontier_score():
    res = R.resolve_provider(_openai(), env=_ALL_KEYS)
    assert res["selected_model"] == "gpt-5.5"
    # Score equals the explicit frontier_model_score of the selection.
    reg_obj = _openai()
    chosen = next(c for c in reg_obj.candidates if c.model_id == "gpt-5.5")
    assert res["selected_model_score"] == round(R.frontier_model_score(chosen), 6)


def test_scoring_formula_weights_sum_and_clamp():
    # capability_score of an all-1.0 model is 1.0; penalty of all-0 is 0.
    perfect = reg.ModelCandidate(
        provider="OPENAI", model_id="x", reasoning_strength=1, coding_strength=1,
        financial_analysis_strength=1, context_score=1, tool_support_score=1,
        structured_output_score=1, release_rank=1,
    )
    assert R.capability_score(perfect) == 1.0
    assert R.penalty_score(perfect) == 0.0
    assert R.frontier_model_score(perfect) == 1.0
    # Missing-key availability penalty subtracts exactly 0.20.
    assert R.frontier_model_score(perfect, availability_penalty=1.0) == pytest.approx(0.80)


def test_deprecated_model_is_blocked_and_never_selected():
    res = R.resolve_provider(_openai(), env=_ALL_KEYS)
    assert "gpt-4o" in res["deprecated_model_blocked"]
    assert res["selected_model"] != "gpt-4o"


def test_missing_api_key_degrades_without_crash():
    res = R.resolve_provider(_openai(), env={})  # no keys at all
    # A model is still *named* (we know which we'd use) but the provider does
    # not participate in quorum and is flagged API_KEY_MISSING.
    assert res["selected_model"] == "gpt-5.5"
    assert res["provider_key_present"] is False
    assert res["participates_in_quorum"] is False
    assert res["availability_status"] == R.FALLBACK_API_KEY_MISSING


def test_valid_override_is_used():
    env = {**_ALL_KEYS, "OPENAI_MODEL_OVERRIDE": "gpt-5.4"}
    res = R.resolve_provider(_openai(), env=env)
    assert res["selected_model"] == "gpt-5.4"
    assert res["override_used"] is True
    assert res["override_status"] == "OVERRIDE_VALID"


def test_unknown_override_used_but_flagged_unvetted():
    env = {**_ALL_KEYS, "OPENAI_MODEL_OVERRIDE": "gpt-6-experimental"}
    res = R.resolve_provider(_openai(), env=env)
    assert res["selected_model"] == "gpt-6-experimental"
    assert res["override_used"] is True
    assert res["source_kind"] == "override"


def test_invalid_override_rejected_and_falls_back_to_registry():
    # Deprecated id is on the denylist -> rejected, registry selection used.
    env = {**_ALL_KEYS, "OPENAI_MODEL_OVERRIDE": "gpt-4o"}
    res = R.resolve_provider(_openai(), env=env)
    assert res["override_used"] is False
    assert res["override_status"] == "OVERRIDE_DEPRECATED"
    assert res["selected_model"] == "gpt-5.5"


def test_unsafe_override_token_rejected():
    env = {**_ALL_KEYS, "OPENAI_MODEL_OVERRIDE": "place_order_model"}
    res = R.resolve_provider(_openai(), env=env)
    assert res["override_used"] is False
    assert res["override_status"] == "OVERRIDE_UNSAFE_TOKEN"


def test_fallback_is_explicit_never_silent():
    # Force the seed primary to be deprecated -> selection drops to next best
    # AND must carry an explicit fallback reason.
    preg = _openai()
    cands = list(preg.candidates)
    cands[0] = replace(cands[0], deprecation_penalty=1.0, availability_status="DEPRECATED")
    preg2 = replace(preg, candidates=tuple(cands))
    res = R.resolve_provider(preg2, env=_ALL_KEYS)
    assert res["selected_model"] != "gpt-5.5"
    assert res["fallback_used"] is True
    assert res["fallback_reason"] == R.FALLBACK_MODEL_DEPRECATED


def test_no_available_model_reports_no_available_model():
    preg = _openai()
    # Deprecate/unavailable every candidate.
    cands = tuple(
        replace(c, deprecation_penalty=1.0, availability_status="DEPRECATED")
        for c in preg.candidates
    )
    preg2 = replace(preg, candidates=cands)
    res = R.resolve_provider(preg2, env=_ALL_KEYS)
    assert res["selected_model"] is None
    assert res["provider_status"] == "NO_AVAILABLE_MODEL"
    assert res["participates_in_quorum"] is False


def test_offline_mode_makes_no_network_call():
    # The prober must NEVER be invoked in OFFLINE_REGISTRY mode.
    called = {"n": 0}

    def boom(model, env):  # pragma: no cover - must not run
        called["n"] += 1
        return R.PROBE_PROVIDER_ERROR

    R.resolve_all(env=_ALL_KEYS, mode=R.MODE_OFFLINE_REGISTRY, prober=boom)
    assert called["n"] == 0


def test_live_probe_disabled_by_default_when_no_prober():
    res = R.resolve_all(env=_ALL_KEYS, mode=R.MODE_LIVE_PROBE, prober=None)
    assert res["model_availability_live_probed"] is False
    # Models still resolve from the offline registry (probe disabled != crash).
    assert res["providers"]["OPENAI"]["selected_model"] == "gpt-5.5"


def test_live_probe_blocks_model_with_negative_probe_status():
    def prober(model, env):
        # Mark the seed primary not-found; everything else available.
        if model.model_id == "gpt-5.5":
            return R.PROBE_MODEL_NOT_FOUND
        return R.PROBE_MODEL_AVAILABLE

    res = R.resolve_provider(
        _openai(), env=_ALL_KEYS, mode=R.MODE_LIVE_PROBE, prober=prober
    )
    assert res["selected_model"] != "gpt-5.5"
    assert res["fallback_used"] is True
    assert res["fallback_reason"] == R.FALLBACK_MODEL_NOT_FOUND


def test_resolve_all_selects_highest_per_provider():
    res = R.resolve_all(env=_ALL_KEYS)
    sel = {p: r["selected_model"] for p, r in res["providers"].items()}
    assert sel["OPENAI"] == "gpt-5.5"
    assert sel["ANTHROPIC"] == "claude-opus-4-8"
    assert sel["XAI"] == "grok-4.3"
    assert sel["GOOGLE_GEMINI"] == "gemini-3.1-pro"
    assert sel["MISTRAL"] == "mistral-medium-3.5"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
