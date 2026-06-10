"""Module G — compatibility / portfolio fit invariants."""

from __future__ import annotations

from src.alpha.compatibility import assess_portfolio_fit, pairwise_compatibility


def _semis(c_ij: float) -> tuple[list[dict], dict]:
    assets = [
        {"name": "chipmaker", "weight": 0.5, "quality": 90.0},
        {"name": "foundry", "weight": 0.5, "quality": 90.0},
    ]
    matrix = {("chipmaker", "foundry"): c_ij}
    return assets, matrix


def test_two_apexes_can_clash() -> None:
    assets, clash = _semis(-1.0)
    _, synergy = _semis(1.0)
    clashed = assess_portfolio_fit(assets, clash)
    synergized = assess_portfolio_fit(assets, synergy)
    assert clashed["portfolio_fit_score"] < synergized["portfolio_fit_score"]
    assert clashed["overlap_risk"] > synergized["overlap_risk"]


def test_scores_are_bounded() -> None:
    for c_ij in (-1.0, 0.0, 1.0):
        assets, matrix = _semis(c_ij)
        result = assess_portfolio_fit(assets, matrix)
        assert 0.0 <= result["portfolio_fit_score"] <= 100.0
        assert 0.0 <= result["overlap_risk"] <= 100.0


def test_heavy_interference_recommends_avoid_stack() -> None:
    assets, matrix = _semis(-1.0)
    result = assess_portfolio_fit(assets, matrix)
    assert result["sequencing_recommendation"] == "avoid_stack"


def test_quality_plus_synergy_recommends_core_now() -> None:
    assets, matrix = _semis(0.5)
    result = assess_portfolio_fit(assets, matrix)
    assert result["sequencing_recommendation"] == "core_now"


def test_missing_pairs_default_to_independent() -> None:
    assets, _ = _semis(0.0)
    result = assess_portfolio_fit(assets, None)
    assert result["missing_inputs"] == ["compatibility[chipmaker,foundry]"]
    assert result["compatibility_matrix"][0]["c_ij"] == 0.0


def test_pair_key_order_does_not_matter() -> None:
    assets = [
        {"name": "b_asset", "weight": 0.5, "quality": 80.0},
        {"name": "a_asset", "weight": 0.5, "quality": 80.0},
    ]
    result = assess_portfolio_fit(assets, {("a_asset", "b_asset"): -0.8})
    assert result["compatibility_matrix"][0]["c_ij"] == -0.8


def test_single_asset_portfolio_does_not_crash() -> None:
    result = assess_portfolio_fit([{"name": "solo", "weight": 1.0, "quality": 70.0}])
    assert result["portfolio_fit_score"] == 70.0
    assert result["compatibility_matrix"] == []


def test_pairwise_compatibility_correlation_heuristic() -> None:
    # High correlation between two strong assets = concentration risk.
    assert pairwise_compatibility(90.0, 90.0, 0.9) < 0
    # Negative correlation = diversification benefit.
    assert pairwise_compatibility(90.0, 90.0, -0.9) > 0
    assert -1.0 <= pairwise_compatibility(100.0, 100.0, 1.0) <= 1.0
