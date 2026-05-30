"""Tests — paper-outcome CSV / sheet importer (Workstream A).

Proves the alias normalization, that missing prices are never invented (only
flagged), that dry-run writes nothing, and that --apply is fail-closed behind
the operator permission guard.  No fabricated outcomes; real-money sizing
PROHIBITED.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.paper_outcome_importer import (
    apply_import,
    build_import_report,
    main,
    normalize_row,
)
from scripts.paper_outcome_intake import VALID_FOR_CALIBRATION


def _sheet_row(**overrides):
    # UPPER_SNAKE + spaced + percent headers, exactly as a human exports them.
    row = {
        "TRADE_ID": "T-1",
        "SIGNAL_ID": "S-1",
        "TICKER": "AAPL",
        "ENTRY_TIMESTAMP_UTC": "2026-05-01T00:00:00Z",
        "EXIT_TIMESTAMP_UTC": "2026-05-06T00:00:00Z",
        "BUY PRICE": "100.0",
        "SELL PRICE": "110.0",
        "EXIT_REASON": "target",
        "REALIZED_RETURN_%": "10.0",
        "REALIZED_R_MULTIPLE": "2.0",
        "OUTCOME_Y_0_OR_1": "1",
        "PROOF_STATUS": "PAPER_VERIFIED",
    }
    row.update(overrides)
    return row


# --- 1: importer parses sheet aliases ---------------------------------------
def test_importer_parses_sheet_aliases():
    rec = normalize_row(_sheet_row())
    assert rec["trade_id"] == "T-1"
    assert rec["signal_id"] == "S-1"
    assert rec["ticker"] == "AAPL"
    assert rec["entry_price"] == "100.0"
    assert rec["exit_price"] == "110.0"
    assert rec["realized_return_pct"] == "10.0"
    assert rec["realized_r_multiple"] == "2.0"
    assert rec["outcome_y_0_or_1"] == "1"
    assert rec["proof_status"] == "PAPER_VERIFIED"

    report = build_import_report([_sheet_row()])
    assert report["rows_seen"] == 1
    assert report["valid_for_calibration"] == 1
    assert report["intake_report"]["normalized_records"][0][
        "intake_classification"
    ] == VALID_FOR_CALIBRATION


# --- 2: importer rejects missing prices (never invents them) ----------------
def test_importer_rejects_missing_prices():
    row = _sheet_row()
    del row["BUY PRICE"]  # operator forgot the entry price
    report = build_import_report([row])
    assert report["valid_for_calibration"] == 0
    assert "entry_price" in report["missing_required_fields"]
    # The normalized record carries no invented price.
    nr = report["intake_report"]["normalized_records"][0]
    assert nr["entry_price"] is None
    assert nr["intake_classification"] != VALID_FOR_CALIBRATION


# --- 2b: duplicate trade ids are surfaced, not double-counted ----------------
def test_importer_dedupes_trade_ids():
    report = build_import_report([_sheet_row(), _sheet_row()])
    assert report["rows_seen"] == 2
    assert report["duplicate_trade_ids"] == ["T-1"]
    # Only the first unique row reaches intake.
    assert report["intake_report"]["records_total"] == 1


# --- 3: importer dry-run writes nothing -------------------------------------
def test_importer_dry_run_writes_nothing(tmp_path, monkeypatch):
    import scripts.paper_outcome_intake as intake

    intake_dir = tmp_path / "intake_store"
    monkeypatch.setattr(intake, "_DEFAULT_INTAKE_DIR", intake_dir, raising=False)

    src = tmp_path / "outcomes.json"
    src.write_text(json.dumps([_sheet_row()]), encoding="utf-8")

    rc = main(["--input", str(src)])  # no --apply → dry-run default
    assert rc == 0
    assert not intake_dir.exists()


# --- 4: importer apply requires the operator guard --------------------------
def test_importer_apply_requires_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_OPERATOR_GUARD_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("MVP_OPERATOR_RECEIPT_DIR", str(tmp_path / "receipts"))

    report = build_import_report([_sheet_row()], applied=True)
    out_path = tmp_path / "imported.json"

    # VIEWER may not perform an AUDIT_ONLY_WRITE → fail closed, nothing written.
    with pytest.raises(PermissionError):
        apply_import(report, output_path=out_path, operator_role="VIEWER")
    assert not out_path.exists()

    # OPERATOR is allowed → the audit-only normalized artifact is written.
    res = apply_import(report, output_path=out_path, operator_role="OPERATOR")
    assert res["written"] is True
    assert res["canonical_store_written"] is False
    assert out_path.exists()


# --- safety stamp ------------------------------------------------------------
def test_importer_real_money_prohibited():
    report = build_import_report([_sheet_row()])
    assert report["real_money_sizing_impact"] == "PROHIBITED"
    assert report["real_money_weight_allowed"] is False
    assert report["operator_execution_required"] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
