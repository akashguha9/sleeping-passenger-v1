"""Integration: discovery survives an execution block (the core sprint fix).

These run the real daily synthesis pipeline against the committed payload (whose
price layer is currently unavailable, H/C price coverage = 0.0) and prove that
discovery output is NOT suppressed when execution is blocked.
"""
from __future__ import annotations

from scripts.daily_synthesis_pipeline import (
    render_portfolio_truth_context,
    run_daily_synthesis,
)


def test_discovery_survives_execution_block():
    result = run_daily_synthesis()
    mode = result["mode_state"]

    # Execution lane is blocked (weak price layer).
    assert mode["execution_allowed"] is False
    assert mode["new_risk_allowed"] is False
    assert mode["buy_board_allowed"] is False

    # Discovery lane is still alive.
    assert mode["discovery_allowed"] is True
    assert mode["candidate_board_allowed"] is True
    assert len(result["discovery_board"]) > 0

    # No executable buys are surfaced while blocked.
    assert result["execution_board"] == []

    # No discovery-board candidate is classified as an executable buy.
    classes = {row["classification"] for row in result["discovery_board"]}
    assert "BUY" not in classes
    assert "PROBE_BUY" not in classes


def test_price_coverage_blocks_execution_not_discovery():
    result = run_daily_synthesis()
    cov = result["coverage"]
    assert cov["holdings_price_coverage"] < 0.80
    assert cov["candidate_price_coverage"] < 0.80
    assert "H_PRICE_COVERAGE_BELOW_0_80" in result["mode_state"]["blockers"]
    # Discovery board still populated despite the coverage failure.
    assert len(result["discovery_board"]) > 0


def test_phantom_rows_quarantined_not_open_risk():
    result = run_daily_synthesis()
    quarantine = {row["ticker"] for row in result["quarantine_board"]}
    verified = set(result["portfolio_truth_gate"]["verified_open_holdings"])
    # Known phantom / closed names appear in quarantine, never in verified open.
    for ticker in ("GLD", "UNG", "TIP", "TLT", "FCG"):
        assert ticker not in verified
    assert "GLD" in quarantine


def test_context_block_reports_mode_summary_and_message():
    result = run_daily_synthesis()
    text = render_portfolio_truth_context(result)
    assert "MODE SUMMARY" in text
    assert "Discovery is active, but execution is blocked." in text
    assert "discovery_allowed = True" in text
    assert "execution_allowed = False" in text
