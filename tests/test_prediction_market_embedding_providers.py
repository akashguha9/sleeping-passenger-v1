"""
Tests for the swappable embedding-provider layer used by the
Polymarket × Kalshi disagreement scanner.

These tests cover:
  - The deterministic baseline returns stable, normalised vectors.
  - ``resolve_embedding_provider`` returns the deterministic provider
    when asked for ``deterministic`` (default) and never opens a
    network socket.
  - ``resolve_embedding_provider("real", ...)`` returns a *fallback*
    deterministic provider when no API key is configured.
  - Strict mode raises ``EmbeddingProviderUnavailable`` instead of
    silently falling back.
  - The HTTP provider parses the OpenAI-style payload shape via a
    fake injected transport.
  - A failing transport must NOT crash the scanner — the provider
    falls back to deterministic embedding so downstream scoring still
    has a value.
  - The provider's status dict is safe to stamp onto an advisory alert
    (no secrets, advisory contract intact).
"""
from __future__ import annotations

from typing import Any, Mapping

import pytest
from tests.helpers import scanner_probes as probes

from scripts.prediction_market_embedding_providers import (
    DeterministicEmbeddingProvider,
    EmbeddingProviderUnavailable,
    HTTPEmbeddingProvider,
    PROVIDER_DETERMINISTIC,
    PROVIDER_FALLBACK_REAL,
    PROVIDER_REAL,
    resolve_embedding_provider,
)


# ---------------------------------------------------------------------------
# Deterministic provider
# ---------------------------------------------------------------------------


class TestDeterministicProvider:
    def test_default_returns_stable_vectors(self):
        provider = DeterministicEmbeddingProvider()
        a = provider.embed_text("Will Bitcoin hit $100k in May?")
        b = provider.embed_text("Will Bitcoin hit $100k in May?")
        assert a == b
        assert isinstance(a, list)
        assert all(isinstance(x, float) for x in a)

    def test_empty_text_returns_none(self):
        provider = DeterministicEmbeddingProvider()
        assert provider.embed_text("") is None

    def test_status_dict_is_safe_to_stamp(self):
        provider = DeterministicEmbeddingProvider()
        stamp = provider.to_status_dict()
        assert stamp["embedding_provider"] == "deterministic"
        assert stamp["embedding_available"] is True
        assert "api_key" not in repr(stamp).lower()

    def test_as_callable_matches_embedding_fn_contract(self):
        provider = DeterministicEmbeddingProvider()
        fn = provider.as_callable()
        vec_a = fn("Will Bitcoin hit $100k in May?")
        vec_b = provider.embed_text("Will Bitcoin hit $100k in May?")
        assert vec_a == vec_b


# ---------------------------------------------------------------------------
# Factory — deterministic / real / unknown
# ---------------------------------------------------------------------------


class TestResolveEmbeddingProvider:
    def test_default_is_deterministic_offline(self):
        provider = resolve_embedding_provider(None)
        assert isinstance(provider, DeterministicEmbeddingProvider)
        assert provider.name == PROVIDER_DETERMINISTIC
        # No env required — must run offline.
        assert provider.available is True

    def test_explicit_deterministic_string(self):
        provider = resolve_embedding_provider("deterministic")
        assert isinstance(provider, DeterministicEmbeddingProvider)

    def test_real_without_api_key_falls_back_silently(self):
        provider = resolve_embedding_provider("real", env={})
        # Strict NOT set → fallback path
        assert provider.available is False
        assert provider.name == PROVIDER_FALLBACK_REAL
        assert "no_api_key" in provider.status_reason
        # Even fallback still produces a vector.
        vec = provider.embed_text("Will Bitcoin hit $100k in May?")
        assert isinstance(vec, list) and len(vec) > 0

    def test_real_without_api_key_strict_raises(self):
        with pytest.raises(EmbeddingProviderUnavailable):
            resolve_embedding_provider("real", env={}, strict=True)

    def test_unknown_provider_falls_back_in_non_strict(self):
        provider = resolve_embedding_provider("magic_new_provider", env={})
        assert provider.available is False
        assert provider.status_reason.startswith("unknown_embedding_provider")

    def test_unknown_provider_strict_raises(self):
        with pytest.raises(EmbeddingProviderUnavailable):
            resolve_embedding_provider(
                "magic_new_provider", env={}, strict=True
            )

    def test_no_secret_value_leaks_into_status(self):
        env = {
            "OPENAI_API_KEY": probes.sk_style_token("do-not-leak"),
        }

        def _transport(*_args, **_kwargs):  # pragma: no cover - not invoked
            raise AssertionError("transport must not be called for status check")

        provider = resolve_embedding_provider(
            "real", env=env, transport=_transport
        )
        stamp = provider.to_status_dict()
        flat = repr(stamp)
        assert "do-not-leak" not in flat
        assert "sk-" not in flat


# ---------------------------------------------------------------------------
# HTTP provider — fake transport
# ---------------------------------------------------------------------------


class TestHTTPProviderWithFakeTransport:
    def test_openai_style_payload_is_parsed(self):
        calls: list[tuple[str, Mapping[str, str], Mapping[str, Any], float]] = []

        def fake_transport(
            url: str,
            headers: Mapping[str, str],
            payload: Mapping[str, Any],
            timeout_seconds: float,
        ) -> Mapping[str, Any]:
            calls.append((url, headers, payload, timeout_seconds))
            # Mimic the openai embeddings response shape exactly.
            return {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}

        provider = resolve_embedding_provider(
            "real",
            env={"OPENAI_API_KEY": probes.sk_style_token("fake")},
            transport=fake_transport,
        )
        vec = provider.embed_text("Will Bitcoin hit $100k in May?")
        assert vec == [0.1, 0.2, 0.3, 0.4]
        assert calls, "transport was not called"
        # Outbound headers include Authorization — but the *value* is
        # not present in the alert payload (verified via to_status_dict).
        url, headers, payload, timeout = calls[0]
        assert "Authorization" in headers
        assert payload["input"] == "Will Bitcoin hit $100k in May?"
        assert payload["model"]  # default model resolved
        assert timeout > 0

    def test_alt_payload_shapes_parsed(self):
        def fake_transport(*_args, **_kwargs):
            return {"embedding": [0.5, 0.5, 0.5]}

        provider = resolve_embedding_provider(
            "real",
            env={"OPENAI_API_KEY": "sk-fake"},
            transport=fake_transport,
        )
        vec = provider.embed_text("hello")
        assert vec == [0.5, 0.5, 0.5]

    def test_failing_transport_falls_back_to_deterministic(self):
        def boom_transport(*_args, **_kwargs):
            raise RuntimeError("simulated network failure")

        provider = resolve_embedding_provider(
            "real",
            env={"OPENAI_API_KEY": "sk-fake"},
            transport=boom_transport,
        )
        vec = provider.embed_text("hello world")
        # Network failure must NOT crash; we fall back to the deterministic
        # baseline so the alert still has an embedding score.
        assert isinstance(vec, list)
        assert len(vec) > 0

    def test_model_override_via_factory(self):
        seen_models: list[str] = []

        def fake_transport(
            url, headers, payload, timeout_seconds
        ):  # pragma: no cover - boilerplate
            seen_models.append(payload.get("model", ""))
            return {"data": [{"embedding": [0.0, 1.0]}]}

        provider = resolve_embedding_provider(
            "real",
            model="text-embedding-3-large",
            env={"OPENAI_API_KEY": "sk-fake"},
            transport=fake_transport,
        )
        provider.embed_text("hello")
        assert seen_models == ["text-embedding-3-large"]


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------


class TestProviderSafety:
    def test_provider_never_grants_execution_permission(self):
        provider = resolve_embedding_provider("real", env={})
        stamp = provider.to_status_dict()
        for forbidden in ("execution", "broker", "order", "trade"):
            assert forbidden not in str(stamp).lower(), (
                f"provider status dict mentioned forbidden term {forbidden!r}: {stamp}"
            )

    def test_strict_failure_raises_clean_exception(self):
        with pytest.raises(EmbeddingProviderUnavailable) as exc_info:
            resolve_embedding_provider("real", env={}, strict=True)
        # Reason includes the explicit unavailability category so the
        # operator can act on it without grepping logs.
        assert "no_api_key" in str(exc_info.value)

    def test_provider_name_constants(self):
        assert PROVIDER_DETERMINISTIC == "deterministic"
        assert PROVIDER_REAL == "real"
        assert "fallback" in PROVIDER_FALLBACK_REAL
