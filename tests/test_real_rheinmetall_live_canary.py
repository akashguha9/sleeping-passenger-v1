"""Tests for the real Rheinmetall live canary path (P2).

The live news-canary path must be:
* network-gated (OFFLINE by default; no real network call here),
* advisory-only, no persistence, no synthesis hand-off,
* honest about provider status (never fabricates rows on failure),
* able to map a fresh Rheinmetall row to RHM.DE / Germany IF a provider returns
  one — and to lift real C_global through the refresh+SQLite bridge.

All network I/O is monkeypatched with offline injected transports, so the test
is deterministic and never touches the wire. Mirrors the spec's provider
verification predicate.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import persistence

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)


def _canary():
    return importlib.import_module("scripts.rheinmetall_news_canary")


def _refresh():
    return importlib.import_module("scripts.run_daily_discovery_refresh")


def _rhm_article(now=NOW, url="https://example.test/rhm"):
    return {
        "title": "Rheinmetall wins expanded defense order; backlog grows",
        "seendate": now.strftime("%Y%m%dT%H%M%SZ"),
        "sourcecountry": "Germany",
        "url": url,
    }


def _db_pdir():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "refresh.db"
    persistence.init_schema(db)
    pdir = tmp / "payload"
    pdir.mkdir()
    return db, pdir


# --- 1. canary offline is an honest, advisory skip --------------------------

def test_canary_offline_is_network_disabled():
    mod = _canary()
    rep = mod.run_canary(allow_network=False, now_utc=NOW, env={})
    assert rep["canary_status"] in {
        mod.CANARY_NETWORK_DISABLED, mod.CANARY_NO_PROVIDER_CONFIGURED
    }
    assert rep["live_verified"] is False
    assert rep["target_evidence"]["fresh_target_rows"] == 0
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["execution_gate"] == "LOCKED"


# --- 2. fresh Rheinmetall row maps to RHM.DE and reports LIVE_VERIFIED -------

def test_fresh_row_maps_to_rhm_de_live_verified():
    mod = _canary()
    rep = mod.run_canary(
        allow_network=True, now_utc=NOW, max_rows=10,
        transports={"gdelt": lambda q: [_rhm_article()]}, env={},
    )
    assert rep["canary_status"] == mod.CANARY_LIVE_VERIFIED
    assert rep["live_verified"] is True
    te = rep["target_evidence"]
    assert te["target_ticker"] == "RHM.DE"
    assert te["fresh_target_rows"] >= 1
    assert te["max_freshness_score"] > 0


# --- 3. provider failure is classified honestly, nothing fabricated ---------

def test_provider_failure_records_status_without_fabricating():
    mod = _canary()

    def _down(q):
        raise ConnectionError("synthetic connection refused")

    rep = mod.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": _down}, env={},
    )
    statuses = {r["provider"]: r["status"] for r in rep["provider_reports"]}
    assert statuses["gdelt"] == "NETWORK_UNREACHABLE"
    assert rep["live_verified"] is False
    assert rep["target_evidence"]["fresh_target_rows"] == 0


# --- 4. empty everywhere -> OK_EMPTY + TARGET_NOT_FOUND ----------------------

def test_empty_is_ok_empty_and_target_not_found():
    mod = _canary()
    rep = mod.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: []}, env={},
    )
    assert rep["canary_status"] == mod.CANARY_TARGET_NOT_FOUND
    statuses = {r["provider"]: r["status"] for r in rep["provider_reports"]}
    assert statuses["gdelt"] == "OK_EMPTY"


# --- 5. canary leaks no secret even with keyed-provider env set --------------

def test_no_secret_leak_with_keys():
    mod = _canary()
    env = {"NEWS_API_KEY": "newsapi-secret-aaa", "EVENT_REGISTRY_API_KEY": "er-secret-aaa"}
    rep = mod.run_canary(
        allow_network=True, now_utc=NOW,
        transports={"gdelt": lambda q: [_rhm_article()]}, env=env,
    )
    blob = json.dumps(rep, default=str)
    for secret in env.values():
        assert secret not in blob
    assert rep["secret_leak_check_passed"] is True


# --- 6. live row persists through refresh into signal_events + real C_global -

def test_live_row_persists_and_lifts_real_c_global():
    mod = _refresh()
    db, pdir = _db_pdir()
    rep = mod.run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, market_state="open", country_focus="Germany",
        target_ticker="RHM.DE", env={},
        news_transports={"gdelt": lambda q: [_rhm_article()] if "rheinmetall" in q.lower() else []},
    )
    assert rep["news_rows_written_signal_events"] >= 1
    assert rep["C_global"] == pytest.approx(1 / 30, abs=1e-4)
    with sqlite3.connect(str(db)) as conn:
        n = conn.execute(
            "select count(*) from signal_events where source_name='gdelt'"
        ).fetchone()[0]
    assert n >= 1


# --- 7. skip-network persists nothing and keeps C_global = 0 -----------------

def test_skip_network_persists_nothing_zero_c_global():
    mod = _refresh()
    db, pdir = _db_pdir()
    rep = mod.run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=False, use_mock_providers=False,
        now_utc=NOW, market_state="open", env={},
    )
    assert rep["news_rows_written_signal_events"] == 0
    assert rep["C_global"] == 0.0


# --- 8. provider_live_verified predicate (spec Section: provider verification) -

def test_provider_live_verified_predicate():
    def verified(verdict):
        return (
            verdict.get("ok") is True
            and verdict.get("status") in ("OK", "LIVE_VERIFIED", 200)
            and (verdict.get("rows", 1) or 0) > 0
            and (verdict.get("freshness_score", 0.0) or 0.0) > 0
        )

    ok = {"ok": True, "status": "LIVE_VERIFIED", "rows": 1, "freshness_score": 1.0}
    empty = {"ok": False, "status": "OK_EMPTY", "rows": 0, "freshness_score": 0.0}
    unreachable = {"ok": False, "status": "NETWORK_UNREACHABLE", "freshness_score": 0.0}
    assert verified(ok) is True
    assert verified(empty) is False
    assert verified(unreachable) is False
