"""Model scorecard proofs (Pass 4, Phase 7) — evidence caps cannot be argued up."""
from __future__ import annotations

import pytest

from scripts import model_scorecard as sc


def _segments(score=7.0, **flags):
    base_flags = {"has_tests": True, "has_out_of_sample": False,
                  "has_independent_validation": False}
    base_flags.update(flags)
    return [
        {"segment": name, "claimed_score": score,
         "evidence": f"tests + reports for {name}", "gap": "", "next_fix": "",
         **base_flags}
        for name in sc.SEGMENT_WEIGHTS
    ]


def test_weights_sum_to_one():
    assert sum(sc.SEGMENT_WEIGHTS.values()) == pytest.approx(1.0)


def test_total_formula_exact():
    card = sc.build_scorecard(_segments(score=7.0))
    assert card["total"] == pytest.approx(7.0)


def test_no_score_above_8_without_tests():
    score, note = sc.apply_evidence_caps(
        9.5, has_tests=False, has_out_of_sample=True,
        has_independent_validation=False)
    assert score == 8.0 and "no tests" in note


def test_no_score_above_9_without_out_of_sample():
    score, note = sc.apply_evidence_caps(
        9.8, has_tests=True, has_out_of_sample=False,
        has_independent_validation=False)
    assert score == 9.0 and "out-of-sample" in note


def test_ten_requires_independent_validation():
    score, note = sc.apply_evidence_caps(
        10.0, has_tests=True, has_out_of_sample=True,
        has_independent_validation=False)
    assert score == 9.5 and "independent validation" in note


def test_evidence_is_mandatory():
    segments = _segments()
    segments[0]["evidence"] = "  "
    with pytest.raises(sc.ScorecardError):
        sc.build_scorecard(segments)


def test_all_segments_mandatory():
    with pytest.raises(sc.ScorecardError):
        sc.build_scorecard(_segments()[:-1])


def test_score_bounds():
    with pytest.raises(sc.ScorecardError):
        sc.apply_evidence_caps(11.0, has_tests=True, has_out_of_sample=True,
                               has_independent_validation=True)


def test_rendered_scorecard_table_and_clamps(tmp_path):
    segments = _segments(score=9.5)  # tests yes, OOS no → clamp to 9
    path = sc.write_scorecard(segments, out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name.startswith("model_scorecard_")
    assert "| Segment | Weight | Score /10 | Evidence | Gap | Next Fix |" in text
    assert "clamped to 9" in text
    assert "never expected profit" in text
