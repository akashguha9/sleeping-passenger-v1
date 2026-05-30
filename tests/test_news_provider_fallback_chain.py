"""Tests — P2 read-only news provider fallback chain.

Deterministic, NO network, NO real API keys. Injected transports drive the
GDELT -> NewsAPI -> Event Registry fallback path and prove:
  1. GDELT timeout -> NewsAPI is attempted.
  2. NewsAPI empty -> Event Registry is attempted.
  3. A fresh Rheinmetall row maps to RHM.DE (conf >= 0.70).
  4. Provider statuses are honest (never LIVE_VERIFIED without a fresh row).
  5. No raw API key value appears in the report.
  6. Unmapped rows are retained with a reason.
  7. A provider exception never crashes the chain.
  8. No fake LIVE_VERIFIED on empty/failed providers.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.news_provider_fallback_chain import (
    EVENT_REGISTRY,
    GDELT_PUBLIC,
    LIVE_VERIFIED,
    NEWSAPI,
    NETWORK_DISABLED,
    OK_EMPTY,
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_TIMEOUT,
    NewsProviderTimeout,
    describe_news_providers,
    fetch_news_chain,
    provider_configured,
)

NOW = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
FRESH_ISO = NOW.isoformat()


def _rheinmetall_article():
    return {
        "title": "Rheinmetall wins major new defense order in Germany",
        "description": "Rheinmetall AG secured a multi-year artillery contract.",
        "url": "https://example.de/rheinmetall-order",
        "published_at": FRESH_ISO,
        "country": "Germany",
        "sourcecountry": "Germany",
    }


def _gdelt_timeout(_query):
    raise NewsProviderTimeout("gdelt timed out")


def _empty(_query):
    return []


def _rheinmetall_transport(_query):
    return [_rheinmetall_article()]


# --- 1 + 2 + 3: full fallback to Event Registry, mapped to RHM.DE -----------

def test_gdelt_timeout_then_newsapi_empty_then_event_registry_maps_rhm():
    report = fetch_news_chain(
        transports={
            GDELT_PUBLIC: _gdelt_timeout,
            NEWSAPI: _empty,
            EVENT_REGISTRY: _rheinmetall_transport,
        },
        now_utc=NOW,
    )
    reps = {r["provider"]: r for r in report["provider_reports"]}

    # GDELT attempted, timed out
    assert reps[GDELT_PUBLIC]["attempted"] is True
    assert reps[GDELT_PUBLIC]["status"] == PROVIDER_TIMEOUT

    # NewsAPI attempted after GDELT failed, returned empty (no fresh rows)
    assert reps[NEWSAPI]["attempted"] is True
    assert reps[NEWSAPI]["status"] in {OK_EMPTY, "DEGRADED_EMPTY"}
    assert reps[NEWSAPI]["fresh_rows"] == 0

    # Event Registry attempted after NewsAPI empty, returned a fresh mapped row
    assert reps[EVENT_REGISTRY]["attempted"] is True
    assert reps[EVENT_REGISTRY]["status"] == LIVE_VERIFIED
    assert reps[EVENT_REGISTRY]["fresh_rows"] >= 1
    assert reps[EVENT_REGISTRY]["mapped_rows"] >= 1

    assert report["first_live_provider"] == EVENT_REGISTRY
    rhm = [r for r in report["mapped_rows"] if r["ticker"] == "RHM.DE"]
    assert rhm, "Rheinmetall did not map to RHM.DE"
    assert rhm[0]["country"] == "Germany"
    assert rhm[0]["mapping_confidence"] >= 0.70
    assert rhm[0]["is_live"] is True


# --- 3b: first provider already live stops the chain ------------------------

def test_first_live_provider_stops_chain():
    report = fetch_news_chain(
        transports={
            GDELT_PUBLIC: _rheinmetall_transport,
            NEWSAPI: _rheinmetall_transport,
        },
        now_utc=NOW,
    )
    assert report["first_live_provider"] == GDELT_PUBLIC
    reps = {r["provider"]: r for r in report["provider_reports"]}
    # NewsAPI is never attempted because GDELT already went LIVE_VERIFIED.
    assert NEWSAPI not in reps or reps.get(NEWSAPI, {}).get("attempted") is not True


# --- 4 + 8: no fake LIVE_VERIFIED on stale rows -----------------------------

def test_stale_row_is_not_live_verified():
    stale = dict(_rheinmetall_article())
    stale["published_at"] = "2026-05-01T00:00:00+00:00"  # ~29 days old > 24h TTL
    report = fetch_news_chain(
        transports={GDELT_PUBLIC: lambda _q: [stale]}, now_utc=NOW
    )
    reps = {r["provider"]: r for r in report["provider_reports"]}
    assert reps[GDELT_PUBLIC]["status"] != LIVE_VERIFIED
    assert reps[GDELT_PUBLIC]["fresh_rows"] == 0
    assert report["first_live_provider"] is None
    assert report["news_layer_present"] is False
    assert report["missing_layers"] == ["news_support", "mapping_support"]


# --- 5: no secret leak ------------------------------------------------------

def test_no_api_key_in_report():
    env = {"NEWS_API_KEY": "newsapi-secret-123", "EVENT_REGISTRY_API_KEY": "er-secret-456"}
    report = fetch_news_chain(
        transports={GDELT_PUBLIC: _rheinmetall_transport}, env=env, now_utc=NOW
    )
    blob = json.dumps(report, default=str)
    assert "newsapi-secret-123" not in blob
    assert "er-secret-456" not in blob
    assert report["secret_leak_check_passed"] is True


# --- 6: unmapped rows retained with a reason --------------------------------

def test_unmapped_row_retained_with_reason():
    generic = {
        "title": "Global markets edged higher on light volume",
        "description": "No single security named.",
        "published_at": FRESH_ISO,
    }
    report = fetch_news_chain(
        transports={GDELT_PUBLIC: lambda _q: [generic]}, now_utc=NOW
    )
    assert report["rows"], "row was dropped"
    row = report["rows"][0]
    assert row["mapping_status"] == "UNMAPPED"
    assert row["mapping_failure_reason"]  # explicit reason present
    assert report["unmapped_row_count"] >= 1


# --- 7: provider exception never crashes ------------------------------------

def test_all_providers_fail_does_not_crash():
    def _boom(_query):
        raise RuntimeError("kaboom")

    report = fetch_news_chain(
        transports={GDELT_PUBLIC: _boom, NEWSAPI: _boom, EVENT_REGISTRY: _boom},
        now_utc=NOW,
    )
    assert report["first_live_provider"] is None
    assert report["news_layer_present"] is False
    for rep in report["provider_reports"]:
        assert rep["status"] != LIVE_VERIFIED


# --- config honesty ---------------------------------------------------------

def test_provider_configured_aliases():
    assert provider_configured(GDELT_PUBLIC) is True  # public, no key
    assert provider_configured(NEWSAPI, {"NEWSAPI_KEY": "k"}) is True
    assert provider_configured(NEWSAPI, {"NEWS_API_KEY": "k"}) is True
    assert provider_configured(NEWSAPI, {}) is False
    assert provider_configured(EVENT_REGISTRY, {"EVENTREGISTRY_API_KEY": "k"}) is True
    assert provider_configured(EVENT_REGISTRY, {}) is False


def test_offline_no_transport_keyed_providers_not_configured():
    report = fetch_news_chain(allow_network=False, env={}, now_utc=NOW)
    reps = {r["provider"]: r for r in report["provider_reports"]}
    assert reps[NEWSAPI]["status"] == PROVIDER_NOT_CONFIGURED
    assert reps[EVENT_REGISTRY]["status"] == PROVIDER_NOT_CONFIGURED
    # GDELT public is configured but network is off -> NETWORK_DISABLED
    assert reps[GDELT_PUBLIC]["status"] == NETWORK_DISABLED
    assert report["news_layer_present"] is False


def test_safety_stamps_present():
    report = fetch_news_chain(transports={GDELT_PUBLIC: _empty}, now_utc=NOW)
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["executable_allowed"] is False
