"""Tests for resolved-outcome CSV import (provenance, idempotency, math)."""
from __future__ import annotations

import csv
import math
from pathlib import Path

from scripts import import_outcomes_csv as imp
from scripts import outcome_evidence as oe
from scripts import persistence


def _paper(**o):
    r = {"source_type": "PAPER_TRADE", "trade_id": "PT1", "signal_id": "EV1",
         "ticker": "RELIANCE", "opened_at": "2026-01-05", "closed_at": "2026-01-20",
         "direction": "LONG", "entry_price": "100", "exit_price": "110",
         "leverage": "1.0", "score_at_entry": "0.7"}
    r.update(o)
    return r


def test_valid_paper_trade_imports(tmp_path):
    db = tmp_path / "o.db"
    rep = imp.import_outcomes([_paper()], db_path=db)
    assert rep["accepted_count"] == 1
    assert rep["provenance"]["paper_n"] == 1
    assert rep["provenance"]["real_n"] == 0
    assert rep["rows_written"] == 1


def test_valid_real_manual_trade_imports(tmp_path):
    db = tmp_path / "o.db"
    rep = imp.import_outcomes([_paper(source_type="REAL_MANUAL_TRADE", trade_id="MT1")], db_path=db)
    assert rep["provenance"]["real_n"] == 1


def test_synthetic_rejected_in_runtime(tmp_path):
    db = tmp_path / "o.db"
    rep = imp.import_outcomes([_paper(source_type="SYNTHETIC_FIXTURE")], db_path=db, runtime_mode=True)
    assert rep["accepted_count"] == 0
    assert rep["rejected"][0]["reason"] == "synthetic_fixture_rejected_in_runtime"


def test_real_requires_id(tmp_path):
    db = tmp_path / "o.db"
    rep = imp.import_outcomes([_paper(source_type="REAL_MANUAL_TRADE", trade_id="", signal_id="")], db_path=db)
    assert rep["accepted_count"] == 0
    assert rep["rejected"][0]["reason"] == "missing_trade_or_signal_id"


def test_missing_exit_becomes_open_ineligible(tmp_path):
    db = tmp_path / "o.db"
    rep = imp.import_outcomes([_paper(exit_price="", realized_pnl="")], db_path=db)
    o = imp.build_outcome_from_row(_paper(exit_price="", realized_pnl=""))
    assert o.outcome_label == oe.OPEN
    assert o.is_calibration_eligible is False


def test_pnl_based_return_exact():
    o = imp.build_outcome_from_row(_paper(entry_price="", exit_price="",
                                          realized_pnl="1500", capital_at_risk="10000"))
    assert math.isclose(o.realized_return, 0.15)


def test_price_based_return_exact():
    o = imp.build_outcome_from_row(_paper(entry_price="100", exit_price="110"))
    assert math.isclose(o.realized_return, 0.10)


def test_closed_before_opened_rejected(tmp_path):
    rep = imp.import_outcomes([_paper(opened_at="2026-02-01", closed_at="2026-01-01")], db_path=tmp_path / "o.db")
    assert rep["rejected"][0]["reason"] == "closed_before_opened"


def test_duplicate_import_idempotent(tmp_path):
    db = tmp_path / "o.db"
    imp.import_outcomes([_paper()], db_path=db)
    rep2 = imp.import_outcomes([_paper()], db_path=db)
    assert rep2["rows_written"] == 0
    assert len(persistence.get_imported_outcome_rows(db)) == 1


def test_rebuild_from_db_recomputes_evidence(tmp_path):
    db = tmp_path / "o.db"
    imp.import_outcomes([_paper(), _paper(source_type="REAL_MANUAL_TRADE", trade_id="MT9", ticker="AAPL")], db_path=db)
    outs = imp.rebuild_imported_outcomes(db)
    prov = oe.provenance_counts(outs)
    assert prov["paper_n"] == 1 and prov["real_n"] == 1
    assert all(o.advisory_only for o in outs)


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "o.db"
    rep = imp.import_outcomes([_paper()], db_path=db, dry_run=True)
    assert rep["accepted_count"] == 1
    assert rep["rows_written"] == 0
    assert persistence.get_imported_outcome_rows(db) == []


def test_template_file_parses():
    rows = list(csv.DictReader(Path("templates/outcome_import_template.csv").open(encoding="utf-8-sig")))
    assert len(rows) >= 3
    rep = imp.import_outcomes(rows, db_path=Path("/tmp/never_written.db"), dry_run=True)
    assert rep["rejected_count"] == 0  # template is valid


def test_no_execution_language_in_report(tmp_path):
    rep = imp.import_outcomes([_paper()], db_path=tmp_path / "o.db")
    assert rep["broker_api_called"] is False
    blob = str(rep).lower()
    for w in ("place_order", "execute_trade", "auto_buy", "auto_sell"):
        assert w not in blob
