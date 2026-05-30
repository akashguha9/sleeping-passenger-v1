"""Tests for the consolidated daily operator Kanté report (P4).

Validates the report schema, the hard safety/no-execution invariants, the
secret-leak self-check, deterministic Germany metrics through the real
mock-provider refresh, and that the report is NOT written to disk by default.

Advisory only; no execution, no broker, no real network.
"""
from __future__ import annotations

import importlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import persistence

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)

REQUIRED_FIELDS = [
    "run_timestamp_utc",
    "provider_attempts",
    "secret_leak_check_passed",
    "rows_written_signal_events",
    "news_rows_written_signal_events",
    "filings_rows_written_signal_events",
    "L_today_count",
    "H_price_coverage",
    "C_global",
    "C_price",
    "C_news",
    "C_mapping",
    "coverage_by_country",
    "first_covered_country",
    "payload_stale",
    "sqlite_fresh_rows_count",
    "new_risk_allowed",
    "execution_gate",
    "broker_api_called",
    "ai_execution_count",
    "warnings",
    "next_missing_layers",
]


def _mod():
    return importlib.import_module("scripts.run_daily_discovery_refresh")


def _env():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "refresh.db"
    persistence.init_schema(db)
    pdir = tmp / "payload"
    pdir.mkdir()
    return tmp, db, pdir


def _refresh(**kw):
    mod = _mod()
    _tmp, db, pdir = _env()
    rep = mod.run_daily_refresh(
        db_path=db, payload_dir=pdir, use_mock_providers=True, now_utc=NOW,
        market_state="open", country_focus="Germany", env={}, **kw
    )
    return rep


def test_operator_report_present_in_refresh():
    rep = _refresh()
    assert "operator_report" in rep
    assert isinstance(rep["operator_report"], dict)


def test_operator_report_schema_complete():
    op = _refresh()["operator_report"]
    missing = [f for f in REQUIRED_FIELDS if f not in op]
    assert missing == [], "missing operator-report fields: %s" % missing


def test_operator_report_safety_invariants():
    op = _refresh()["operator_report"]
    assert op["execution_gate"] == "LOCKED"
    assert op["broker_api_called"] is False
    assert op["ai_execution_count"] == 0


def test_operator_report_secret_leak_check():
    op = _refresh()["operator_report"]
    assert op["secret_leak_check_passed"] is True
    # Scan for secret-VALUE shapes, not the legitimate field name
    # ``secret_leak_check_passed`` (which legitimately contains "secret").
    blob = json.dumps(op).lower()
    for needle in ("api_key=", "apikey=", "password=", "bearer ", "token="):
        assert needle not in blob


def test_operator_report_no_secret_leak_with_keys_set():
    # Even with keyed-provider secrets configured, no value may appear.
    mod = _mod()
    _tmp, db, pdir = _env()
    env = {
        "NEWS_API_KEY": "newsapi-secret-qqq",
        "EVENT_REGISTRY_API_KEY": "er-secret-qqq",
        "TWELVE_DATA_API_KEY": "td-secret-qqq",
    }
    rep = mod.run_daily_refresh(
        db_path=db, payload_dir=pdir, use_mock_providers=True, now_utc=NOW,
        market_state="open", country_focus="Germany", env=env,
    )
    op = rep["operator_report"]
    assert op["secret_leak_check_passed"] is True
    blob = json.dumps(op, default=str)
    for secret in env.values():
        assert secret not in blob


def test_operator_report_deterministic_germany_metrics():
    op = _refresh()["operator_report"]
    # Deterministic mock-provider path persists a mapped Germany news row.
    assert op["rows_written_signal_events"] >= 1
    assert op["C_global"] == pytest.approx(1 / 30, abs=1e-4)
    assert op["coverage_by_country"].get("Germany") == 1
    assert op["first_covered_country"] == "Germany"
    assert op["payload_stale"] is False  # fresh rows written


def test_operator_report_not_written_by_default(tmp_path):
    mod = _mod()
    db = tmp_path / "s.db"
    rc = mod.main(["--db-path", str(db), "--use-mock-providers",
                   "--output-dir", str(tmp_path), "--country-focus", "Germany"])
    assert rc == 0
    # No operator-report file unless --operator-report-out is given.
    assert not list(tmp_path.glob("*operator*"))


def test_operator_report_written_when_flag_set(tmp_path):
    mod = _mod()
    db = tmp_path / "s.db"
    out = tmp_path / "daily_operator_kante_report.json"
    rc = mod.main(["--db-path", str(db), "--use-mock-providers",
                   "--output-dir", str(tmp_path), "--country-focus", "Germany",
                   "--operator-report-out", str(out)])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    assert missing == []
    assert data["execution_gate"] == "LOCKED"
    assert data["broker_api_called"] is False
    assert data["secret_leak_check_passed"] is True


def test_build_arg_parser_exposes_real_canary_flags():
    parser = _mod().build_arg_parser()
    ns = parser.parse_args(
        [
            "--allow-network",
            "--country-focus", "Germany",
            "--target-ticker", "RHM.DE",
            "--news-query", "Rheinmetall",
            "--max-rows", "10",
            "--skip-synthesis",
            "--operator-report-out", "x.json",
        ]
    )
    assert ns.allow_network is True
    assert ns.country_focus == "Germany"
    assert ns.target_ticker == "RHM.DE"
    assert ns.news_query == ["Rheinmetall"]
    assert ns.max_rows == 10
    assert ns.operator_report_out == "x.json"
