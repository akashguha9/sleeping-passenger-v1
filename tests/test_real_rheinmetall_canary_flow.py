"""Tests — Rheinmetall news canary flow (Kanté P2).

Deterministic, offline, no broker, no key. Proves the operator canary:
  * records every provider attempt honestly (GDELT -> NewsAPI -> Event Registry)
  * maps a fresh Rheinmetall article to RHM.DE and reports LIVE_VERIFIED
  * classifies timeout / unreachable / auth-fail / empty exactly per the spec
  * never crashes on a misbehaving provider
  * never persists, never trades, never hands off to synthesis
  * leaks no secret value even with keyed-provider env set
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts import rheinmetall_news_canary as canary
from scripts.news_provider_fallback_chain import (
    NewsProviderAuthFailed,
    NewsProviderTimeout,
)

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)


def _rhm_article(now=NOW, url="https://example.test/rhm"):
    return {
        "title": "Rheinmetall wins expanded defense order; backlog grows",
        "seendate": now.strftime("%Y%m%dT%H%M%SZ"),
        "sourcecountry": "Germany",
        "url": url,
    }


# --- 1. fresh Rheinmetall row -> LIVE_VERIFIED, mapped to RHM.DE -------------

def test_fresh_rheinmetall_maps_to_rhm_de_live_verified():
    rep = canary.run_canary(
        allow_network=True, now_utc=NOW, max_rows=10,
        transports={"gdelt": lambda q: [_rhm_article()]},
        env={},
    )
    assert rep["canary_status"] == canary.CANARY_LIVE_VERIFIED
    assert rep["live_verified"] is True
    assert rep["first_live_provider"] == "gdelt"
    te = rep["target_evidence"]
    assert te["target_ticker"] == "RHM.DE"
    assert te["fresh_target_rows"] >= 1
    assert te["max_freshness_score"] > 0
    assert te["max_mapping_confidence"] >= 0.70
    assert "Germany" in te["countries"]
    # GDELT went live first, so the chain honestly stops there (no needless
    # downstream provider calls); the full priority is still reported.
    gdelt = next(r for r in rep["provider_reports"] if r["provider"] == "gdelt")
    assert gdelt["status"] == "LIVE_VERIFIED"
    assert rep["provider_priority"] == ["gdelt", "newsapi", "event_registry"]


# --- 2. GDELT empty -> falls through; NewsAPI (injected) goes live ----------

def test_chain_falls_through_to_second_provider():
    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: [], "newsapi": lambda q: [_rhm_article()]},
        env={"NEWS_API_KEY": "x"},
    )
    assert rep["canary_status"] == canary.CANARY_LIVE_VERIFIED
    assert rep["first_live_provider"] == "newsapi"
    statuses = {r["provider"]: r["status"] for r in rep["provider_reports"]}
    assert statuses["gdelt"] == "OK_EMPTY"
    assert statuses["newsapi"] == "LIVE_VERIFIED"


# --- 3. empty everywhere -> OK_EMPTY + TARGET_NOT_FOUND, nothing fabricated --

def test_empty_response_is_ok_empty_and_target_not_found():
    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: []},
        env={},
    )
    assert rep["canary_status"] == canary.CANARY_TARGET_NOT_FOUND
    assert rep["live_verified"] is False
    assert rep["target_evidence"]["fresh_target_rows"] == 0
    statuses = {r["provider"]: r["status"] for r in rep["provider_reports"]}
    assert statuses["gdelt"] == "OK_EMPTY"
    assert rep["missing_layer_reason"]


# --- 4. timeout / unreachable classified exactly ----------------------------

def test_timeout_classified_as_provider_timeout():
    def _timeout(q):
        raise NewsProviderTimeout("synthetic timeout")

    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": _timeout}, env={},
    )
    statuses = {r["provider"]: r["status"] for r in rep["provider_reports"]}
    assert statuses["gdelt"] == "PROVIDER_TIMEOUT"
    assert rep["live_verified"] is False


def test_unreachable_classified_as_network_unreachable():
    def _down(q):
        raise ConnectionError("synthetic connection refused")

    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": _down}, env={},
    )
    statuses = {r["provider"]: r["status"] for r in rep["provider_reports"]}
    assert statuses["gdelt"] == "NETWORK_UNREACHABLE"
    assert rep["canary_status"] == canary.CANARY_ALL_PROVIDERS_FAILED


# --- 5. auth failure classified as PROVIDER_AUTH_FAILED ----------------------

def test_auth_failure_classified():
    def _auth(q):
        raise NewsProviderAuthFailed("401")

    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": _auth}, env={},
    )
    statuses = {r["provider"]: r["status"] for r in rep["provider_reports"]}
    assert statuses["gdelt"] == "PROVIDER_AUTH_FAILED"


# --- 6. stale article never claims LIVE_VERIFIED ----------------------------

def test_stale_article_not_live_verified():
    stale = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: [_rhm_article(now=stale, url="https://example.test/old")]},
        env={},
    )
    assert rep["live_verified"] is False
    assert rep["canary_status"] != canary.CANARY_LIVE_VERIFIED
    assert rep["target_evidence"]["fresh_target_rows"] == 0


# --- 7. no network, no transport -> honest NETWORK_DISABLED, no crash --------

def test_no_network_is_network_disabled():
    rep = canary.run_canary(allow_network=False, now_utc=NOW, env={})
    assert rep["canary_status"] in {
        canary.CANARY_NETWORK_DISABLED, canary.CANARY_NO_PROVIDER_CONFIGURED
    }
    assert rep["live_verified"] is False
    assert rep["target_evidence"]["fresh_target_rows"] == 0


# --- 8. a misbehaving provider never crashes the canary ---------------------

def test_misbehaving_provider_does_not_crash():
    def _boom(q):
        raise RuntimeError("synthetic provider explosion")

    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": _boom}, env={},
    )
    assert rep["report"] == "rheinmetall_news_canary"
    assert rep["live_verified"] is False


# --- 9. advisory / no-execution invariants + no persistence -----------------

def test_advisory_invariants_and_no_persistence():
    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: [_rhm_article()]}, env={},
    )
    assert rep["advisory_only"] is True
    assert rep["human_execution_required"] is True
    assert rep["executable_allowed"] is False
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["execution_gate"] == "LOCKED"
    assert rep["skip_synthesis"] is True
    assert rep["persisted_rows"] == 0
    assert rep["real_money_sizing_impact"] == "PROHIBITED"


# --- 10. no secret leak with keyed-provider env set -------------------------

def test_no_secret_leak_with_keys():
    env = {"NEWS_API_KEY": "newsapi-secret-aaa", "EVENT_REGISTRY_API_KEY": "er-secret-aaa"}
    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: [_rhm_article()]}, env=env,
    )
    blob = json.dumps(rep, default=str)
    for secret in env.values():
        assert secret not in blob
    assert rep["secret_leak_check_passed"] is True


# --- 11. CLI emits valid JSON and exits 0 -----------------------------------

def test_cli_json_offline_runs_clean(capsys):
    rc = canary.main(["--json"])  # no --allow-network: offline, honest
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["report"] == "rheinmetall_news_canary"
    assert payload["live_verified"] is False
    assert payload["secret_leak_check_passed"] is True


# --- 12. report write round-trip --------------------------------------------

def test_report_write_round_trip(tmp_path):
    rep = canary.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: [_rhm_article()]}, env={},
    )
    path = tmp_path / "rheinmetall_news_canary.json"
    canary.write_report(rep, path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["canary_status"] == canary.CANARY_LIVE_VERIFIED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
