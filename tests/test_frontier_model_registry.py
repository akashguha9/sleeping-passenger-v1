"""Tests — frontier model registry (Kanté Five-Model Frontier Resolver sprint).

Proves the registry: five providers, config-driven seeds, capability fields,
deprecation flags, and the embedded fallback. No network, no broker, advisory.
"""
from __future__ import annotations

import pytest

from scripts import frontier_model_registry as reg


def test_registry_contains_five_providers():
    r = reg.load_registry()
    assert set(r.provider_ids()) == set(reg.PROVIDERS)
    assert len(reg.PROVIDERS) == 5


def test_every_provider_has_at_least_one_candidate_and_a_primary():
    r = reg.load_registry()
    for provider_id in reg.PROVIDERS:
        preg = r.provider(provider_id)
        assert preg is not None
        assert preg.candidates, f"{provider_id} has no candidates"
        primary = preg.primary_preferred()
        assert primary is not None
        assert not primary.is_deprecated


def test_provider_key_env_present_for_each_provider():
    r = reg.load_registry()
    # Each provider names the env var(s) holding its key — never the value.
    assert r.provider("OPENAI").key_env == ("OPENAI_API_KEY",)
    assert r.provider("ANTHROPIC").key_env == ("ANTHROPIC_API_KEY",)
    assert r.provider("XAI").key_env == ("XAI_API_KEY",)
    assert "GEMINI_API_KEY" in r.provider("GOOGLE_GEMINI").key_env
    assert "GOOGLE_API_KEY" in r.provider("GOOGLE_GEMINI").key_env
    assert r.provider("MISTRAL").key_env == ("MISTRAL_API_KEY",)


def test_capability_tiers_are_known():
    r = reg.load_registry()
    for preg in r.providers.values():
        for c in preg.candidates:
            assert c.capability_tier in reg.CAPABILITY_TIERS


def test_deprecated_models_flagged_and_in_denylist():
    r = reg.load_registry()
    openai = r.provider("OPENAI")
    deny = openai.deprecated_denylist()
    assert "gpt-4o" in deny
    bad = next(c for c in openai.candidates if c.model_id == "gpt-4o")
    assert bad.is_deprecated
    assert not bad.available_offline()


def test_seed_primaries_are_current_frontier_ids():
    r = reg.load_registry()
    assert r.provider("ANTHROPIC").primary_preferred().model_id == "claude-opus-4-8"
    assert r.provider("OPENAI").primary_preferred().model_id == "gpt-5.5"
    assert r.provider("XAI").primary_preferred().model_id == "grok-4.3"
    assert r.provider("MISTRAL").primary_preferred().model_id == "mistral-medium-3.5"


def test_embedded_fallback_used_when_config_missing(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    r = reg.load_registry(missing)
    assert set(r.provider_ids()) == set(reg.PROVIDERS)
    assert r.source_path == "embedded_fallback"


def test_corrupt_config_degrades_to_fallback(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    r = reg.load_registry(bad)
    assert set(r.provider_ids()) == set(reg.PROVIDERS)


def test_registry_carries_no_secret_values_only_env_names():
    r = reg.load_registry()
    for preg in r.providers.values():
        for name in preg.key_env:
            assert name.endswith("_API_KEY") or name.endswith("_KEY")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
