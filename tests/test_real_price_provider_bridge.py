"""Tests — real price provider resolver + bridge (mission P3).

Deterministic, offline (injected transports), no API key, no broker. Proves
provider priority, honest missing-provider fallback, valid-price persistence,
C_price > 0, H_price_coverage, and that static fallback stays non-executable.
"""
from __future__ import annotations

import ast
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.persistence import init_schema
from scripts.real_price_provider import (
    ALPHA_VANTAGE,
    NETWORK_DISABLED,
    POLYGON,
    PRICE_PROVIDER_NOT_CONFIGURED,
    PRICE_PROVIDER_PRIORITY,
    PROVIDER_SELECTED,
    TWELVE_DATA,
    YAHOO,
    build_mock_price_transport,
    describe_price_providers,
    resolve_price_provider,
)
from scripts.refresh_live_price_marks import build_price_coverage, refresh_price_marks

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]

# Genuine execution-call patterns. (The module legitimately *blocklists* broker
# provider names like "alpaca_orders" in FORBIDDEN_PROVIDERS — that is safety
# code, not an execution call, so it is intentionally not scanned here.)
_FORBIDDEN = [
    "place_order(", "submit_order(", "execute_trade(", "broker_execute(",
    "send_transaction(", "auto_execute(",
]


def _fresh_db():
    db = Path(tempfile.mkdtemp()) / "px.db"
    init_schema(db)
    return db


# --- provider priority -------------------------------------------------------

def test_priority_order_is_yahoo_first():
    assert PRICE_PROVIDER_PRIORITY[0] == YAHOO
    assert set(PRICE_PROVIDER_PRIORITY) == {YAHOO, TWELVE_DATA, ALPHA_VANTAGE, POLYGON}


def test_injected_transport_selects_provider_offline():
    res = resolve_price_provider(
        allow_network=False,
        transports={YAHOO: build_mock_price_transport(NOW)},
        now_utc=NOW,
    )
    assert res["provider"] == YAHOO
    assert res["status"] == PROVIDER_SELECTED
    assert callable(res["callable"])


def test_prefer_keyed_provider_when_transport_injected():
    res = resolve_price_provider(
        allow_network=False,
        prefer=TWELVE_DATA,
        transports={TWELVE_DATA: build_mock_price_transport(NOW)},
        now_utc=NOW,
    )
    assert res["provider"] == TWELVE_DATA


def test_keyed_provider_configured_from_env():
    env = {"POLYGON_API_KEY": "pg-key"}
    descs = {d["provider"]: d for d in describe_price_providers(env)}
    assert descs[POLYGON]["configured"] is True
    assert descs[TWELVE_DATA]["configured"] is False
    assert descs[YAHOO]["configured"] is True  # public, no key


# --- honest fallback ---------------------------------------------------------

def test_missing_provider_network_off_is_network_disabled():
    res = resolve_price_provider(allow_network=False, env={}, now_utc=NOW)
    assert res["callable"] is None
    assert res["status"] == NETWORK_DISABLED


def test_no_provider_yields_c_price_zero():
    db = _fresh_db()
    rep = refresh_price_marks(["AAPL"], provider=None, db_path=db, now_utc=NOW)
    assert rep["written"] == 0
    cov = build_price_coverage(db, holdings=["AAPL"], now_utc=NOW, market_state="open")
    assert cov["C_price"] == 0.0


def test_forbidden_broker_provider_is_refused():
    res = resolve_price_provider(
        allow_network=True, prefer="alpaca_trading", env={}, now_utc=NOW
    )
    # broker/trading provider must never be selectable as a price source
    assert res["provider"] != "alpaca_trading"
    assert res["prefer_rejected_reason"] is not None


# --- valid price writes market_data + C_price > 0 ----------------------------

def test_mock_provider_writes_marks_and_lifts_c_price():
    db = _fresh_db()
    res = resolve_price_provider(
        allow_network=False, transports={YAHOO: build_mock_price_transport(NOW)}, now_utc=NOW
    )
    tickers = ["RHM.DE", "SHEL.L", "RELIANCE.NS", "7203.T", "MSFT"]
    rep = refresh_price_marks(tickers, provider=res["callable"], db_path=db, now_utc=NOW)
    assert rep["written"] == 5
    cov = build_price_coverage(
        db, holdings=["MSFT"], candidate_tickers=tickers, now_utc=NOW, market_state="open"
    )
    assert cov["C_price"] > 0.0  # Germany / UK / India / Japan / US covered
    assert cov["price_meta"]["valid_price_count"] >= 5


def test_h_price_coverage_computed_and_blocks_new_risk():
    db = _fresh_db()
    res = resolve_price_provider(
        allow_network=False, transports={YAHOO: build_mock_price_transport(NOW)}, now_utc=NOW
    )
    # Only one of two holdings is in the mock universe -> H_price_coverage = 0.5
    refresh_price_marks(["MSFT"], provider=res["callable"], db_path=db, now_utc=NOW)
    cov = build_price_coverage(
        db, holdings=["MSFT", "ZZZ.UNLISTED"], now_utc=NOW, market_state="open"
    )
    assert cov["H_price_coverage"] == 0.5
    from scripts.refresh_live_price_marks import evaluate_new_risk_gate

    gate = evaluate_new_risk_gate(cov["H_price_coverage"], cov["C_price"])
    assert gate["new_risk_allowed"] is False
    assert "EXISTING_RISK_VISIBILITY_DEGRADED" in gate["warnings"]
    assert gate["execution_gate"] == "LOCKED"


def test_null_price_does_not_count():
    db = _fresh_db()

    def _bad_provider(ticker):
        return {"price": None, "timestamp_utc": NOW.isoformat(), "currency": "USD"}

    rep = refresh_price_marks(["AAPL"], provider=_bad_provider, db_path=db, now_utc=NOW)
    assert rep["written"] == 0


# --- static fallback never executable ----------------------------------------

def test_static_fallback_remains_non_executable():
    from scripts.why_today import executable_candidate

    assert (
        executable_candidate(
            why_today_score_value=1.0,
            source_health_score=1.0,
            valid_price=True,
            mapping_confidence=1.0,
            country_coverage_confidence=1.0,
            in_phantom_closed_sold=False,
            is_static_universe_only=True,
        )
        is False
    )


# --- no broker / order / execution tokens ------------------------------------

def test_module_has_no_execution_tokens():
    src = (REPO_ROOT / "scripts" / "real_price_provider.py").read_text(encoding="utf-8")
    ast.parse(src)
    for tok in _FORBIDDEN:
        assert tok not in src, f"forbidden token {tok!r}"


def test_resolver_carries_locked_stamps():
    res = resolve_price_provider(allow_network=False, env={}, now_utc=NOW)
    assert res["broker_api_called"] is False
    assert res["ai_execution_count"] == 0
    assert res["execution_gate"] == "LOCKED"
    # no secret leak even when keys present
    env = {"TWELVE_DATA_API_KEY": "td-secret"}
    res2 = resolve_price_provider(allow_network=True, env=env, now_utc=NOW)
    assert "td-secret" not in json.dumps(res2, default=str)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
