"""Broken-windows repair-debt report.

Proves broken windows are detected, a clean state passes, repair debt affects
the release gate, and the report stays advisory-only.
"""
from __future__ import annotations

import scripts.persistence as persistence
from scripts import broken_windows_report as bwr


def test_clean_state_passes():
    out = bwr.assess_broken_windows({})
    assert out["release_gate_impact"] == "CLEAR"
    assert out["repair_debt_score"] == 0.0
    assert out["critical_broken_windows"] == {}
    assert "intact" in out["recommended_next_repair"].lower()


def test_fake_rows_are_critical_and_block():
    out = bwr.assess_broken_windows({"fake_rows_detected": 3})
    assert out["release_gate_impact"] == "BLOCK"
    assert out["critical_broken_windows"]["fake_rows_detected"] == 3
    assert out["repair_debt_score"] > 0.0


def test_unlogged_loss_is_critical():
    out = bwr.assess_broken_windows({"closed_losses_without_moltbook": 2})
    assert out["release_gate_impact"] == "BLOCK"
    assert out["critical_broken_windows"]["unlogged_losses"] == 2


def test_medium_windows_warn_not_block():
    out = bwr.assess_broken_windows({
        "manual_trades_missing_reconciliation": 1,
        "stale_sources": 2,
    })
    assert out["release_gate_impact"] == "WARN"
    assert out["critical_count"] == 0
    assert out["medium_count"] == 3


def test_repair_debt_affects_readiness_monotonic():
    light = bwr.assess_broken_windows({"stale_sources": 1})
    heavy = bwr.assess_broken_windows({
        "fake_rows_detected": 4, "closed_losses_without_moltbook": 4,
        "failed_smoke_checks": 2,
    })
    assert heavy["repair_debt_score"] >= light["repair_debt_score"]
    assert heavy["release_gate_impact"] == "BLOCK"


def test_report_is_advisory_only():
    out = bwr.assess_broken_windows({"fake_rows_detected": 1})
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["execution_gate"] == "LOCKED"


def test_build_report_reads_db(tmp_path):
    db = tmp_path / "bw.db"
    persistence.init_schema(db)
    rep = bwr.build_report(db)
    assert rep["report"] == "broken_windows_report"
    assert rep["db_available"] is True
    assert rep["release_gate_impact"] == "CLEAR"
    assert rep["advisory_status"] == "ADVISORY_ONLY"
