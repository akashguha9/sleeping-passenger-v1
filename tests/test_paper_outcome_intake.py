"""Tests — paper-outcome intake (deterministic, pure + guarded apply).

Kanté Ceiling Push II, Workstream A.  Proves the validity maths, the three
classification bands, that dry-run writes nothing, that --apply is fail-closed
behind the operator permission guard, and that real-money sizing is
unconditionally PROHIBITED.  No fabricated outcomes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.paper_outcome_intake import (
    NEEDS_OPERATOR_REVIEW,
    REJECTED_INSUFFICIENT_PROOF,
    VALID_FOR_CALIBRATION,
    apply_normalized_write,
    build_intake_report,
    main,
    validate_outcome,
)


def _valid_record(**overrides):
    rec = {
        "trade_id": "T-1",
        "signal_id": "S-1",
        "ticker": "AAPL",
        "entry_timestamp_utc": "2026-05-01T00:00:00Z",
        "exit_timestamp_utc": "2026-05-06T00:00:00Z",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "exit_reason": "target",
        "holding_days": 5,
        "realized_return_pct": 10.0,
        "realized_r_multiple": 2.0,
        "outcome_y_0_or_1": 1,
        "proof_status": "PAPER_VERIFIED",
        "source": "MANUAL_PAPER",
    }
    rec.update(overrides)
    return rec


# --- 1 ----------------------------------------------------------------------
def test_valid_paper_outcome_passes():
    r = validate_outcome(_valid_record())
    assert r["intake_classification"] == VALID_FOR_CALIBRATION
    assert r["outcome_quality_score"] == pytest.approx(1.0)
    assert r["return_error"] == pytest.approx(0.0)
    assert r["realized_return_pct_expected"] == pytest.approx(10.0)
    assert r["outcome_y_0_or_1_expected"] == 1
    assert r["holding_days_expected"] == 5


# --- 2 ----------------------------------------------------------------------
def test_wrong_return_math_requires_review():
    r = validate_outcome(_valid_record(realized_return_pct=50.0))
    assert r["valid_price_math"] is False
    assert r["intake_classification"] == NEEDS_OPERATOR_REVIEW
    assert r["outcome_quality_score"] == pytest.approx(0.75)


# --- 3 ----------------------------------------------------------------------
def test_missing_signal_id_requires_review():
    r = validate_outcome(_valid_record(signal_id=""))
    assert r["has_required_ids"] is False
    assert "signal_id" in r["missing_fields"]
    assert r["intake_classification"] == NEEDS_OPERATOR_REVIEW


# --- 4 ----------------------------------------------------------------------
def test_open_trade_rejected():
    # An open trade has no exit price + no exit timestamp + no proof.
    rec = _valid_record(
        exit_price="",
        exit_timestamp_utc="",
        realized_return_pct="",
        outcome_y_0_or_1="",
        proof_status="",
    )
    r = validate_outcome(rec)
    assert r["valid_price_math"] is False
    assert r["valid_time_order"] is False
    assert r["intake_classification"] == REJECTED_INSUFFICIENT_PROOF


# --- 5 ----------------------------------------------------------------------
def test_negative_return_label_mismatch_review():
    # Loss (exit < entry) but operator marked outcome_y=1.
    r = validate_outcome(
        _valid_record(exit_price=90.0, realized_return_pct=-10.0, outcome_y_0_or_1=1)
    )
    assert r["valid_price_math"] is True
    assert r["outcome_y_0_or_1_expected"] == 0
    assert r["valid_outcome_label"] is False
    assert r["intake_classification"] == NEEDS_OPERATOR_REVIEW
    assert r["outcome_quality_score"] == pytest.approx(0.85)


# --- 6 ----------------------------------------------------------------------
def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    import scripts.paper_outcome_intake as intake

    intake_dir = tmp_path / "intake_store"
    monkeypatch.setattr(intake, "_DEFAULT_INTAKE_DIR", intake_dir, raising=False)

    csv_path = tmp_path / "outcomes.json"
    csv_path.write_text(json.dumps([_valid_record()]), encoding="utf-8")

    rc = main(["--input", str(csv_path)])  # no --apply → dry-run default
    assert rc == 0
    # Nothing written anywhere.
    assert not intake_dir.exists()


# --- 7 ----------------------------------------------------------------------
def test_apply_requires_guard(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MVP_OPERATOR_GUARD_AUDIT_PATH", str(tmp_path / "audit.jsonl")
    )
    monkeypatch.setenv("MVP_OPERATOR_RECEIPT_DIR", str(tmp_path / "receipts"))

    report = build_intake_report([_valid_record()])
    out_path = tmp_path / "normalized.json"

    # VIEWER may not perform an AUDIT_ONLY_WRITE → fail closed, nothing written.
    with pytest.raises(PermissionError):
        apply_normalized_write(report, output_path=out_path, operator_role="VIEWER")
    assert not out_path.exists()

    # OPERATOR is allowed → the audit-only normalized artifact is written.
    res = apply_normalized_write(
        report, output_path=out_path, operator_role="OPERATOR"
    )
    assert res["written"] is True
    assert res["canonical_store_written"] is False
    assert out_path.exists()


# --- 8 ----------------------------------------------------------------------
def test_real_money_sizing_prohibited():
    r = validate_outcome(_valid_record())
    assert r["real_money_sizing_impact"] == "PROHIBITED"
    assert r["real_money_weight_allowed"] is False
    assert r["execution_gate"] == "LOCKED"
    assert r["broker_api_called"] is False
    assert r["ai_execution_count"] == 0

    report = build_intake_report([_valid_record(), _valid_record(trade_id="T-2")])
    assert report["real_money_sizing_impact"] == "PROHIBITED"
    assert report["real_money_weight_allowed"] is False
    assert report["operator_execution_required"] is True
    assert report["execution_gate"] == "LOCKED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
