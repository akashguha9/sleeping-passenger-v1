"""Smoke test for the end-to-end calibration pipeline CLI."""
from __future__ import annotations

from scripts import run_calibration_pipeline as pipe


def test_pipeline_empty_db_is_no_data(tmp_path):
    rep = pipe.run_pipeline(tmp_path / "empty.db")
    assert rep["calibration"]["status"] == "NO_DATA"
    assert rep["calibration"]["should_drive_sizing"] is False
    assert rep["recommendation"]["applied"] is False
    assert rep["broker_api_called"] is False
    assert rep["advisory_status"] == "ADVISORY_ONLY"


def test_pipeline_backtest_mode_no_ohlcv_is_no_data(tmp_path):
    rep = pipe.run_pipeline(tmp_path / "empty.db", backtest=True)
    # No OHLCV in a fresh DB -> no backtest outcomes -> NO_DATA, never fabricated.
    assert rep["provenance"]["backtest_n"] == 0
    assert rep["calibration"]["status"] == "NO_DATA"
