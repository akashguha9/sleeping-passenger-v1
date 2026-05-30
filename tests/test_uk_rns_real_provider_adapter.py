"""Tests — UK RNS real provider adapter (mission P2).

Deterministic, offline (injected transport / fixtures), no API key, no network.
Proves config-mode honesty (API key / source URL / none), row normalization,
stale/empty not live, network gating, mapped RNS row reaching the payload
(L_today), and that no credential value is ever logged.
"""
from __future__ import annotations

import json

import pytest

from scripts.global_filings_loader import (
    STATUS_LIVE_VERIFIED,
    STATUS_NETWORK_DISABLED,
    STATUS_OK_EMPTY,
    STATUS_PROVIDER_NOT_CONFIGURED,
    fetch_uk_rns_filings,
    normalize_uk_rns_row,
    rns_config_state,
)
from scripts.top30_country_coverage import build_country_coverage_from_payload

_FRESH = "2026-05-29T08:00:00+00:00"


def _rns_raw():
    return {
        "entity_name": "Shell", "ticker": "SHEL.L",
        "headline": "Shell plc half-year results", "event_type": "regulatory",
        "published_at_utc": _FRESH, "freshness_score": 1.0,
    }


# --- config modes ------------------------------------------------------------

def test_config_mode_api_key():
    state = rns_config_state({"LSE_RNS_API_KEY": "rns-secret"})
    assert state["mode"] == "API_KEY"
    assert state["configured"] is True
    assert state["api_key_present"] is True
    assert "rns-secret" not in json.dumps(state)  # value never present


def test_config_mode_source_url():
    state = rns_config_state({"RNS_SOURCE_URL": "https://example.test/rns.json"})
    assert state["mode"] == "SOURCE_URL"
    assert state["configured"] is True
    assert state["source_url_env"] == "RNS_SOURCE_URL"
    # only the env NAME, never the URL value
    assert "example.test" not in json.dumps(state)


def test_config_mode_none():
    state = rns_config_state({})
    assert state["mode"] == "NONE"
    assert state["configured"] is False


# --- normalization -----------------------------------------------------------

def test_normalized_row_shape():
    ev = normalize_uk_rns_row(_rns_raw())
    assert ev["source_name"] == "UK_RNS"
    assert ev["source_type"] == "disclosure"
    assert ev["country"] == "United Kingdom"
    assert ev["jurisdiction"] == "UK"
    assert ev["exchange"] == "LSE"
    assert ev["ticker"] == "SHEL.L"
    assert ev["is_live"] is True
    assert ev["fetched_at_utc"]
    assert ev["executable_allowed"] is False
    assert ev["advisory_only"] is True
    assert ev["human_review_required"] is True
    assert ev["safety"]["execution_gate"] == "LOCKED"


def test_stale_row_not_live():
    ev = normalize_uk_rns_row(
        {"entity_name": "Shell", "ticker": "SHEL.L",
         "published_at_utc": "2020-01-01T00:00:00+00:00"}
    )
    assert ev["is_live"] is False
    assert ev["freshness_score"] == 0.0


# --- fetch honesty -----------------------------------------------------------

def test_network_disabled_no_fetch():
    events, meta = fetch_uk_rns_filings(allow_network=False, env={})
    assert events == []
    assert meta["status"] == STATUS_NETWORK_DISABLED
    assert meta["is_live"] is False


def test_not_configured_with_network_is_honest():
    events, meta = fetch_uk_rns_filings(allow_network=True, env={})
    assert events == []
    assert meta["status"] == STATUS_PROVIDER_NOT_CONFIGURED
    assert meta["is_live"] is False


def test_injected_transport_empty_is_ok_empty():
    events, meta = fetch_uk_rns_filings(transport=lambda: [])
    assert events == []
    assert meta["status"] == STATUS_OK_EMPTY
    assert meta["is_live"] is False


def test_injected_transport_fresh_is_live_verified():
    events, meta = fetch_uk_rns_filings(transport=lambda: [_rns_raw()])
    assert meta["status"] == STATUS_LIVE_VERIFIED
    assert meta["is_live"] is True
    assert events[0]["ticker"] == "SHEL.L"


def test_transport_error_degrades_honestly():
    def _boom():
        raise RuntimeError("network down")

    events, meta = fetch_uk_rns_filings(transport=_boom)
    assert events == []
    assert meta["is_live"] is False
    assert meta["status"] in {"PROVIDER_ERROR", "PROVIDER_TIMEOUT"}


def test_fetch_meta_never_logs_secret():
    env = {"LSE_RNS_API_KEY": "rns-very-secret", "RNS_SOURCE_URL": "https://feed.secret/x"}
    _, meta = fetch_uk_rns_filings(transport=lambda: [_rns_raw()], env=env)
    blob = json.dumps(meta, default=str)
    assert "rns-very-secret" not in blob
    assert "feed.secret" not in blob


# --- fresh RNS row reaches the payload / L_today -----------------------------

def test_fresh_rns_row_reaches_payload_and_lifts_uk():
    events, _ = fetch_uk_rns_filings(transport=lambda: [_rns_raw()])
    payload = {
        "price_movers": {"movers": []},
        "news_events": {"events": []},
        "filings_events": {"events": events},
    }
    mapping_rows = [
        {"mapping_confidence": e["mapping_confidence"], "country": e["country"],
         "ticker": e["ticker"]}
        for e in events if e.get("ticker")
    ]
    cov = build_country_coverage_from_payload(
        payload, mapping_rows=mapping_rows, universe_records=[]
    )
    uk = next(r for r in cov["countries"] if r["country"] == "United Kingdom")
    assert uk["filings_support"] == 1
    assert uk["synthesis_consumed"] == 1  # reaches L_today / consumed payload
    assert cov["ratios"]["C_filings"] > 0.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
