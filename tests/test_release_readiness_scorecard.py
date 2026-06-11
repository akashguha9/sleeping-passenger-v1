"""Release readiness scorecard: machine-readable, bounded, honest."""
from __future__ import annotations

import json
import re
from pathlib import Path

_DOC = (
    Path(__file__).resolve().parents[1]
    / "docs" / "release" / "release_readiness_scorecard.md"
)

_SEGMENTS = (
    "secret_scanning",
    "security_gate_integrity",
    "dependency_reproducibility",
    "release_evidence",
    "advisory_only_boundary",
    "model_evaluation_honesty",
    "operator_demo_readiness",
    "regression_resistance",
    "ci_determinism",
    "real_money_readiness",
    "investor_demo_readiness",
)


def _scorecard() -> dict:
    m = re.search(r"```json\n(.*?)```", _DOC.read_text(encoding="utf-8"),
                  re.DOTALL)
    assert m, "scorecard must carry a machine-readable JSON block"
    return json.loads(m.group(1))


def test_scorecard_parses_with_all_segments():
    assert set(_scorecard()["segments"]) == set(_SEGMENTS)


def test_scores_bounded_and_deltas_consistent():
    for name, seg in _scorecard()["segments"].items():
        assert 0 <= seg["pre"] <= 10, name
        assert 0 <= seg["post"] <= 10, name
        assert seg["delta"] == seg["post"] - seg["pre"], name


def test_no_segment_regressed():
    for name, seg in _scorecard()["segments"].items():
        assert seg["delta"] >= 0, name


def test_real_money_readiness_stays_conservative():
    """Code changes alone must never move this score (see blockers #5)."""
    seg = _scorecard()["segments"]["real_money_readiness"]
    assert seg["post"] <= 3
