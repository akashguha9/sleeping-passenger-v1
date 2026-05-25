"""Typed config / environment contract (Kanté Sprint 2 — Task 6)."""
from __future__ import annotations

import json

from scripts import config_contract as cc


def test_clean_local_config_warns_not_fails():
    # Empty env: optional keys unset → WARN, but nothing FAILs.
    report = cc.evaluate(env={})
    assert report["overall"] in ("WARN", "PASS")
    assert report["counts"]["FAIL"] == 0


def test_missing_db_path_fails():
    report = cc.evaluate(env={"MVP_DB_PATH": ""})
    assert report["overall"] == "FAIL"
    db_check = next(c for c in report["checks"] if c["name"] == "runtime_db_path")
    assert db_check["status"] == "FAIL"


def test_db_path_default_resolves_when_absent():
    report = cc.evaluate(env={})
    db_check = next(c for c in report["checks"] if c["name"] == "runtime_db_path")
    assert db_check["status"] == "PASS"


def test_optional_source_keys_warn():
    report = cc.evaluate(env={})
    src = next(c for c in report["checks"] if c["name"] == "optional_source_keys")
    assert src["status"] == "WARN"
    assert "XAI_API_KEY" in src["unset"]


def test_broker_execution_env_var_fails():
    report = cc.evaluate(env={"BROKER_API_KEY": "anything"})
    assert report["overall"] == "FAIL"
    danger = next(c for c in report["checks"] if c["name"] == "no_dangerous_env_vars")
    assert danger["status"] == "FAIL"
    assert "BROKER_API_KEY" in danger["dangerous"]


def test_live_execution_flag_fails():
    report = cc.evaluate(env={"PIPELINE_ENABLE_LIVE_EXECUTION": "true"})
    assert report["overall"] == "FAIL"
    flag = next(c for c in report["checks"] if c["name"] == "execution_flags_off")
    assert flag["status"] == "FAIL"


def test_paper_execution_flag_warns_only():
    report = cc.evaluate(env={"PIPELINE_ENABLE_PAPER_EXECUTION": "1"})
    flag = next(c for c in report["checks"] if c["name"] == "execution_flags_off")
    assert flag["status"] == "WARN"
    assert report["counts"]["FAIL"] == 0


def test_real_repo_env_example_has_no_drift():
    report = cc.evaluate(env={})
    assert report["drift"]["example_present"] is True
    assert report["drift"]["drift_count"] == 0, report["drift"]


def test_env_example_drift_detected(tmp_path):
    # A trimmed example missing several contract vars → drift > 0.
    (tmp_path / ".env.example").write_text(
        "API_HOST=127.0.0.1\nMVP_DB_PATH=runtime/mvp_local.db\n", encoding="utf-8"
    )
    report = cc.evaluate(env={}, repo_root=tmp_path)
    assert report["drift"]["drift_count"] > 0
    drift = next(c for c in report["checks"] if c["name"] == "env_example_drift")
    assert drift["status"] == "WARN"


def test_no_secret_values_printed():
    report = cc.evaluate(env={"XAI_API_KEY": "sk-supersecretvalue1234567890"})
    blob = json.dumps(report)
    assert "sk-supersecretvalue" not in blob


def test_cli_main_fails_closed_on_broker(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    assert cc.main(["--json"]) == 1
