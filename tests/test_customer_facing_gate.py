"""Customer-facing feature gate tests — proof_loop_hardening_sprint, Phase 5.

Pins the leakage control that hides the customer-facing layer until the
proof loop has actually closed.  Default = off.  Env override = DEMO_ONLY.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.customer_facing_gate import (
    CUSTOMER_FACING_DEMO_LABEL,
    CUSTOMER_FACING_DISABLED_MESSAGE,
    ENV_FLAG_NAME,
    N_REAL_FLOOR,
    evaluate_gate,
)


pytestmark = [
    pytest.mark.safety_floor,
]


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_default_disabled_when_no_artifacts_and_no_env(tmp_path):
    cr_path = tmp_path / "calibration_report.json"
    em_path = tmp_path / "evidence_manifest.json"
    # No files exist; no env flag.
    state = evaluate_gate(
        env={},
        calibration_report_path=cr_path,
        evidence_manifest_path=em_path,
    )
    assert state.customer_facing_enabled is False
    assert state.env_flag_true is False
    assert state.demo_only_label is None
    assert state.disabled_message == CUSTOMER_FACING_DISABLED_MESSAGE


def test_env_override_only_does_not_unlock_when_n_real_below_floor(tmp_path):
    cr_path = _write(tmp_path / "cal.json", {"calibration_status": "INSUFFICIENT_EVIDENCE", "n_real": 0})
    em_path = _write(tmp_path / "ev.json", {"evidence_status": "EMPTY"})
    state = evaluate_gate(
        env={ENV_FLAG_NAME: "1"},
        calibration_report_path=cr_path,
        evidence_manifest_path=em_path,
    )
    assert state.customer_facing_enabled is False
    assert state.env_flag_true is True
    # Env override surfaces DEMO_ONLY label without unlocking the gate.
    assert state.demo_only_label == CUSTOMER_FACING_DEMO_LABEL
    assert state.disabled_message is None


def test_gate_unlocked_only_when_env_and_n_real_and_status_all_pass(tmp_path):
    cr_path = _write(
        tmp_path / "cal.json", {"calibration_status": "MEASURED_PASS", "n_real": 250}
    )
    em_path = _write(
        tmp_path / "ev.json", {"evidence_status": "SUFFICIENT_FOR_INVESTOR_DEMO"}
    )
    state = evaluate_gate(
        env={ENV_FLAG_NAME: "1"},
        calibration_report_path=cr_path,
        evidence_manifest_path=em_path,
    )
    assert state.customer_facing_enabled is True
    assert state.env_flag_true is True
    assert state.demo_only_label is None
    assert state.disabled_message is None


def test_gate_locked_when_evidence_status_only_partial_even_at_n_real_threshold(tmp_path):
    cr_path = _write(
        tmp_path / "cal.json", {"calibration_status": "MEASURABLE_WITH_WARNING", "n_real": 25}
    )
    em_path = _write(tmp_path / "ev.json", {"evidence_status": "PARTIAL"})
    state = evaluate_gate(
        env={ENV_FLAG_NAME: "1"},
        calibration_report_path=cr_path,
        evidence_manifest_path=em_path,
    )
    assert state.customer_facing_enabled is False


def test_n_real_floor_constant_is_20():
    # Pin the contract for downstream readers.
    assert N_REAL_FLOOR == 20


def test_env_truthy_values():
    # Sanity: only canonical truthy values flip the override.
    for v in ("1", "true", "yes", "on", "True", "YES"):
        s = evaluate_gate(env={ENV_FLAG_NAME: v})
        assert s.env_flag_true is True
    for v in ("0", "false", "no", "off", "", "anything-else"):
        s = evaluate_gate(env={ENV_FLAG_NAME: v})
        assert s.env_flag_true is False


def test_customer_router_disabled_response_carries_safety_stamps(monkeypatch):
    """Default-off response must still carry advisory-only stamps."""
    monkeypatch.delenv(ENV_FLAG_NAME, raising=False)

    from scripts.api.routers import customer_router

    resp = customer_router.get_customer_baskets()
    assert resp.get("disabled") is True
    assert resp.get("reason") == CUSTOMER_FACING_DISABLED_MESSAGE
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0
    assert resp["human_review_required"] is True
    # The customer disclaimer must be present too.
    assert "disclaimer" in resp


def test_customer_router_demo_only_when_env_override_but_n_real_zero(monkeypatch):
    monkeypatch.setenv(ENV_FLAG_NAME, "1")

    from scripts.api.routers import customer_router

    resp = customer_router.get_customer_baskets()
    # Env override flips us out of disabled response into stamped response.
    assert resp.get("disabled") is not True
    assert resp.get("demo_only_label") == CUSTOMER_FACING_DEMO_LABEL
    gate = resp.get("customer_facing_gate")
    assert gate is not None
    assert gate["customer_facing_enabled"] is False
    assert gate["env_flag_true"] is True


def test_customer_router_no_execution_language_in_disabled_response(monkeypatch):
    monkeypatch.delenv(ENV_FLAG_NAME, raising=False)

    from scripts.api.routers import customer_router

    resp = customer_router.get_customer_baskets()
    text = json.dumps(resp).lower()
    forbidden = [
        "place order",
        "execute trade",
        "auto trade",
        "autotrade",
        "broker connected",
        "ai executed",
        "send order",
    ]
    for phrase in forbidden:
        assert phrase not in text, f"forbidden execution phrase leaked: {phrase}"
