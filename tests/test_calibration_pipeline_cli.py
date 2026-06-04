"""Tests for the end-to-end calibration pipeline CLI (real-evidence flags)."""
from __future__ import annotations

import csv
from pathlib import Path

from scripts import run_calibration_pipeline as pipe
from scripts import persistence


REPORT_FIELDS = (
    "real_n", "paper_n", "backtest_n", "synthetic_n", "eligible_n",
    "calibration_status", "ECE", "Brier", "MCE", "log_loss", "ECE_CI_95",
    "recalibration_method", "raw_brier", "recalibrated_brier", "oos_improved",
    "signal_quality_score", "readiness_score", "allowed_mode", "can_drive_sizing",
    "advisory_only", "human_execution_required", "broker_api_called",
)


def test_empty_db_is_no_data(tmp_path):
    rep = pipe.run_pipeline(tmp_path / "empty.db")
    assert rep["calibration_status"] == "NO_DATA"
    assert rep["can_drive_sizing"] is False
    assert rep["broker_api_called"] is False
    for f in REPORT_FIELDS:
        assert f in rep, f"missing report field {f}"


def test_backtest_mode_no_ohlcv_is_no_data(tmp_path):
    rep = pipe.run_pipeline(tmp_path / "empty.db", backtest=True)
    assert rep["backtest_n"] == 0
    assert rep["calibration_status"] == "NO_DATA"


def test_json_contract_stable(tmp_path):
    rep = pipe.run_pipeline(tmp_path / "e.db")
    assert set(REPORT_FIELDS).issubset(rep.keys())


def _outcomes_csv(path, rows):
    cols = ["source_type", "trade_id", "signal_id", "ticker", "opened_at", "closed_at",
            "direction", "entry_price", "exit_price", "realized_pnl", "capital_at_risk",
            "leverage", "score_at_entry", "archetype", "signal_class", "notes"]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def test_import_paper_outcomes_raises_paper_n(tmp_path):
    db = tmp_path / "p.db"
    csvp = tmp_path / "out.csv"
    rows = [{"source_type": "PAPER_TRADE", "trade_id": f"PT{i}", "ticker": "RELIANCE",
             "opened_at": "2026-01-05", "closed_at": "2026-01-20", "direction": "LONG",
             "entry_price": 100, "exit_price": 100 + (i % 5), "leverage": 1.0,
             "score_at_entry": 0.5 + (i % 4) * 0.1} for i in range(25)]
    _outcomes_csv(csvp, rows)
    rep = pipe.run_pipeline(db, import_outcomes=csvp)
    assert rep["paper_n"] == 25
    assert rep["real_n"] == 0


def test_import_real_outcomes_raises_real_n(tmp_path):
    db = tmp_path / "r.db"
    csvp = tmp_path / "out.csv"
    rows = [{"source_type": "REAL_MANUAL_TRADE", "trade_id": f"MT{i}", "ticker": "AAPL",
             "opened_at": "2026-02-01", "closed_at": "2026-02-15", "direction": "LONG",
             "entry_price": 100, "exit_price": 110, "leverage": 1.0,
             "score_at_entry": 0.7} for i in range(3)]
    _outcomes_csv(csvp, rows)
    rep = pipe.run_pipeline(db, import_outcomes=csvp)
    assert rep["real_n"] == 3


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "d.db"
    csvp = tmp_path / "out.csv"
    _outcomes_csv(csvp, [{"source_type": "PAPER_TRADE", "trade_id": "PT1", "ticker": "X",
                          "opened_at": "2026-01-01", "closed_at": "2026-01-10", "direction": "LONG",
                          "entry_price": 100, "exit_price": 105, "leverage": 1.0, "score_at_entry": 0.6}])
    rep = pipe.run_pipeline(db, import_outcomes=csvp, dry_run=True)
    assert rep["dry_run"] is True
    assert persistence.get_imported_outcome_rows(db) == []


def test_paper_outcomes_do_not_lift_real_readiness(tmp_path):
    db = tmp_path / "b.db"
    csvp = tmp_path / "out.csv"
    rows = []
    for i in range(60):
        win = i % 10 < 9  # 90% win at score 0.9 -> well calibrated paper data
        rows.append({"source_type": "PAPER_TRADE", "trade_id": f"PT{i}", "ticker": "RELIANCE",
                     "opened_at": "2026-01-05", "closed_at": "2026-01-20", "direction": "LONG",
                     "entry_price": 100, "exit_price": 110 if win else 90, "leverage": 1.0,
                     "score_at_entry": 0.9})
    _outcomes_csv(csvp, rows)
    rep = pipe.run_pipeline(db, import_outcomes=csvp)
    assert rep["paper_n"] == 60
    assert rep["real_n"] == 0
    assert rep["readiness_score"] <= 7.0
    assert rep["can_drive_sizing"] is False


def test_no_broker_language_in_report(tmp_path):
    rep = pipe.run_pipeline(tmp_path / "e.db")
    blob = str(rep).lower()
    for w in ("place_order", "execute_trade", "auto_buy", "auto_sell"):
        assert w not in blob
