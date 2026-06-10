"""Streamlit dashboard owner-gate proofs (Pass 2, Phase 6).

The dashboard must default to loopback, refuse non-loopback binds without
the explicit override, and — new — require the owner token (same
verification path as the API) whenever it is reachable beyond loopback.
"""
from __future__ import annotations

import importlib

import pytest

import scripts.runtime_config as rc
from scripts import generate_api_token as gen
from src.dashboard import streamlit_app as dash


def _reset_env(monkeypatch, **overrides):
    for var in (
        "STREAMLIT_SERVER_ADDRESS",
        "MVP_DASHBOARD_ALLOW_NONLOOPBACK",
        "MVP_DASHBOARD_REQUIRE_TOKEN",
        "MVP_API_TOKEN",
        "MVP_API_TOKEN_HASH",
    ):
        monkeypatch.delenv(var, raising=False)
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    importlib.reload(rc)


def test_dashboard_defaults_to_loopback(monkeypatch):
    _reset_env(monkeypatch)
    assert dash._dashboard_bind_is_loopback() is True


def test_dashboard_nonloopback_detected(monkeypatch):
    _reset_env(monkeypatch, STREAMLIT_SERVER_ADDRESS="0.0.0.0")
    assert dash._dashboard_bind_is_loopback() is False


def test_loopback_does_not_require_token_by_default(monkeypatch):
    """Same-OS-user processes can read the SQLite file directly, so a
    loopback token prompt is friction, not security — documented choice."""
    _reset_env(monkeypatch)
    assert dash._dashboard_requires_token() is False


def test_loopback_token_opt_in(monkeypatch):
    _reset_env(monkeypatch, MVP_DASHBOARD_REQUIRE_TOKEN="1")
    assert dash._dashboard_requires_token() is True


def test_nonloopback_always_requires_token(monkeypatch):
    _reset_env(
        monkeypatch,
        STREAMLIT_SERVER_ADDRESS="0.0.0.0",
        MVP_DASHBOARD_ALLOW_NONLOOPBACK="1",
    )
    assert dash._dashboard_requires_token() is True


def test_dashboard_token_uses_api_verification_hash_mode(monkeypatch):
    raw = gen.generate_token()
    _reset_env(monkeypatch, MVP_API_TOKEN_HASH=gen.hash_token(raw))
    assert dash._dashboard_token_ok(raw) is True
    assert dash._dashboard_token_ok(raw + "x") is False
    assert dash._dashboard_token_ok("") is False
    assert dash._dashboard_token_ok(None) is False


def test_dashboard_token_plaintext_fallback(monkeypatch):
    _reset_env(monkeypatch, MVP_API_TOKEN="legacy-token")
    assert dash._dashboard_token_ok("legacy-token") is True
    assert dash._dashboard_token_ok("nope") is False


def test_dashboard_gate_fails_closed_with_no_token_configured(monkeypatch):
    """Token-gated dashboard with nothing to verify against must deny."""
    _reset_env(monkeypatch)
    assert dash._dashboard_token_ok("anything") is False


def test_docs_warn_against_direct_exposure():
    text = (dash.__doc__ or "").lower()
    assert "loopback" in text
    assert "owner-token gate" in text or "owner token" in text
