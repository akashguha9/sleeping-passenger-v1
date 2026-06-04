"""Sections 12/13 — phantom quarantine, risk blocks, least-bad override."""
from __future__ import annotations


def test_quarantine_names(gov_result):
    assert set(gov_result.names_to_quarantine) >= {"GLD", "UNG", "FCG", "TLT", "TIP", "ZIM"}


def test_quarantine_blocks_cannot_receive_review(gov_result):
    for block in gov_result.phantom_quarantine_board:
        assert block.quarantine is True
        assert block.can_receive_holding_review is False
        assert block.can_appear_on_manual_board is False


def test_closed_or_sold_block_type(gov_result):
    by_ticker = {b.ticker: b for b in gov_result.phantom_quarantine_board}
    assert by_ticker["GLD"].block_type == "CLOSED_OR_SOLD_POSITION"
    for t in ("UNG", "TIP", "TLT", "FCG"):
        assert by_ticker[t].block_type == "NOT_OWNED_DO_NOT_MANAGE"


def test_phantom_management_attempt_block(gov_result):
    attempts = [b for b in gov_result.risk_blocks if b.block_type == "PHANTOM_POSITION_MANAGEMENT_ATTEMPT"]
    assert attempts
    for b in attempts:
        assert b.severity == "HIGH"
        assert b.quarantine is True
        assert b.reason == "Ticker is not in verified current holdings H"


def test_prompt_only_block(gov_result):
    prompt = [b for b in gov_result.risk_blocks if b.block_type == "PROMPT_ONLY_NOT_MODEL_BACKED"]
    assert any(b.ticker == "CSCO" for b in prompt)


def test_least_bad_override_list(gov_result):
    names = [x["ticker"] for x in gov_result.least_bad_override_list]
    assert names == ["RHM.DE", "AIR.PA", "SAP.DE"]
    assert len(names) <= 3
    for entry in gov_result.least_bad_override_list:
        assert entry["manual_research_only"] is True
        assert entry["not_automatic_trade"] is True
        assert "must_verify" in entry
        # current holdings must never be in the override list
        assert entry["ticker"] not in gov_result.portfolio_truth.current_holdings_H
