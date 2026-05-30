"""Tests for the Kanté score-ceiling audit doc (WORKSTREAM A)."""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "KANTE_SCORE_CEILING_AUDIT.md"

# The exact 22 segment names from the sprint baseline.
_SEGMENTS = (
    "Signal richness",
    "Quant sophistication",
    "Data/model diversity",
    "Technical defensibility",
    "Daily runtime usefulness",
    "External evidence architecture",
    "Source-health maturity",
    "Advisory-only safety",
    "Human-execution discipline",
    "DIABLO / chaos-veto integrity",
    "Fake-confidence resistance",
    "Persistence maturity",
    "Moltbook learning value",
    "Frontend explainability",
    "Test coverage",
    "CI stability",
    "Maintainability",
    "Complexity health",
    "Investor impressiveness",
    "Real-money readiness",
    "Year-1 survival compatibility",
    "Overall MVP score",
)


def test_kante_score_ceiling_doc_exists() -> None:
    assert _DOC.is_file(), "docs/KANTE_SCORE_CEILING_AUDIT.md must exist"
    assert _DOC.read_text(encoding="utf-8").strip(), "audit doc must not be empty"


def test_kante_score_ceiling_doc_states_real_money_not_ready() -> None:
    text = _DOC.read_text(encoding="utf-8").lower()
    assert "real-money readiness" in text
    # Real money must be explicitly described as prohibited / not ready.
    assert "prohibited" in text
    assert "no broker" in text
    assert "no 50" in text or "50–100 paper" in text or "50-100 paper" in text


def test_kante_score_ceiling_doc_has_all_22_segments() -> None:
    text = _DOC.read_text(encoding="utf-8")
    missing = [seg for seg in _SEGMENTS if seg not in text]
    assert not missing, f"audit doc missing segments: {missing}"
    assert len(_SEGMENTS) == 22
