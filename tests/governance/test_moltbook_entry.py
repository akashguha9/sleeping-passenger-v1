"""Sections 14/15 — model reliability + Moltbook entry."""
from __future__ import annotations

import json


def test_mistral_reliability_downgraded(gov_result):
    by_model = {m.model: m for m in gov_result.model_reliability}
    mistral = by_model["mistral"]
    assert mistral.reliability == 0.55  # 1 - 0.25 - 0.20
    assert mistral.action_calls_downgraded is True
    assert by_model["claude"].reliability == 1.0


def test_wrong_run_date_block(gov_result):
    blocks = [b for b in gov_result.risk_blocks if b.block_type == "WRONG_RUN_DATE"]
    assert any(b.name == "mistral" for b in blocks)


def test_moltbook_fields(gov_result):
    mb = gov_result.moltbook_entry
    assert mb["date"] == "2026-06-05"
    assert mb["best_signal"] == ["RHM.DE", "AIR.PA", "SAP.DE"]
    assert set(mb["weakest_signal"]) >= {"GLD", "UNG", "FCG", "TLT", "TIP", "ZIM"}
    assert mb["concentration_warning"] == "COUNTRY_CONCENTRATION_WARNING"
    assert mb["existing_holding_review"] == [
        "ANET", "ASML", "CVX", "HDFCBANK.NS", "LMT", "MSFT", "RELIANCE.NS", "RTX", "TSM", "XOM"
    ]
    assert mb["no_new_risk_day"] == "YES"
    assert mb["final_regime"] == "EXISTING_POSITION_MANAGEMENT_ONLY"
    assert mb["source_health_status"] == "FAILED"
    assert mb["operator_lesson"].startswith("Do not reward a broken data day")


def test_moltbook_is_json_serializable(gov_result):
    json.dumps(gov_result.moltbook_entry)
