"""Thesis cards: complete product surface, honest labeling, board render."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import signal_thesis_card_report as card
from scripts import signal_ceiling_score_report as ceiling
from scripts import signal_thesis_contract as tc

AS_OF = 1000


def test_card_renders_all_required_sections():
    c = tc.fixture_contract_strong(AS_OF)
    report = tc.grade(c, AS_OF)
    md = card.render_thesis_card(c, report, AS_OF)
    for section in card.REQUIRED_SECTIONS:
        assert section in md, f"missing section: {section}"
    assert "FIXTURE_DEMONSTRATION" in md          # honest data-mode banner
    assert "ADVISORY_ONLY" in md


def test_card_shows_quarantined_anecdote_and_empty_null_warning():
    c = tc.fixture_contract_anecdote_only(AS_OF)
    report = tc.grade(c, AS_OF)
    md = card.render_thesis_card(c, report, AS_OF)
    assert "quarantined" in md
    assert "INSUFFICIENT_EVIDENCE" in md


def test_card_flags_untested_null_in_next_action():
    c = tc.fixture_contract_strong(AS_OF)
    report = tc.grade(c, AS_OF)
    md = card.render_thesis_card(c, report, AS_OF)
    assert "null" in md.lower()


def test_write_card_and_board(tmp_path: Path):
    c1 = tc.fixture_contract_strong(AS_OF)
    c2 = tc.fixture_contract_anecdote_only(AS_OF)
    p1 = card.write_card(c1, AS_OF, tmp_path)
    p2 = card.write_card(c2, AS_OF, tmp_path)
    assert p1.exists() and p2.exists()
    board = card.render_board([(c1, tc.grade(c1, AS_OF)),
                               (c2, tc.grade(c2, AS_OF))])
    assert "THESIS BOARD" in board
    assert c1.ticker in board and c2.ticker in board


def test_renderer_raises_on_missing_section(monkeypatch):
    c = tc.fixture_contract_strong(AS_OF)
    report = tc.grade(c, AS_OF)
    monkeypatch.setattr(card, "REQUIRED_SECTIONS",
                        card.REQUIRED_SECTIONS + ("SECTION THAT DOES NOT EXIST",))
    with pytest.raises(ValueError, match="missing required sections"):
        card.render_thesis_card(c, report, AS_OF)


def test_ceiling_report_blocks_deltas_without_artifacts(tmp_path: Path):
    """On an empty root no artifact exists, so no delta may be granted."""
    report = ceiling.build_report(root=tmp_path)
    for seg, row in report["segments"].items():
        assert row["delta"] == 0.0, (seg, row)
    assert report["advisory_status"] == "ADVISORY_ONLY"


def test_ceiling_report_grants_deltas_only_with_evidence():
    report = ceiling.build_report()
    for seg, row in report["segments"].items():
        if row["delta"] > 0:
            assert row["blocked_by"] == [], (seg, row)
    assert report["new_overall_ceiling"] <= 10.0
