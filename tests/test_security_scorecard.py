"""The security scorecard's machine-readable block stays valid and honest."""
from __future__ import annotations

import json
import re
from pathlib import Path

_DOC = Path(__file__).resolve().parents[1] / "docs" / "security" / "security_scorecard.md"

_SEGMENTS = (
    "secret_scanning",
    "fixture_hygiene",
    "runtime_file_custody",
    "ci_determinism",
    "workflow_pinning",
    "historical_exposure_containment",
    "release_evidence",
    "regression_resistance",
    "real_money_readiness_impact",
)


def _scorecard() -> dict:
    text = _DOC.read_text(encoding="utf-8")
    m = re.search(r"```json\n(.*?)```", text, re.DOTALL)
    assert m, "scorecard must carry a machine-readable JSON block"
    return json.loads(m.group(1))


def test_scorecard_json_parses_with_all_segments():
    card = _scorecard()
    assert set(card["segments"]) == set(_SEGMENTS)


def test_scores_are_bounded_and_deltas_consistent():
    for name, seg in _scorecard()["segments"].items():
        assert 0 <= seg["pre"] <= 10, name
        assert 0 <= seg["post"] <= 10, name
        assert seg["delta"] == seg["post"] - seg["pre"], name


def test_no_segment_regressed():
    for name, seg in _scorecard()["segments"].items():
        assert seg["delta"] >= 0, f"{name} regressed"
