"""Role-fit scorecard evidence freshness — proof_loop_hardening_sprint, Phase 7.

Pins the leakage control: path-existence alone is *not* full evidence.
Stale artifacts decay the segment's R_adj_s.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from scripts.segment_role_scorecard import (
    DEFAULT_ARTIFACT_MAX_AGE_DAYS,
    Criterion,
    Segment,
    _max_age_for,
)


pytestmark = [
    pytest.mark.safety_floor,
]


def _make_segment(criteria: list[Criterion]) -> Segment:
    return Segment(
        segment="test_segment",
        role_name="test_role",
        role_description="test description",
        target_relevance=1.0,
        absolute_score=5.0,
        absolute_ceiling_reason="unit test",
        confidence=1.0,
        criteria=criteria,
        blockers=[],
        next_action="n/a",
    )


def _touch(path: Path, age_days: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    if age_days is not None:
        now = time.time()
        mtime = now - age_days * 86400.0
        os.utime(path, (mtime, mtime))


def test_missing_artifact_yields_zero_evidence(tmp_path):
    crit = Criterion("c", 1.0, 1.0, ("does/not/exist.json",))
    seg = _make_segment([crit])
    seg._finalise(repo_root=tmp_path)
    assert seg.evidence_completeness == 0.0


def test_fresh_artifact_yields_full_evidence(tmp_path):
    rel = "runtime/release/calibration_report.json"
    _touch(tmp_path / rel, age_days=0.0)
    crit = Criterion("c", 1.0, 1.0, (rel,))
    seg = _make_segment([crit])
    seg._finalise(repo_root=tmp_path)
    assert seg.evidence_completeness == pytest.approx(1.0)


def test_half_stale_artifact_lands_around_half(tmp_path):
    # max_age for calibration_report is 7 days; age = 10.5 -> 0.5
    rel = "runtime/release/calibration_report.json"
    _touch(tmp_path / rel, age_days=10.5)
    crit = Criterion("c", 1.0, 1.0, (rel,))
    seg = _make_segment([crit])
    seg._finalise(repo_root=tmp_path)
    assert seg.evidence_completeness == pytest.approx(0.5, abs=0.05)


def test_fully_stale_artifact_yields_zero(tmp_path):
    rel = "runtime/release/calibration_report.json"
    _touch(tmp_path / rel, age_days=100.0)
    crit = Criterion("c", 1.0, 1.0, (rel,))
    seg = _make_segment([crit])
    seg._finalise(repo_root=tmp_path)
    assert seg.evidence_completeness == pytest.approx(0.0)


def test_segment_role_fit_decreases_when_artifact_ages(tmp_path):
    rel = "runtime/release/calibration_report.json"
    # Fresh: full evidence
    _touch(tmp_path / rel, age_days=0.0)
    crit = Criterion("c", 1.0, 1.0, (rel,))
    fresh = _make_segment([crit])
    fresh._finalise(repo_root=tmp_path)
    fresh_score = fresh.confidence_adjusted_role_fit

    # Stale: same paths, but aged past max_age budget
    _touch(tmp_path / rel, age_days=100.0)
    stale = _make_segment([Criterion("c", 1.0, 1.0, (rel,))])
    stale._finalise(repo_root=tmp_path)
    stale_score = stale.confidence_adjusted_role_fit

    assert stale_score < fresh_score


def test_path_existence_alone_is_insufficient_for_full_evidence(tmp_path):
    """Creating an empty file but aging it beyond max_age must penalise."""
    rel = "runtime/release/calibration_report.json"
    _touch(tmp_path / rel, age_days=30.0)
    crit = Criterion("c", 1.0, 1.0, (rel,))
    seg = _make_segment([crit])
    seg._finalise(repo_root=tmp_path)
    assert seg.evidence_completeness < 1.0


def test_max_age_resolves_default_for_unknown_path():
    assert _max_age_for("docs/some/unknown_path.md") == DEFAULT_ARTIFACT_MAX_AGE_DAYS


def test_criterion_with_no_evidence_path_does_not_count_in_e_s(tmp_path):
    rel = "runtime/release/calibration_report.json"
    _touch(tmp_path / rel, age_days=0.0)
    has_evidence = Criterion("c_a", 0.5, 1.0, (rel,))
    no_evidence = Criterion("c_b", 0.5, 1.0, ())
    seg = _make_segment([has_evidence, no_evidence])
    seg._finalise(repo_root=tmp_path)
    # Only the criterion with evidence contributes; full freshness
    # therefore lifts E_s to 1.0.
    assert seg.evidence_completeness == pytest.approx(1.0)
