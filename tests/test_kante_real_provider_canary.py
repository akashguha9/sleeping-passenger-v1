"""Tests — Kanté real-provider canary (deterministic, offline).

Proves the canary math, market-state TTL, honest degradation, secret-safety,
and the advisory-only safety posture WITHOUT any network. The real network path
(Yahoo public) is exercised only by the operator-run canary, never in CI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import json as _json

from scripts.kante_real_provider_canary import (
    CANARY_REPORT_PATH,
    HOLDINGS_H,
    T_CANARY,
    compute_canary,
    evaluate_mark,
    market_state,
    max_age_minutes_for,
    probe_prices,
    write_report,
)
from scripts.real_price_provider import build_mock_price_transport

# Top-level safety stamps the strict release-artifact coherence gate keys on.
_STRICT_COHERENCE_KEYS = (
    "advisory_status",
    "execution_gate",
    "broker_api_called",
    "ai_execution_count",
)
# Sprint-mandated top-level canary safety fields.
_REQUIRED_TOP_LEVEL = {
    "advisory_only": True,
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "real_money_sizing_impact": "PROHIBITED",
    "real_money_weight_allowed": False,
    "operator_execution_required": True,
    "proof_status": "ADVISORY_ONLY_CANARY_ARTIFACT",
}
# Per source/provider row safety stamps.
_REQUIRED_ROW = {
    "advisory_only": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "decision_impact": "ADVISORY_CONTEXT_ONLY",
    "execution_permission": "WATCH_ONLY",
}


# A fixed Saturday (weekend -> CLOSED everywhere) for determinism.
SATURDAY = datetime(2026, 5, 30, 7, 0, 0, tzinfo=timezone.utc)
# A fixed Wednesday inside the US/EU sessions for OPEN-state tests.
WEDNESDAY = datetime(2026, 5, 27, 15, 0, 0, tzinfo=timezone.utc)


# --- network is OFF by default ----------------------------------------------

def test_skip_network_degrades_honestly():
    out = probe_prices(T_CANARY, allow_network=False, now_utc=SATURDAY)
    assert out["resolver_status"] == "NETWORK_DISABLED"
    assert all(not r["valid_price"] for r in out["results"])
    assert all(r["status"] == "NETWORK_DISABLED" for r in out["results"])


def test_compute_canary_offline_is_empty_but_safe():
    report = compute_canary(allow_network=False, now_utc=SATURDAY)
    assert report["coverage_proof"]["C_global"] == 0.0
    assert report["holdings_coverage"]["H_price_coverage"] == 0.0
    assert report["new_risk_allowed"] is False
    assert report["secret_leak_check_passed"] is True
    assert report["safety"]["execution_gate"] == "LOCKED"
    assert report["safety"]["broker_api_called"] is False
    assert report["safety"]["ai_execution_count"] == 0
    # Top-level stamps too — required by the strict release-artifact coherence gate.
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0


# --- mock transport proves the math -----------------------------------------

def test_mock_transport_lifts_price_coverage():
    transports = {"yahoo": build_mock_price_transport(now_utc=SATURDAY)}
    report = compute_canary(transports=transports, now_utc=SATURDAY)
    rows = {r["ticker"]: r for r in report["canary_results"]}
    # Germany / UK / India / Japan / US all carry a valid mock price.
    assert rows["RHM.DE"]["valid_price"] is True
    assert rows["RHM.DE"]["currency"] == "EUR"
    assert rows["SHEL.L"]["valid_price"] is True
    assert rows["RELIANCE.NS"]["valid_price"] is True
    assert rows["7203.T"]["valid_price"] is True
    assert rows["MSFT"]["valid_price"] is True
    # C_price counts 5 distinct countries over the top-30 set.
    assert report["coverage_proof"]["C_price"] == round(5 / 30, 4)
    # Still advisory-only and no fabricated coverage.
    assert report["new_risk_allowed"] is False  # Germany lacks news/mapping
    assert report["secret_leak_check_passed"] is True


# --- valid_price predicate ---------------------------------------------------

def test_valid_price_requires_price_ts_currency():
    # Missing currency -> not valid.
    mark = {"price": 100.0, "timestamp_utc": SATURDAY.isoformat(), "currency": None,
            "provider": "yahoo"}
    res = evaluate_mark("RHM.DE", mark, SATURDAY)
    assert res["valid_price"] is False

    # Non-positive price -> not valid.
    mark2 = {"price": 0.0, "timestamp_utc": SATURDAY.isoformat(), "currency": "EUR",
             "provider": "yahoo"}
    assert evaluate_mark("RHM.DE", mark2, SATURDAY)["valid_price"] is False

    # Full, fresh mark -> valid + LIVE.
    mark3 = {"price": 525.0, "timestamp_utc": SATURDAY.isoformat(), "currency": "EUR",
             "provider": "yahoo"}
    ok = evaluate_mark("RHM.DE", mark3, SATURDAY)
    assert ok["valid_price"] is True
    assert ok["status"] == "LIVE_PRICE_VERIFIED"


def test_none_mark_is_symbol_unsupported():
    res = evaluate_mark("NOPE.ZZ", None, SATURDAY)
    assert res["valid_price"] is False
    assert res["status"] == "SYMBOL_UNSUPPORTED"


# --- market-state TTL --------------------------------------------------------

def test_weekend_is_closed_and_accepts_friday_close():
    assert market_state("RHM.DE", SATURDAY) == "CLOSED"
    # A Friday close (~16h earlier) is still valid on Saturday.
    friday_close = SATURDAY - timedelta(hours=16)
    mark = {"price": 1293.4, "timestamp_utc": friday_close.isoformat(),
            "currency": "EUR", "provider": "yahoo"}
    assert evaluate_mark("RHM.DE", mark, SATURDAY)["valid_price"] is True


def test_open_state_rejects_stale_intraday():
    assert market_state("MSFT", WEDNESDAY) == "OPEN"
    max_age, state = max_age_minutes_for("MSFT", WEDNESDAY)
    assert state == "OPEN"
    assert max_age == 60
    # A 3-hour-old intraday quote is stale when the market is OPEN.
    stale = WEDNESDAY - timedelta(hours=3)
    mark = {"price": 450.0, "timestamp_utc": stale.isoformat(),
            "currency": "USD", "provider": "yahoo"}
    res = evaluate_mark("MSFT", mark, WEDNESDAY)
    assert res["valid_price"] is False
    assert res["status"] == "PRICE_STALE"


def test_unknown_venue_flags_degraded():
    # A venue suffix we cannot place -> UNKNOWN, wider window + degraded flag.
    assert market_state("FOO.ZZ", WEDNESDAY) == "UNKNOWN"
    mark = {"price": 10.0, "timestamp_utc": (WEDNESDAY - timedelta(hours=2)).isoformat(),
            "currency": "USD", "provider": "yahoo"}
    res = evaluate_mark("FOO.ZZ", mark, WEDNESDAY)
    assert res["valid_price"] is True
    assert res["status"] == "DEGRADED_MARKET_STATE_UNKNOWN"


# --- secret-safety -----------------------------------------------------------

def test_secret_value_never_appears_in_report():
    fake_env = {
        "TWELVE_DATA_API_KEY": "SECRET_TWELVE_abc123def456",
        "ALPHA_VANTAGE_API_KEY": "SECRET_ALPHA_zzz999",
        "POLYGON_API_KEY": "SECRET_POLY_qqq000",
    }
    transports = {"yahoo": build_mock_price_transport(now_utc=SATURDAY)}
    report = compute_canary(transports=transports, env=fake_env, now_utc=SATURDAY)
    import json as _json

    blob = _json.dumps(report)
    for secret in fake_env.values():
        assert secret not in blob
    assert report["secret_leak_check_passed"] is True
    # The keyed providers still report presence honestly (boolean only).
    cfg = {c["provider"]: c for c in report["configured_providers"]}
    assert cfg["twelve_data"]["api_key_present"] is True
    assert cfg["twelve_data"]["configured"] is True


# --- holdings coverage threshold --------------------------------------------

# --- Section 2 — canary artifact safety-stamp coherence ---------------------

def test_kante_real_provider_canary_artifact_has_safety_stamps(tmp_path):
    """The canonically-written artifact carries every required top-level and
    per-row safety stamp."""
    transports = {"yahoo": build_mock_price_transport(now_utc=SATURDAY)}
    report = compute_canary(transports=transports, now_utc=SATURDAY)
    path = write_report(report, tmp_path / "canary.json")
    written = _json.loads(path.read_text(encoding="utf-8"))

    for key, expected in _REQUIRED_TOP_LEVEL.items():
        assert written[key] == expected, f"top-level {key}={written.get(key)!r}"
    # Nested safety dict mirrors the contract.
    assert written["safety"]["execution_gate"] == "LOCKED"
    assert written["safety"]["broker_api_called"] is False
    # Every provider/source row is stamped too.
    assert written["canary_results"], "expected canary result rows"
    for row in written["canary_results"]:
        for key, expected in _REQUIRED_ROW.items():
            assert row[key] == expected, f"row {row.get('ticker')} {key}={row.get(key)!r}"


def test_kante_real_provider_canary_writer_adds_safety_stamps(tmp_path):
    """Proves the stamps come from the canonical writer (not a manual JSON
    patch): a fresh in-memory report, never touched by hand, is fully stamped."""
    report = compute_canary(allow_network=False, now_utc=SATURDAY)
    # In-memory report (before any file write) already carries the stamps.
    for key, expected in _REQUIRED_TOP_LEVEL.items():
        assert report[key] == expected
    for row in report["canary_results"]:
        for key, expected in _REQUIRED_ROW.items():
            assert row[key] == expected
    # And the writer round-trips them faithfully.
    path = write_report(report, tmp_path / "out.json")
    reloaded = _json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["proof_status"] == "ADVISORY_ONLY_CANARY_ARTIFACT"


def test_canary_artifact_no_broker_or_execution_fields():
    """No positive broker/execution field may ever appear — top-level or row."""
    report = compute_canary(allow_network=False, now_utc=SATURDAY)
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["execution_gate"] == "LOCKED"
    assert report["executable_allowed"] is False
    assert report["real_money_weight_allowed"] is False
    assert report["safety"]["broker_order_id"] == "NONE"
    assert report["safety"]["can_execute"] is False
    for row in report["canary_results"]:
        assert row["broker_api_called"] is False
        assert row["ai_execution_count"] == 0
        assert row["execution_permission"] == "WATCH_ONLY"


def test_runtime_artifact_coherence_strict_canary_passes(tmp_path):
    """The freshly-written canary satisfies the strict-coherence stamp keys."""
    report = compute_canary(allow_network=False, now_utc=SATURDAY)
    path = write_report(report, tmp_path / "canary.json")
    data = _json.loads(path.read_text(encoding="utf-8"))
    for key in _STRICT_COHERENCE_KEYS:
        assert key in data, f"strict-coherence key missing: {key}"


def test_h_price_coverage_gate_and_new_risk_lock():
    # Force a universe where all 10 holdings get a valid price.
    universe = {h: ("USD", 100.0) for h in HOLDINGS_H}
    transports = {"yahoo": build_mock_price_transport(now_utc=SATURDAY, universe=universe)}
    report = compute_canary(transports=transports, now_utc=SATURDAY)
    hc = report["holdings_coverage"]
    assert hc["H_price_coverage"] == 1.0
    assert hc["existing_risk_visibility_ok"] is True
    # new_risk_allowed still requires C_global > 0 (Germany news/mapping absent),
    # and it NEVER unlocks execution regardless.
    assert report["new_risk_allowed"] is False
    assert report["executable_allowed"] is False
    assert report["safety"]["can_execute"] is False
