"""Entry-quality gate is wired into candidate-vs-executable split."""
from __future__ import annotations

from pathlib import Path

from daily_payload_factory import write_daily_payload

from scripts.candidate_executable_split import (
    build_candidate_executable_split,
    classify_candidate,
    compute_eqs,
)
from scripts.fresh_market_discovery import build_fresh_market_discovery
from scripts.portfolio_truth_gate import build_portfolio_truth_gate


def _strong_eqs() -> dict:
    return compute_eqs({
        "data_quality": 1.0, "invalidation_defined": 1, "position_sizing_defined": 1,
        "source_health": 1.0, "portfolio_truth_clean": 1, "liquidity_quality": 1.0,
        "human_review_ready": 1,
    })


def test_strong_candidate_with_entry_quality_pass_is_executable() -> None:
    eqs = _strong_eqs()
    verdict = classify_candidate(
        cqs=0.85, eqs=eqs["eqs"], eqs_components=eqs["components"],
        portfolio_truth="NOT_A_HOLDING", forbidden_for_execution=False,
        source_health=1.0, entry_quality_pass=True, entry_quality_score=0.82,
    )
    assert verdict["classification"] == "EXECUTABLE-PAPER-BUY"
    assert verdict["executable"] is True


def test_strong_candidate_with_entry_quality_fail_is_not_executable() -> None:
    eqs = _strong_eqs()
    verdict = classify_candidate(
        cqs=0.85, eqs=eqs["eqs"], eqs_components=eqs["components"],
        portfolio_truth="NOT_A_HOLDING", forbidden_for_execution=False,
        source_health=1.0,
        entry_quality_pass=False, entry_quality_score=0.20,
        entry_quality_reasons=["trend_50: above=False"],
    )
    assert verdict["classification"] == "BUY-CANDIDATE / NOT-EXECUTABLE"
    assert verdict["executable"] is False
    assert "entry-quality gate failed" in verdict["reason"]
    assert "trend_50" in verdict["reason"]


def test_omitted_entry_quality_keeps_legacy_behaviour() -> None:
    # entry_quality_pass omitted (None) — previous behaviour preserved.
    eqs = _strong_eqs()
    verdict = classify_candidate(
        cqs=0.85, eqs=eqs["eqs"], eqs_components=eqs["components"],
        portfolio_truth="NOT_A_HOLDING", forbidden_for_execution=False,
        source_health=1.0,
    )
    assert verdict["classification"] == "EXECUTABLE-PAPER-BUY"


def test_entry_quality_by_ticker_flows_through_builder(tmp_path: Path) -> None:
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        verified=[], movers=[{"ticker": "AAPL", "freshness": "FRESH_TODAY"}],
        source_health="LIVE_OK",
    )
    gate = build_portfolio_truth_gate(payload_dir=payload_dir)
    discovery = build_fresh_market_discovery(
        payload_dir=payload_dir, truth_gate=gate,
        features={"AAPL": {
            "signal_strength": 0.9, "narrative_velocity": 0.9, "price_momentum": 0.9,
            "filing_materiality": 0.7, "liquidity_quality": 0.9, "freshness": 0.95,
            "data_quality": 0.9,
        }},
    )
    split = build_candidate_executable_split(
        discovery, gate,
        eqs_features={"AAPL": {
            "data_quality": 0.9, "invalidation_defined": 1, "position_sizing_defined": 1,
            "source_health": 0.9, "liquidity_quality": 0.9, "human_review_ready": 1,
        }},
        why_today_scores={"AAPL": 0.9},
        entry_quality_by_ticker={"AAPL": {
            "entry_quality_pass": False,
            "entry_quality_score": 0.18,
            "reasons": ["trend_50: above=False, rising=False"],
        }},
    )
    aapl = next(r for r in split["classified"] if r["ticker"] == "AAPL")
    assert aapl["entry_quality_pass"] is False
    assert aapl["entry_quality_score"] == 0.18
    assert aapl["classification"] == "BUY-CANDIDATE / NOT-EXECUTABLE"
    assert "entry-quality" in aapl["reason"].lower()
    # Name is preserved in discovery, not erased.
    assert any(r["ticker"] == "AAPL" for r in split["buy_candidate_not_executable"])
