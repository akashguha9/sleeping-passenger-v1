"""Tests — provider secret redaction (mission P2/P3 safety).

Proves credential VALUES never appear in logs / status dicts / report blobs;
only ``*_present`` booleans and env NAMES are exposed.
"""
from __future__ import annotations

import json

import pytest

from scripts.provider_secret_redaction import (
    assert_no_secret,
    collect_secret_values,
    key_present,
    provider_key_fields,
    redact,
)


def test_key_present_uses_injected_env():
    env = {"FOO_KEY": "sk-secret-123"}
    assert key_present("FOO_KEY", env) is True
    assert key_present("MISSING_KEY", env) is False
    assert key_present(None, env) is False
    assert key_present("FOO_KEY", {"FOO_KEY": "   "}) is False


def test_redact_never_returns_raw_value():
    secret = "sk-live-abcdef123456"
    out = redact(secret)
    assert secret not in out
    assert out == "***"
    assert redact(None) == "<absent>"
    assert redact("") == "<absent>"


def test_redact_keep_suffix_exposes_only_tail():
    secret = "sk-live-abcdef123456"
    out = redact(secret, keep_suffix=4)
    assert out == "***3456"
    assert secret not in out


def test_provider_key_fields_has_no_value():
    env = {"TWELVE_DATA_API_KEY": "td-key-999"}
    fields = provider_key_fields("twelve_data", "TWELVE_DATA_API_KEY", env)
    assert fields["api_key_present"] is True
    assert fields["api_key_env"] == "TWELVE_DATA_API_KEY"
    assert fields["requires_api_key"] is True
    # the value must never appear in the descriptor
    assert "td-key-999" not in json.dumps(fields)


def test_assert_no_secret_detects_leak_and_clean():
    env = {"K1": "topsecret", "K2": "other"}
    secrets = collect_secret_values(["K1", "K2"], env)
    assert assert_no_secret({"status": "OK", "key_present": True}, secrets) is True
    assert assert_no_secret({"oops": "topsecret embedded"}, secrets) is False


def test_collect_secret_values_skips_empty():
    env = {"A": "x", "B": "", "C": "  "}
    vals = collect_secret_values(["A", "B", "C"], env)
    assert vals == ["x"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
