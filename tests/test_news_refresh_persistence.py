"""Tests — news fallback chain persistence into signal_events (Kanté P1).

Proves, deterministically and with NO network / NO API key, that
``run_daily_refresh`` now runs the GDELT -> NewsAPI -> Event Registry fallback
chain, persists the genuinely-fresh mapped rows into the canonical SQLite
``signal_events`` table, and that those rows flow through the bridge into the
country-coverage proof so Germany's real C_global becomes positive.

Hard safety: every assertion uses an OFFLINE injected transport (or no
transport at all). No row is fabricated; a failing / empty provider degrades
honestly; the advisory / no-execution invariants always hold.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import persistence
from scripts.run_daily_discovery_refresh import run_daily_refresh

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)


def _env():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "refresh.db"
    persistence.init_schema(db)
    pdir = tmp / "payload"
    pdir.mkdir()
    return db, pdir


def _rheinmetall_gdelt_transport(now=NOW):
    """Offline GDELT-shaped transport: ONE fresh Rheinmetall article, no ticker.

    The chain's own enrich+map path must resolve Germany / RHM.DE — nothing is
    pre-baked here, so a pass proves the genuine normalize->enrich->map->persist
    pipeline, not a fixture shortcut.
    """
    seendate = now.strftime("%Y%m%dT%H%M%SZ")

    def _t(query: str):
        if "rheinmetall" not in query.lower():
            return []
        return [{
            "title": "Rheinmetall wins expanded defense order; backlog grows",
            "seendate": seendate,
            "sourcecountry": "Germany",
            "url": "https://example.test/rhm-order",
        }]

    return _t


def _signal_events(db, source):
    return persistence.get_signal_events(source_name=source, limit=50, db_path=db)


# --- 1. injected real-shaped provider persists a mapped news row -------------

def test_injected_provider_persists_mapped_news_row_to_signal_events():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, market_state="open", country_focus="Germany",
        target_ticker="RHM.DE", env={},
        news_transports={"gdelt": _rheinmetall_gdelt_transport()},
    )
    # The fallback chain was attempted and went live on GDELT.
    assert rep["news_chain"]["first_live_provider"] == "gdelt"
    assert rep["news_rows_written_signal_events"] >= 1
    assert rep["rows_written_signal_events"] >= rep["news_rows_written_signal_events"]

    # The genuine row landed in signal_events under the gdelt source.
    rows = _signal_events(db, "gdelt")
    assert len(rows) >= 1
    raw = rows[0]["raw_payload"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    assert raw["ticker"] == "RHM.DE"
    assert raw["country"] == "Germany"
    assert raw["mapping_status"] == "MAPPED"
    assert float(raw["mapping_confidence"]) >= 0.70
    assert raw["is_live"] is True


# --- 2. persisted rows flow through the bridge into coverage -> C_global -----

def test_persisted_news_lifts_real_c_global_for_germany():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, market_state="open", country_focus="Germany",
        target_ticker="RHM.DE", env={},
        news_transports={"gdelt": _rheinmetall_gdelt_transport()},
    )
    # Germany covered end-to-end: news_support + mapping_support now satisfied
    # from genuinely-persisted-then-bridged SQLite rows.
    assert rep["C_global"] == pytest.approx(1 / 30, abs=1e-4)
    assert rep["C_news"] > 0.0
    assert rep["C_mapping"] > 0.0
    assert rep["country_coverage_summary"]["first_covered_country"] == "Germany"
    assert rep["country_coverage_summary"]["global_status"] == "C_GLOBAL_POSITIVE"
    assert rep["L_today_count"] >= 1


# --- 3. deterministic no-network mock fixture also proves it -----------------

def test_mock_providers_prove_c_global_through_chain():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, use_mock_providers=True, now_utc=NOW,
        market_state="open", country_focus="Germany", env={},
    )
    assert rep["C_global"] == pytest.approx(1 / 30, abs=1e-4)
    assert rep["news_rows_written_signal_events"] >= 1
    assert rep["news_chain"]["mode"] == "MOCK"
    # The persisted news row is genuinely mapped (not a pre-baked ticker fixture).
    rows = _signal_events(db, "gdelt")
    assert len(rows) >= 1


# --- 4. skip-network: no provider, no rows, no fake live, C_global = 0 -------

def test_skip_network_writes_no_news_rows_and_zero_c_global():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=False, use_mock_providers=False,
        now_utc=NOW, market_state="open", env={},
    )
    assert rep["news_rows_written_signal_events"] == 0
    assert rep["C_global"] == 0.0
    assert rep["news_chain"]["first_live_provider"] is None
    assert rep["news_chain"]["news_layer_present"] is False
    assert "news_support" in (rep["news_chain"]["missing_layers"] or [])
    # No news source rows were fabricated.
    assert _signal_events(db, "gdelt") == []


# --- 5. provider failure is classified honestly, never crashes, no fake row --

def test_provider_failure_is_honest_and_persists_nothing():
    db, pdir = _env()

    def _boom(query: str):
        raise ConnectionError("synthetic network failure")

    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, market_state="open", country_focus="Germany", env={},
        news_transports={"gdelt": _boom},
    )
    # The chain did not crash; it reported the failure and persisted nothing.
    assert rep["news_rows_written_signal_events"] == 0
    assert rep["C_global"] == 0.0
    statuses = {r["provider"]: r["status"] for r in rep["news_chain"]["provider_reports"]}
    assert statuses.get("gdelt") == "NETWORK_UNREACHABLE"
    assert _signal_events(db, "gdelt") == []


# --- 6. empty provider response -> OK_EMPTY, no fabricated row ---------------

def test_empty_provider_response_writes_nothing():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, market_state="open", country_focus="Germany", env={},
        news_transports={"gdelt": lambda q: []},
    )
    assert rep["news_rows_written_signal_events"] == 0
    assert rep["C_global"] == 0.0
    assert _signal_events(db, "gdelt") == []


# --- 7. stale article is never persisted as live ----------------------------

def test_stale_article_not_persisted_as_live():
    db, pdir = _env()
    stale = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)  # 28 days old

    def _stale_transport(query: str):
        if "rheinmetall" not in query.lower():
            return []
        return [{
            "title": "Rheinmetall older defense order story",
            "seendate": stale.strftime("%Y%m%dT%H%M%SZ"),
            "sourcecountry": "Germany",
            "url": "https://example.test/rhm-stale",
        }]

    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, market_state="open", country_focus="Germany", env={},
        news_transports={"gdelt": _stale_transport},
    )
    # Article exists but is stale -> not live -> not persisted, C_global stays 0.
    assert rep["news_rows_written_signal_events"] == 0
    assert rep["C_global"] == 0.0
    assert _signal_events(db, "gdelt") == []


# --- 8. dry-run never persists news rows ------------------------------------

def test_dry_run_persists_no_news_rows():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        dry_run=True, now_utc=NOW, country_focus="Germany", env={},
        news_transports={"gdelt": _rheinmetall_gdelt_transport()},
    )
    assert rep["dry_run"] is True
    assert rep["news_rows_written_signal_events"] == 0
    assert _signal_events(db, "gdelt") == []


# --- 9. advisory / no-execution invariants always hold ----------------------

def test_advisory_invariants_hold_with_news_chain():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, country_focus="Germany", env={},
        news_transports={"gdelt": _rheinmetall_gdelt_transport()},
    )
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["execution_gate"] == "LOCKED"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["can_execute"] is False
    assert rep["no_secret_leak"] is True
    assert rep["news_chain"]["secret_leak_check_passed"] is True


# --- 10. no secret leaks even with keyed-provider env set -------------------

def test_no_secret_leak_with_news_keys_set():
    db, pdir = _env()
    env = {
        "NEWS_API_KEY": "newsapi-secret-zzz",
        "EVENT_REGISTRY_API_KEY": "er-secret-zzz",
        "TWELVE_DATA_API_KEY": "td-secret-zzz",
    }
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=True, use_mock_providers=False,
        now_utc=NOW, country_focus="Germany", env=env,
        news_transports={"gdelt": _rheinmetall_gdelt_transport()},
    )
    blob = json.dumps(rep, default=str)
    for secret in env.values():
        assert secret not in blob
    assert rep["no_secret_leak"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
