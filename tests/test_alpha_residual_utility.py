"""Module B — residual utility engine invariants."""

from __future__ import annotations

from src.alpha.residual_utility import score_residual_utility

_PLUMBING_LIKE = {
    "recurring_need": 1.0,
    "non_optional": 1.0,
    "retention_without_hype": 1.0,
    "cost_or_safety_advantage": 0.8,
    "unprompted_repeat_demand": 0.9,
    "failure_urgency": 0.9,
}
_MEME_LIKE = {
    "recurring_need": 0.1,
    "non_optional": 0.0,
    "retention_without_hype": 0.1,
    "cost_or_safety_advantage": 0.1,
    "unprompted_repeat_demand": 0.1,
    "failure_urgency": 0.0,
}
_STORY_FREE = {
    "brand_dependence": 0.0,
    "promotion_dependence": 0.0,
    "status_premium": 0.0,
    "speculative_interest": 0.0,
}
_STORY_HEAVY = {key: 1.0 for key in _STORY_FREE}


def test_scores_are_bounded() -> None:
    for utility, narrative in [
        (_PLUMBING_LIKE, _STORY_FREE),
        (_MEME_LIKE, _STORY_HEAVY),
        (None, None),
    ]:
        result = score_residual_utility(utility, narrative)
        assert 0.0 <= result["residual_utility_score"] <= 100.0
        assert 0.0 <= result["narrative_dependency_score"] <= 100.0
        assert -100.0 <= result["residual_alpha_proxy"] <= 100.0


def test_boring_necessity_beats_meme() -> None:
    boring = score_residual_utility(_PLUMBING_LIKE, _STORY_FREE)
    meme = score_residual_utility(_MEME_LIKE, _STORY_HEAVY)
    assert boring["residual_utility_score"] > meme["residual_utility_score"]
    assert meme["narrative_dependency_score"] > boring["narrative_dependency_score"]


def test_narrative_dependence_erodes_residual_utility() -> None:
    clean = score_residual_utility(_PLUMBING_LIKE, _STORY_FREE)
    storied = score_residual_utility(_PLUMBING_LIKE, _STORY_HEAVY)
    assert storied["residual_utility_score"] < clean["residual_utility_score"]


def test_alpha_proxy_is_utility_minus_price_expectation() -> None:
    cheap = score_residual_utility(
        _PLUMBING_LIKE, _STORY_FREE, market_price_expectation=10.0
    )
    expensive = score_residual_utility(
        _PLUMBING_LIKE, _STORY_FREE, market_price_expectation=95.0
    )
    assert cheap["residual_alpha_proxy"] > expensive["residual_alpha_proxy"]
    assert expensive["residual_alpha_proxy"] < 0


def test_missing_inputs_default_neutral_without_crash() -> None:
    result = score_residual_utility(None, None)
    assert len(result["missing_inputs"]) == 10
    assert result["residual_utility_score"] > 0


def test_output_carries_job_and_stripped_layers() -> None:
    result = score_residual_utility(
        _PLUMBING_LIKE, _STORY_FREE, core_job_to_be_done="move water"
    )
    assert result["core_job_to_be_done"] == "move water"
    assert "logo" in result["stripped_layers"]
    assert result["explanation"]
