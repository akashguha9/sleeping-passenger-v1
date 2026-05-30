"""Tests — daily discovery refresh real flow (mission P1).

Deterministic, offline, no broker. Proves: --skip-network runs; mock-providers
run lifts C_price and proves C_global>0 end-to-end (Germany); the report is
emitted with the required fields; payloads rebuild; no secrets leak; and no
broker/order/execution tokens exist.
"""
from __future__ import annotations

import ast
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.persistence import init_schema
from scripts.run_daily_discovery_refresh import run_daily_refresh

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN = [
    "place_order", "submit_order", "execute_trade", "broker_execute",
    "broker_api(", "send_transaction", "auto_execute", "unlock_execution",
]

_REQUIRED_REPORT_KEYS = [
    "run_timestamp_utc", "dry_run", "network_allowed", "providers_attempted",
    "providers_configured", "providers_live_verified", "rows_fetched",
    "rows_written_signal_events", "price_marks_written", "payloads_rebuilt",
    "L_today_count", "country_coverage_summary", "C_global", "C_price",
    "C_news", "C_filings", "C_mapping", "H_price_coverage", "warnings",
    "safety_stamps",
]


def _env():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "refresh.db"
    init_schema(db)
    pdir = tmp / "payload"
    pdir.mkdir()
    return db, pdir


# --- skip-network mode -------------------------------------------------------

def test_skip_network_runs_and_emits_all_report_keys():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=False, use_mock_providers=False,
        now_utc=NOW, market_state="open", env={},
    )
    for key in _REQUIRED_REPORT_KEYS:
        assert key in rep, f"missing report key {key}"
    assert rep["network_allowed"] is False
    assert rep["payloads_rebuilt"] is True
    assert rep["refresh_success"] is True
    # no providers configured / network off -> nothing live, honest
    assert rep["providers_live_verified"] == 0
    assert rep["C_global"] == 0.0


# --- mock-providers mode -----------------------------------------------------

def test_mock_providers_lift_c_price_and_prove_c_global():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, use_mock_providers=True, now_utc=NOW,
        market_state="open", country_focus="Germany", env={},
    )
    assert rep["price_marks_written"] >= 5
    assert rep["C_price"] > 0.0
    assert rep["C_global"] == 0.0333
    assert rep["country_coverage_summary"]["first_covered_country"] == "Germany"
    assert rep["country_coverage_summary"]["global_status"] == "C_GLOBAL_POSITIVE"
    assert rep["providers_live_verified"] >= 1
    assert rep["L_today_count"] >= 1


# --- report written to disk --------------------------------------------------

def test_report_written_to_output_dir(tmp_path):
    db, pdir = _env()
    from scripts.run_daily_discovery_refresh import main

    rc = main([
        "--db-path", str(db), "--output-dir", str(tmp_path),
        "--use-mock-providers", "--market-state", "open",
    ])
    assert rc == 0
    report_path = tmp_path / "daily_refresh_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["payloads_rebuilt"] is True
    assert data["safety_stamps"]["execution_gate"] == "LOCKED"


# --- advisory invariants -----------------------------------------------------

def test_refresh_carries_advisory_invariants():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, use_mock_providers=True, now_utc=NOW, env={}
    )
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["execution_gate"] == "LOCKED"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["can_execute"] is False
    assert rep["new_risk_gate"]["execution_gate"] == "LOCKED"
    # new_risk_allowed is advisory only; it never unlocks execution
    assert rep["new_risk_gate"]["advisory_only"] is True


# --- dry-run does not persist / rebuild --------------------------------------

def test_dry_run_skips_persistence():
    db, pdir = _env()
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, use_mock_providers=True, dry_run=True, now_utc=NOW, env={}
    )
    assert rep["dry_run"] is True
    assert rep["payloads_rebuilt"] is False
    assert rep["price_marks_written"] == 0


# --- no secret leak ----------------------------------------------------------

def test_no_secret_in_report():
    db, pdir = _env()
    env = {
        "TWELVE_DATA_API_KEY": "td-secret-xyz", "COMPANIES_HOUSE_API_KEY": "ch-secret-xyz",
        "LSE_RNS_API_KEY": "rns-secret-xyz", "POLYGON_API_KEY": "pg-secret-xyz",
    }
    rep = run_daily_refresh(
        db_path=db, payload_dir=pdir, allow_network=False, use_mock_providers=True,
        now_utc=NOW, env=env,
    )
    blob = json.dumps(rep, default=str)
    for secret in env.values():
        assert secret not in blob
    assert rep["no_secret_leak"] is True


# --- no broker/order/execution tokens ----------------------------------------

def test_modules_have_no_execution_tokens():
    for name in ("run_daily_discovery_refresh.py", "real_price_provider.py",
                 "country_coverage_proof.py"):
        src = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        ast.parse(src)
        for tok in _FORBIDDEN:
            assert tok not in src, f"forbidden token {tok!r} in {name}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
