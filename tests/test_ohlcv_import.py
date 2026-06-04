"""Tests for OHLCV import contract + CSV importer + ohlcv_bars store."""
from __future__ import annotations

import csv
from pathlib import Path

from scripts import ohlcv_import_contract as contract
from scripts import import_ohlcv_csv as imp
from scripts import persistence


def _row(**over):
    r = {
        "ticker": "AAPL", "date": "2026-01-05", "open": 100.0, "high": 105.0,
        "low": 99.0, "close": 104.0, "volume": 1000, "source": "YFINANCE_IMPORTED",
    }
    r.update(over)
    return r


# --- contract validation ----------------------------------------------------

def test_valid_row_accepted():
    ok, reason, norm = contract.validate_row(_row())
    assert ok and reason is None
    assert norm["ticker"] == "AAPL" and norm["close"] == 104.0


def test_high_below_body_rejected():
    ok, reason, _ = contract.validate_row(_row(high=103.0))  # high < close 104
    assert not ok and reason == "high_below_body"


def test_low_above_body_rejected():
    ok, reason, _ = contract.validate_row(_row(low=101.0))  # low > open/close min 100? open100 close104 -> min 100, low101>100
    assert not ok and reason == "low_above_body"


def test_non_positive_price_rejected():
    ok, reason, _ = contract.validate_row(_row(low=-1.0))
    assert not ok and reason in {"non_positive_price", "low_above_body"}


def test_missing_source_rejected():
    ok, reason, _ = contract.validate_row(_row(source=""))
    assert not ok and reason == "missing_source"


def test_unparseable_date_rejected():
    ok, reason, _ = contract.validate_row(_row(date="not-a-date"))
    assert not ok and reason == "unparseable_date"


def test_dd_mm_yyyy_date_normalised():
    ok, _, norm = contract.validate_row(_row(date="05-01-2026"))
    assert ok and norm["date"] == "2026-01-05"


def test_synthetic_rejected_in_runtime():
    ok, reason, _ = contract.validate_row(_row(source="SYNTHETIC_FIXTURE"), runtime_mode=True)
    assert not ok and reason == "synthetic_fixture_rejected_in_runtime"


def test_synthetic_allowed_in_test_mode():
    ok, reason, norm = contract.validate_row(_row(source="SYNTHETIC_FIXTURE"), runtime_mode=False)
    assert ok and norm is not None


# --- importer + store -------------------------------------------------------

def _write_csv(path: Path, rows):
    cols = ["ticker", "date", "open", "high", "low", "close", "volume", "source"]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def test_csv_import_writes_bars(tmp_path):
    db = tmp_path / "ohlcv.db"
    csvp = tmp_path / "bars.csv"
    _write_csv(csvp, [_row(date="2026-01-05"), _row(date="2026-01-06", close=106, high=107)])
    rep = imp.import_ohlcv_file(csvp, db_path=db)
    assert rep["accepted_count"] == 2
    assert rep["rows_written"] == 2
    assert persistence.count_ohlcv_bars(db) == 2
    assert rep["broker_api_called"] is False


def test_csv_import_is_idempotent(tmp_path):
    db = tmp_path / "ohlcv.db"
    csvp = tmp_path / "bars.csv"
    _write_csv(csvp, [_row(date="2026-01-05")])
    imp.import_ohlcv_file(csvp, db_path=db)
    rep2 = imp.import_ohlcv_file(csvp, db_path=db)  # re-import same file
    assert rep2["rows_written"] == 0  # nothing new
    assert persistence.count_ohlcv_bars(db) == 1


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "ohlcv.db"
    csvp = tmp_path / "bars.csv"
    _write_csv(csvp, [_row()])
    rep = imp.import_ohlcv_file(csvp, db_path=db, dry_run=True)
    assert rep["accepted_count"] == 1
    assert rep["rows_written"] == 0
    assert persistence.count_ohlcv_bars(db) == 0


def test_synthetic_rejected_in_runtime_import(tmp_path):
    db = tmp_path / "ohlcv.db"
    csvp = tmp_path / "bars.csv"
    _write_csv(csvp, [_row(source="SYNTHETIC_FIXTURE")])
    rep = imp.import_ohlcv_file(csvp, db_path=db, runtime_mode=True)
    assert rep["accepted_count"] == 0
    assert rep["rejected_count"] == 1
    assert persistence.count_ohlcv_bars(db) == 0


def test_imported_bar_carries_advisory_stamps(tmp_path):
    db = tmp_path / "ohlcv.db"
    persistence.insert_ohlcv_bars([contract.validate_row(_row())[2]], db_path=db)
    bars = persistence.get_ohlcv_bars("AAPL", db_path=db)
    assert bars[0]["advisory_only"] == "ADVISORY_ONLY"
    assert bars[0]["broker_api_called"] == 0
    assert bars[0]["human_execution_required"] == 1
