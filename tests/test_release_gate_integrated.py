"""Tests for the Integrated Sprint hooks in release_gate.evaluate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import release_gate


def test_evaluate_emits_integrated_sprint_block(tmp_path, monkeypatch):
    # Run the real evaluate() against the live repo — it should never crash
    # and must surface the new integrated_sprint block.
    result = release_gate.evaluate()
    assert "integrated_sprint" in result
    block = result["integrated_sprint"]
    assert "typed_config_ok" in block
    assert "live_payload_quality_module_available" in block
    assert "model_reliability_ledger_ok" in block
    assert "compliance_surface_ok" in block
    # The release-gate JSON always exposes a verdict + advisory invariants.
    assert result["verdict"] in {release_gate.PASS, release_gate.WARN, release_gate.FAIL}


def test_evaluate_marks_typed_config_fail_when_safety_floor_violated(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ADVISORY_ONLY", "false")
    result = release_gate.evaluate()
    assert result["integrated_sprint"]["typed_config_ok"] is False
    assert result["verdict"] == release_gate.FAIL
    assert any("typed_config" in r for r in result["reasons"])


def test_evaluate_warns_when_business_value_summary_missing(monkeypatch, tmp_path):
    # Point the BVR module at a path that does not exist.
    from scripts import business_value_report as bvr
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(bvr, "DEFAULT_SUMMARY_PATH", missing, raising=False)
    result = release_gate.evaluate()
    block = result["integrated_sprint"]
    # The release gate must surface it; the verdict can be WARN or FAIL (FAIL
    # if other checks already failed) but it must not be PASS.
    assert block["business_value_ok"] is False
    assert result["verdict"] in {release_gate.WARN, release_gate.FAIL}


def test_evaluate_safety_stamps_preserved(monkeypatch):
    result = release_gate.evaluate()
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0


def test_evaluate_includes_warnings_and_blocking_lists(monkeypatch):
    result = release_gate.evaluate()
    assert isinstance(result.get("warnings", []), list)
    assert isinstance(result.get("blocking_reasons", []), list)
