"""Section 17 — full 2026-06-05 five-model synthesis regression.

This pins the EXISTING_POSITION_MANAGEMENT_ONLY behaviour that the original
synthesis failure violated. If any of these assertions ever flip, the daily
governance layer has regressed into rewarding a broken data day with risk.
"""
from __future__ import annotations

import json


def test_top_level_verdict(gov_result):
    assert gov_result.source_health.status == "FAILED"
    assert gov_result.no_new_risk_day == "YES"
    assert gov_result.new_risk_permission is False
    assert gov_result.execution_gate_status == "LOCKED"
    assert gov_result.final_regime == "EXISTING_POSITION_MANAGEMENT_ONLY"
    assert gov_result.top_manual_add_consideration == []
    assert gov_result.best_watch == "RHM.DE"


def test_quarantine_and_reduce_exit(gov_result):
    assert set(gov_result.names_to_quarantine) >= {"GLD", "UNG", "FCG", "TLT", "TIP", "ZIM"}
    assert "HDFCBANK.NS" in gov_result.strongest_reduce_exit_review
    assert "RELIANCE.NS" in gov_result.strongest_reduce_exit_review


def test_candidate_classifications(gov_result):
    board = {a.ticker: a.classification for a in gov_result.candidate_quality_board}
    assert board["RHM.DE"] == "WATCH"
    assert board["AIR.PA"] == "WATCH"
    assert board["SAP.DE"] == "WATCH"
    assert board["NVDA"] == "WAIT"
    assert board["NOC"] == "WAIT"
    assert board["TSLA"] in ("AVOID TODAY", "RISK BLOCK")
    assert board["CSCO"] == "AVOID TODAY"


def test_csco_prompt_only_block(gov_result):
    blocks = {b.ticker: b for b in gov_result.risk_blocks if b.block_type == "PROMPT_ONLY_NOT_MODEL_BACKED"}
    assert "CSCO" in blocks


def test_final_board(gov_result):
    fb = gov_result.final_daily_decision_board
    assert fb["final_brutal_verdict"] == "WAIT / CLEAN THE BOOK FIRST"
    assert fb["biggest_risk_block"] == "Missing live prices + 4x India exposure"
    assert fb["execution_gate_status"] == "LOCKED"
    assert fb["new_risk_permission"] is False
    assert fb["broker_execution_allowed"] is False
    assert fb["human_execution_required"] is True


def test_result_is_json_serializable(gov_result):
    blob = json.dumps(gov_result.to_dict())
    assert "EXISTING_POSITION_MANAGEMENT_ONLY" in blob
