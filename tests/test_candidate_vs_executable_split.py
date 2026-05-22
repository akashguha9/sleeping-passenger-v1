"""Layer 3 — candidate vs executable split tests."""
from __future__ import annotations

from pathlib import Path

from daily_payload_factory import holding, write_daily_payload

from scripts.candidate_executable_split import (
    build_candidate_executable_split,
    classify_candidate,
    compute_eqs,
)
from scripts.fresh_market_discovery import build_fresh_market_discovery
from scripts.portfolio_truth_gate import build_portfolio_truth_gate


def test_high_cqs_missing_source_health_is_not_executable() -> None:
    # Strong candidate but no live source health -> NOT-EXECUTABLE, not "None".
    eqs = compute_eqs({
        "data_quality": 0.5,
        "invalidation_defined": 1,
        "position_sizing_defined": 1,
        "source_health": 0.0,
        "liquidity_quality": 0.5,
        "human_review_ready": 1,
    })
    verdict = classify_candidate(
        cqs=0.82,
        eqs=eqs["eqs"],
        eqs_components=eqs["components"],
        portfolio_truth="NOT_A_HOLDING",
        forbidden_for_execution=False,
        source_health=0.0,
    )
    assert verdict["classification"] == "BUY-CANDIDATE / NOT-EXECUTABLE"
    assert verdict["executable"] is False
    assert "not executable because" in verdict["reason"].lower()


def test_strong_clean_candidate_is_executable() -> None:
    eqs = compute_eqs({
        "data_quality": 1.0,
        "invalidation_defined": 1,
        "position_sizing_defined": 1,
        "source_health": 1.0,
        "portfolio_truth_clean": 1,
        "liquidity_quality": 1.0,
        "human_review_ready": 1,
    })
    verdict = classify_candidate(
        cqs=0.85,
        eqs=eqs["eqs"],
        eqs_components=eqs["components"],
        portfolio_truth="NOT_A_HOLDING",
        forbidden_for_execution=False,
        source_health=1.0,
    )
    assert verdict["classification"] == "EXECUTABLE-PAPER-BUY"
    assert verdict["executable"] is True


def test_verified_holding_is_exit_review_only() -> None:
    eqs = compute_eqs({"data_quality": 1.0, "source_health": 1.0})
    verdict = classify_candidate(
        cqs=0.9, eqs=eqs["eqs"], eqs_components=eqs["components"],
        portfolio_truth="VERIFIED_OPEN_HOLDING", forbidden_for_execution=False,
        source_health=1.0,
    )
    assert verdict["classification"] == "SELL / EXIT REVIEW"
    assert verdict["executable"] is False


def test_rtx_candidate_not_executable_end_to_end(tmp_path: Path) -> None:
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        verified=[holding("ANET")],
        movers=[{"ticker": "RTX", "freshness": "UNVERIFIED"}],
        source_health="MISSING_OR_UNVERIFIED",
    )
    gate = build_portfolio_truth_gate(payload_dir=payload_dir)
    # RTX scores strongly on quality, but source health is missing.
    discovery = build_fresh_market_discovery(
        payload_dir=payload_dir, truth_gate=gate,
        features={"RTX": {
            "signal_strength": 0.9, "narrative_velocity": 0.8, "price_momentum": 0.8,
            "filing_materiality": 0.7, "liquidity_quality": 0.9, "freshness": 0.9,
            "data_quality": 0.8,
        }},
    )
    split = build_candidate_executable_split(
        discovery, gate,
        eqs_features={"RTX": {
            "data_quality": 0.8, "invalidation_defined": 1, "position_sizing_defined": 1,
            "source_health": 0.0, "liquidity_quality": 0.9, "human_review_ready": 1,
        }},
    )
    rtx = next(r for r in split["classified"] if r["ticker"] == "RTX")
    assert rtx["classification"] == "BUY-CANDIDATE / NOT-EXECUTABLE"
    assert split["has_executable_buys"] is False
    # The name is preserved as a candidate, not dropped.
    assert any(r["ticker"] == "RTX" for r in split["buy_candidate_not_executable"])


def test_closed_sold_can_be_watchlist_not_executable(tmp_path: Path) -> None:
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        verified=[],
        sold=["GLD"],
        closed=[{"ticker": "GLD", "status": "CLOSED"}],
        closed_or_sold=["GLD"],
        movers=[{"ticker": "GLD", "freshness": "UNVERIFIED"}],
    )
    gate = build_portfolio_truth_gate(payload_dir=payload_dir)
    discovery = build_fresh_market_discovery(
        payload_dir=payload_dir, truth_gate=gate,
        features={"GLD": {
            "signal_strength": 0.9, "narrative_velocity": 0.8, "price_momentum": 0.7,
            "filing_materiality": 0.5, "liquidity_quality": 0.9, "freshness": 0.8,
            "data_quality": 0.8,
        }},
    )
    split = build_candidate_executable_split(discovery, gate)
    gld = next(r for r in split["classified"] if r["ticker"] == "GLD")
    assert gld["classification"] in {"WATCHLIST", "AVOID"}
    assert gld["executable"] is False
