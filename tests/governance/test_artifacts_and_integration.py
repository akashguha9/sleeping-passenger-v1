"""Sections 18/19 — artifact writing + pipeline integration."""
from __future__ import annotations

import json

from scripts.governance.artifacts import ARTIFACT_NAMES, write_governance_artifacts


def test_artifacts_written_with_safety_header(gov_result, tmp_path):
    written = write_governance_artifacts(gov_result, tmp_path, run_id="test_run")
    for name in ARTIFACT_NAMES:
        path = tmp_path / name
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["run_date"] == "2026-06-05"
        assert payload["schema_version"]
        assert payload["source_health_status"] == "FAILED"
        assert payload["execution_gate_status"] == "LOCKED"
        assert payload["new_risk_permission"] is False
        assert payload["human_execution_required"] is True
        assert payload["broker_execution_allowed"] is False
    # dated archive preserved
    archive = tmp_path / "governance_history" / "2026-06-05__test_run"
    assert archive.exists()
    assert (archive / "daily_final_decision_board.json").exists()
    # both canonical + archive copies written
    assert len(written) == len(ARTIFACT_NAMES) * 2


def test_pipeline_attach_governance_is_additive(gov_inputs):
    from scripts.daily_synthesis_pipeline import attach_daily_governance

    base = {"run_date": "2026-06-05"}
    # no inputs => unchanged
    assert attach_daily_governance(dict(base)) == base
    # with inputs => governance attached, gate is the source of truth
    out = attach_daily_governance(dict(base), gov_inputs)
    assert "daily_governance" in out
    assert out["daily_governance"]["no_new_risk_day"] == "YES"
    assert out["daily_governance"]["execution_gate_status"] == "LOCKED"


def test_governance_labels_rendered(gov_inputs):
    from scripts.daily_synthesis_pipeline import _render_governance_labels, attach_daily_governance

    result = attach_daily_governance({"run_date": "2026-06-05"}, gov_inputs)
    lines = "\n".join(_render_governance_labels(result))
    assert "EXECUTION_GATE_LOCKED" in lines
    assert "SOURCE_HEALTH_FAILED" in lines
    assert "NO_NEW_RISK_DAY" in lines
    assert "EXISTING_POSITION_MANAGEMENT_ONLY" in lines
