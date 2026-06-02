"""Tests for scripts/discovery_board.py — discovery before trade candidates."""
from __future__ import annotations

from datetime import date

from scripts.discovery_board import (
    ALLOWED_LABELS,
    AVOID,
    RISK_BLOCK,
    TRADE_CANDIDATE,
    WAIT,
    WATCH,
    DiscoveryCandidate,
    build_daily_discovery_board,
    classify_promotion,
    compute_discovery_score,
)

BANNED = ("BUY", "SELL", "EXECUTE", "PLACE ORDER", "BROKER")


def _strong(ticker, country, score_components=100.0, **over):
    kw = dict(
        ticker=ticker, country=country,
        country_relative_strength=score_components,
        sector_relative_strength=score_components,
        catalyst_score=score_components,
        liquidity_score=score_components,
        model_consensus=score_components,
        data_freshness_score=score_components,
        chaos_risk=0.0, contradiction_score=0.0, sector="Tech",
    )
    kw.update(over)
    return DiscoveryCandidate(**kw)


def test_discovery_score_formula():
    c = DiscoveryCandidate(
        country_relative_strength=50, sector_relative_strength=50, catalyst_score=50,
        liquidity_score=50, model_consensus=50, data_freshness_score=50,
        chaos_risk=0, contradiction_score=0, correlation_penalty=0,
        duplicate_theme_penalty=0,
    )
    # 0.18*50*3 + 0.14*50*2 + 0.10*50 = 27 + 14 + 5 = 46
    assert compute_discovery_score(c) == 46.0


def test_promotion_labels_cover_gates():
    assert classify_promotion(_strong("A", "US"), 92.0) == TRADE_CANDIDATE
    assert classify_promotion(DiscoveryCandidate(chaos_risk=85, liquidity_score=90), 90) == RISK_BLOCK
    assert classify_promotion(DiscoveryCandidate(liquidity_score=10, data_freshness_score=90), 90) == AVOID
    assert classify_promotion(DiscoveryCandidate(liquidity_score=90, data_freshness_score=20), 90) == WAIT
    # mid score, no block -> WATCH
    assert classify_promotion(DiscoveryCandidate(liquidity_score=90, data_freshness_score=90), 72) == WATCH


def test_board_has_all_sections_and_precedes_trade_candidates():
    cands = [_strong(f"US{i}", "United States") for i in range(3)] + [
        _strong("JP1", "Japan"), _strong("UK1", "United Kingdom"),
    ]
    board = build_daily_discovery_board(cands, board_date=date(2026, 6, 2))
    assert board["discovery_board_precedes_trade_candidates"] is True
    for key in (
        "country_discovery_table", "global_ranked_top30",
        "manual_review_candidates", "concentration_warnings",
    ):
        assert key in board
    assert board["total_discovered"] == 5


def test_board_uses_only_advisory_labels_no_buy_sell():
    cands = [_strong(f"US{i}", "United States") for i in range(4)]
    board = build_daily_discovery_board(cands)
    # Every promotion label is in the allowed advisory set.
    labels = {r["promotion_status"] for r in board["global_ranked_top30"]}
    assert labels <= ALLOWED_LABELS
    blob = str(board).upper()
    for tok in BANNED:
        # "BUY"/"SELL" must not appear as a label/instruction anywhere.
        assert tok not in {l.upper() for l in board["allowed_labels"]}
        assert f" {tok} " not in blob


def test_board_caps_promotions_per_country():
    # 5 strong US trade candidates -> at most US cap (2) promoted.
    cands = [_strong(f"US{i}", "United States", score_components=100.0) for i in range(5)]
    board = build_daily_discovery_board(cands)
    assert len(board["manual_review_candidates"]) <= 2
    assert board["promoted_count"] <= 2
    assert board["cap_limited_count"] >= 3


def test_sk_heavy_board_warns_concentration():
    cands = [_strong(f"KR{i}", "South Korea") for i in range(4)]
    board = build_daily_discovery_board(cands)
    assert board["concentration_warnings"]  # non-empty
    assert board["diversity_forces_trades"] is False
