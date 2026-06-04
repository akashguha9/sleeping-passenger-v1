"""Tests for the discovery_v2 candidate scorer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import discovery_v2 as dv


def test_unpriceable_is_hard_skip_regardless_of_other_factors():
    r = dv.score_candidate(liquidity_tier="unpriceable", region="US", momentum=1.0)
    assert r["tier"] == dv.SKIP


def test_liquid_developed_name_is_tradable():
    r = dv.score_candidate(liquidity_tier="high", region="US", momentum=0.7)
    assert r["tier"] == dv.TRADE
    assert 0.0 <= r["score"] <= 1.0


def test_score_is_bounded_and_advisory_only():
    r = dv.score_candidate(liquidity_tier="med", region="DE")
    assert 0.0 <= r["score"] <= 1.0
    assert r["broker_api_called"] is False
    assert r["human_execution_required"] is True


def test_missing_inputs_degrade_to_neutral_not_crash():
    r = dv.score_candidate()
    assert r["tier"] in {dv.TRADE, dv.WATCH, dv.SKIP}


def test_rank_orders_best_first():
    cands = [
        {"ticker": "THIN", "liquidity_tier": "unpriceable", "region": "KR"},
        {"ticker": "MEGA", "liquidity_tier": "high", "region": "US", "momentum": 0.8},
        {"ticker": "MID", "liquidity_tier": "med", "region": "DE"},
    ]
    ranked = dv.rank(cands)
    assert ranked[0]["ticker"] == "MEGA"
    assert ranked[-1]["ticker"] == "THIN"
    assert ranked[-1]["tier"] == dv.SKIP
