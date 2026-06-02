"""Tests for scripts/model_version_performance.py — per-cohort, no overclaiming."""
from __future__ import annotations

from pathlib import Path

from scripts.google_sheet_schema import load_trade_log_csv
from scripts.model_version_performance import build_model_version_report

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trade_log_sample.csv"


def test_report_has_dated_cohorts():
    rows = load_trade_log_csv(FIXTURE).rows
    report = build_model_version_report(rows)
    perf = report["model_version_performance"]
    assert "v2026_05_early" in perf
    assert "v2026_06_global_watchlist" in perf


def test_small_cohorts_flagged_immature_not_conclusive():
    rows = load_trade_log_csv(FIXTURE).rows
    report = build_model_version_report(rows)
    # The fixture is tiny -> every cohort N < 30 -> immature note present.
    assert "immature" in report["interpretation_note"].lower()
    for cohort in report["model_version_performance"].values():
        assert cohort["confidence"] in {"LOW", "MEDIUM", "HIGH"}
        if cohort["n"] < 30:
            assert cohort["maturity_note"] == "promising but immature"


def test_report_is_advisory():
    rows = load_trade_log_csv(FIXTURE).rows
    report = build_model_version_report(rows)
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["human_execution_required"] is True
