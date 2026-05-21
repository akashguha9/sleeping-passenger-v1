"""Release gate + deploy preflight — Kanté positioning: no broken/unsafe deploy.

Proves the gate FAILS on an unlocked execution flag or fake Moltbook
pollution, WARNS when the backend is down but offline checks pass, PASSES a
clean local DB, and never calls a broker API.
"""
from __future__ import annotations

import sqlite3

import scripts.persistence as persistence
from scripts import release_gate, local_deploy_preflight as preflight


def _clean_db(tmp_path):
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    return db


def _no_backend(monkeypatch):
    # Point the health probe at a closed local port so the probe is
    # deterministic regardless of whether a real backend is running.
    monkeypatch.setenv("MVP_BACKEND_HEALTH_URL", "http://127.0.0.1:9/health")


def test_release_gate_passes_clean_local_db(tmp_path):
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "PASS", result["reasons"]
    assert result["fail_count"] == 0


def test_release_gate_fails_if_execution_unlocked(tmp_path):
    db = _clean_db(tmp_path)
    # Defence-in-depth violation: a row claiming a broker call.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side,"
            " quantity, price, executed_at, broker_api_called)"
            " VALUES ('T1','E1','AAPL','BUY',1,1,'t',1)"
        )
        conn.commit()
    finally:
        conn.close()
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "FAIL"
    assert "execution_gate_locked" in result["failing_checks"]


def test_release_gate_fails_if_fake_moltbook_pollution(tmp_path):
    db = _clean_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO moltbook_entries (entry_id, event_id, ticker,"
            " original_signal_thesis, mistake_type, lesson_learned, logged_at,"
            " manual_trade_log_id)"
            " VALUES ('MB1','FABRIC_SPY','SPY','Persistence above 0.8',"
            " 'no_trade_correct','demo','t','')"
        )
        conn.commit()
    finally:
        conn.close()
    result = release_gate.evaluate(db, check_backend=False)
    assert result["verdict"] == "FAIL"
    assert "moltbook_no_fake_pollution" in result["failing_checks"]


def test_release_gate_warns_if_backend_down_but_offline_ok(tmp_path, monkeypatch):
    db = _clean_db(tmp_path)
    _no_backend(monkeypatch)
    result = release_gate.evaluate(db, check_backend=True)
    assert result["verdict"] == "WARN"
    assert result["fail_count"] == 0
    assert "backend_health" in result["warning_checks"]


def test_release_gate_fails_when_db_missing(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    result = release_gate.evaluate(missing, check_backend=False)
    assert result["verdict"] == "FAIL"
    assert "runtime_db_exists" in result["failing_checks"]


def test_release_gate_never_calls_broker_apis():
    import pathlib
    for mod in (release_gate, preflight):
        text = pathlib.Path(mod.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("place_order(", "submit_order(", "execute_trade(",
                          "broker.execute", "import alpaca", "import ib_insync"):
            assert forbidden not in text, (mod.__file__, forbidden)


def test_release_gate_is_advisory_only(tmp_path):
    db = _clean_db(tmp_path)
    result = release_gate.evaluate(db)
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0


def test_preflight_bridge_idempotency_check_passes_clean(tmp_path):
    db = _clean_db(tmp_path)
    chk = preflight.check_moltbook_bridge_idempotent(db)
    assert chk["status"] == "PASS"
