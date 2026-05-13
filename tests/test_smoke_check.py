"""
Tests for scripts/smoke_check.py.

We avoid hitting a real backend by monkey-patching the module-level
_http_get_json shim to a stub that returns a canned (payload, error) tuple.
"""
from __future__ import annotations

from typing import Any

import pytest

import scripts.smoke_check as sc


_HEALTHY: dict[str, Any] = {
    "status": "ok",
    "advisory_status": "ADVISORY_ONLY",
    "execution_mode": "HUMAN_ONLY",
    "execution_gate": "LOCKED",
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
    "human_review_required": True,
    "version": "1.0.0",
    "environment": "local",
    "db_available": True,
    "db_path": "runtime/mvp_local.db",
    "api_token_required": False,
    "allowed_origins_count": 4,
    "generated_at": "2026-05-13T00:00:00+00:00",
}


def _patch_http(monkeypatch, payload, error=None) -> None:
    def fake(url: str, timeout: float):  # noqa: ARG001
        return payload, error

    monkeypatch.setattr(sc, "_http_get_json", fake)


def test_healthy_backend_passes(monkeypatch):
    _patch_http(monkeypatch, dict(_HEALTHY))
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is True
    names = {c["name"]: c["status"] for c in result["checks"]}
    assert names["backend_reachable"] == "PASS"
    assert names["advisory_status"] == "PASS"
    assert names["execution_gate"] == "PASS"
    assert names["broker_api_called"] == "PASS"
    assert names["ai_execution_count"] == "PASS"
    assert names["db_available"] == "PASS"


def test_backend_unreachable_fails(monkeypatch):
    _patch_http(monkeypatch, None, "unreachable: Connection refused")
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is False
    first = result["checks"][0]
    assert first["name"] == "backend_reachable"
    assert first["status"] == "FAIL"
    assert "unreachable" in first["detail"]


def test_malformed_json_fails(monkeypatch):
    _patch_http(monkeypatch, None, "malformed json: line 1 column 1")
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is False
    assert result["checks"][0]["status"] == "FAIL"


def test_missing_advisory_status_fails(monkeypatch):
    payload = dict(_HEALTHY)
    payload.pop("advisory_status")
    _patch_http(monkeypatch, payload)
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["advisory_status"]["status"] == "FAIL"


def test_unlocked_execution_gate_fails(monkeypatch):
    payload = dict(_HEALTHY)
    payload["execution_gate"] = "OPEN"
    _patch_http(monkeypatch, payload)
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["execution_gate"]["status"] == "FAIL"


def test_broker_api_called_true_fails(monkeypatch):
    payload = dict(_HEALTHY)
    payload["broker_api_called"] = True
    _patch_http(monkeypatch, payload)
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["broker_api_called"]["status"] == "FAIL"


def test_ai_execution_count_nonzero_fails(monkeypatch):
    payload = dict(_HEALTHY)
    payload["ai_execution_count"] = 1
    _patch_http(monkeypatch, payload)
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["ai_execution_count"]["status"] == "FAIL"


def test_db_unavailable_fails(monkeypatch):
    payload = dict(_HEALTHY)
    payload["db_available"] = False
    _patch_http(monkeypatch, payload)
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is False
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["db_available"]["status"] == "FAIL"


def test_cli_exit_zero_on_healthy(monkeypatch, capsys):
    _patch_http(monkeypatch, dict(_HEALTHY))
    rc = sc.main(["--api", "http://127.0.0.1:8000"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "RESULT: PASS" in out


def test_cli_exit_nonzero_when_unreachable(monkeypatch, capsys):
    _patch_http(monkeypatch, None, "unreachable: Connection refused")
    rc = sc.main(["--api", "http://127.0.0.1:8000"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "RESULT: FAIL" in out


def test_cli_json_mode(monkeypatch, capsys):
    import json
    _patch_http(monkeypatch, dict(_HEALTHY))
    rc = sc.main(["--api", "http://127.0.0.1:8000", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out.strip())
    assert rc == 0
    assert payload["ok"] is True
    assert payload["api_base"] == "http://127.0.0.1:8000"
    assert payload["health"]["advisory_status"] == "ADVISORY_ONLY"


def test_invalid_timeout(capsys):
    rc = sc.main(["--timeout", "0"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "RESULT: FAIL" in out


def test_token_required_is_info_not_fail(monkeypatch):
    payload = dict(_HEALTHY)
    payload["api_token_required"] = True
    _patch_http(monkeypatch, payload)
    result = sc.run_smoke_check("http://127.0.0.1:8000")
    assert result["ok"] is True
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["api_token_required"]["status"] == "INFO"
