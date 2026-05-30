"""Tests — runtime artifact hygiene (deterministic, pure).

Kanté Ceiling Push II, Workstream F.  Proves missing-stamp FAIL, stale-fresh
FAIL vs stale-disabled WARN, secret-value FAIL, and a clean canary PASS.  The
checker never deletes or mutates anything.
"""
from __future__ import annotations

import json

import pytest

from scripts.runtime_artifact_hygiene import (
    FAIL,
    PASS,
    WARN,
    check_artifact_file,
    evaluate_artifact,
)


def _stamped(**overrides):
    art = {
        "report": "canary",
        "generated_at_utc": "2026-05-30T00:00:00Z",
        "advisory_only": True,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "real_money_sizing_impact": "PROHIBITED",
        "real_money_weight_allowed": False,
        "status": "OK",
        "enabled": True,
    }
    art.update(overrides)
    return art


# --- 1 ----------------------------------------------------------------------
def test_artifact_hygiene_missing_stamp_fails():
    art = _stamped()
    del art["execution_gate"]
    r = evaluate_artifact(art, age_hours=1.0)
    assert r["verdict"] == FAIL
    assert "execution_gate" in r["required_stamp_missing"]


# --- 2 ----------------------------------------------------------------------
def test_artifact_hygiene_stale_live_fails():
    # Claims fresh (status OK, enabled) but well past TTL.
    r = evaluate_artifact(_stamped(), age_hours=72.0, ttl_hours=24.0)
    assert r["verdict"] == FAIL
    assert any("stale_fresh_artifact" in reason for reason in r["fail_reasons"])


# --- 3 ----------------------------------------------------------------------
def test_artifact_hygiene_stale_disabled_warns():
    art = _stamped(status="DISABLED", enabled=False)
    r = evaluate_artifact(art, age_hours=72.0, ttl_hours=24.0)
    assert r["verdict"] == WARN
    assert r["fail_reasons"] == []
    assert any("stale_disabled_artifact" in reason for reason in r["warn_reasons"])


# --- 4 ----------------------------------------------------------------------
def test_artifact_hygiene_secret_fails():
    art = _stamped(api_key="sk-live-1234567890abcdef")
    r = evaluate_artifact(art, age_hours=1.0)
    assert r["verdict"] == FAIL
    assert any("secret_like_value" in reason for reason in r["fail_reasons"])
    # A *_present boolean flag is NOT a secret leak.
    ok = evaluate_artifact(_stamped(openai_api_key_present=True), age_hours=1.0)
    assert ok["verdict"] == PASS


# --- 5 ----------------------------------------------------------------------
def test_artifact_hygiene_valid_canary_passes(tmp_path):
    r = evaluate_artifact(_stamped(), age_hours=1.0, ttl_hours=24.0)
    assert r["verdict"] == PASS
    assert r["fail_reasons"] == []
    assert r["real_money_sizing_impact"] == "PROHIBITED"

    # File mode is read-only: the file is unchanged after a check.
    path = tmp_path / "canary.json"
    payload = _stamped(generated_at_utc="2026-05-30T00:00:00Z")
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    res = check_artifact_file(path, now_utc="2026-05-30T02:00:00Z", ttl_hours=24.0)
    assert res["verdict"] == PASS
    assert res["artifact_age_hours"] == pytest.approx(2.0)
    assert path.read_text(encoding="utf-8") == before


def test_artifact_hygiene_real_money_prohibited():
    r = evaluate_artifact(_stamped(), age_hours=1.0)
    assert r["real_money_sizing_impact"] == "PROHIBITED"
    assert r["real_money_weight_allowed"] is False
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] is False
    assert r["ai_execution_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
