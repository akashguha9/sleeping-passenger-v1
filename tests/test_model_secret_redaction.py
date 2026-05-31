"""Tests — model resolver secret safety + no-execution surface.

Proves: no raw API-key value ever appears in the resolution dict or rendered
synthesis block (only *_present booleans), and the resolver introduces no
broker / order / execution surface. Advisory only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import advisory_contract as contract
from scripts import frontier_model_resolver as R
from scripts import provider_secret_redaction as redact

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Realistic-looking secret values the resolver must never echo.
_SECRET_ENV = {
    "OPENAI_API_KEY": "sk-SUPERSECRETopenai0123456789",
    "ANTHROPIC_API_KEY": "sk-ant-SUPERSECRETanthropic0123456789",
    "XAI_API_KEY": "xai-SUPERSECRETxai0123456789",
    "GEMINI_API_KEY": "AIzaSUPERSECRETgemini0123456789",
    "MISTRAL_API_KEY": "mk-SUPERSECRETmistral0123456789",
    "OPENAI_MODEL_OVERRIDE": "gpt-5.4",
}

_SECRET_VALUES = [
    v for k, v in _SECRET_ENV.items() if k.endswith("_API_KEY")
]


def test_no_secret_value_in_resolution_dict():
    res = R.resolve_all(env=_SECRET_ENV)
    assert redact.assert_no_secret(res, _SECRET_VALUES), "secret leaked into resolution"


def test_no_secret_value_in_rendered_markdown():
    ev = R.build_model_selection_evidence(env=_SECRET_ENV)
    blob = ev["markdown"] + json.dumps(ev["resolution"], default=str) + json.dumps(
        ev["quorum"], default=str
    )
    for secret in _SECRET_VALUES:
        assert secret not in blob, "secret value leaked into rendered output"


def test_only_key_present_booleans_exposed():
    res = R.resolve_all(env=_SECRET_ENV)
    for provider in ("OPENAI", "ANTHROPIC", "XAI", "GOOGLE_GEMINI", "MISTRAL"):
        r = res["providers"][provider]
        assert r["provider_key_present"] is True
        # The dict carries the env *name*, never the value.
        serialized = json.dumps(r, default=str)
        for name in r["key_env"]:
            value = _SECRET_ENV.get(name)
            if value:
                assert value not in serialized


def test_key_present_false_when_absent():
    res = R.resolve_all(env={})
    for provider in ("OPENAI", "ANTHROPIC", "XAI", "GOOGLE_GEMINI", "MISTRAL"):
        assert res["providers"][provider]["provider_key_present"] is False


def test_resolver_modules_have_no_execution_surface():
    forbidden = list(contract.FORBIDDEN_EXECUTION_TOKENS) + [
        "place_order", "submit_order", "/v1/orders", "broker_execute",
        "auto_trade", "order_endpoint",
    ]
    for module in ("frontier_model_registry.py", "frontier_model_resolver.py"):
        text = (_REPO_ROOT / "scripts" / module).read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token.lower() not in text, (
                f"forbidden execution token {token!r} present in {module}"
            )


def test_resolver_makes_no_broker_or_trading_http_call():
    # The resolver must not embed any broker/trading endpoint host.
    for module in ("frontier_model_registry.py", "frontier_model_resolver.py"):
        text = (_REPO_ROOT / "scripts" / module).read_text(encoding="utf-8").lower()
        for host in ("alpaca", "binance", "zerodha", "kite.", "interactivebrokers",
                     "/orders", "/positions", "/account/trade"):
            assert host not in text, f"broker/trading surface {host!r} in {module}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
