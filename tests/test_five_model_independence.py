"""Tests for ``scripts.five_model_independence``."""
from __future__ import annotations

import json

from scripts import five_model_independence as fmi


def test_independent_reports_get_high_score():
    summary = fmi.build_summary()
    assert summary["five_model_independence_score"] >= 9.5
    assert summary["independent_model_count"] == 5
    assert summary["all_expected_models_seen"] is True


def test_contaminated_model_reduces_score():
    runs = [
        fmi.ModelRun(model_name=m, prompt=f"p-{m}",
                     input_context="c", output=f"o-{m}",
                     saw_other_model_outputs=(m == "claude"),
                     run_order=i + 1)
        for i, m in enumerate(fmi.EXPECTED_MODELS)
    ]
    contaminated = fmi.build_summary(runs)
    clean = fmi.build_summary()
    assert (contaminated["five_model_independence_score"]
            < clean["five_model_independence_score"])
    assert contaminated["contaminated_model_count"] == 1


def test_missing_model_reduces_coverage():
    runs = [
        fmi.ModelRun(model_name=m, prompt=f"p-{m}",
                     input_context="c", output=f"o-{m}",
                     run_order=i + 1)
        for i, m in enumerate(fmi.EXPECTED_MODELS[:-1])  # drop mistral
    ]
    summary = fmi.build_summary(runs)
    assert "mistral" in summary["missing_models"]
    assert summary["all_expected_models_seen"] is False
    assert summary["five_model_independence_score"] < 9.5


def test_synthesis_before_freeze_blocks():
    runs = list(fmi._fixture_runs())
    runs[0].independent_before_synthesis = False
    summary = fmi.build_summary(runs)
    assert summary["synthesis_before_freeze"] is True
    assert summary["five_model_independence_score"] < 9.5


def test_model_runs_ledger_records_rows():
    conn = fmi.open_db()
    try:
        for r in fmi._fixture_runs():
            fmi.record_model_run(conn, r)
        rows = conn.execute("SELECT model_name, advisory_only FROM model_runs").fetchall()
        assert len(rows) == len(fmi.EXPECTED_MODELS)
        assert all(r["advisory_only"] == 1 for r in rows)
    finally:
        conn.close()


def test_summary_writes_and_safety_invariants(tmp_path):
    target = tmp_path / "fmi.json"
    fmi.write_summary(target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["five_model_independence_score"] >= 9.5
    assert on_disk["advisory_only"] is True
    assert on_disk["broker_api_called"] is False
    assert on_disk["ai_execution_count"] == 0
