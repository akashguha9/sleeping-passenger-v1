"""Decision memo proofs (Pass 4, Phase 10) — banned phrases and structure."""
from __future__ import annotations

import pytest

from scripts import generate_decision_memo as memo


def _signal(**kw):
    base = {
        "ticker": "acme",
        "signal": "watchlist promotion candidate",
        "confidence": 0.62,
        "evidence_summary": "two filings + one price move, all temporally valid",
        "contradictory_evidence": "one analyst note disputes the margin story",
        "missing_data": "no liquidity depth data",
        "temporal_validity": "all evidence valid per temporal_guard",
        "backtest_context": "OOS expectancy +0.8% (n=42, small sample)",
        "calibration_context": "UNCALIBRATED — treat confidence as a prior",
        "risk_notes": "single-supplier concentration",
        "falsifiers": "margin guidance cut, or filing restatement",
        "review_after_days": 21,
    }
    base.update(kw)
    return base


def test_memo_contains_required_sections():
    text = memo.render_memo(_signal())
    for section in (
        "Ticker: ACME", "Advisory-only status", "Signal:", "Confidence:",
        "## Evidence summary", "## Contradictory evidence",
        "## Known missing data", "## Temporal validity",
        "## Backtest context", "## Calibration context", "## Risk notes",
        "## What would falsify this idea", "## Human decision",
        "Post-decision review date:",
    ):
        assert section in text, section
    assert "the system never decides" in text


@pytest.mark.parametrize("phrase", memo.BANNED_PHRASES)
def test_every_banned_phrase_is_refused(phrase):
    with pytest.raises(memo.MemoError):
        memo.render_memo(_signal(evidence_summary=f"this is {phrase} according to X"))


def test_banned_phrases_caught_case_insensitively():
    with pytest.raises(memo.MemoError):
        memo.render_memo(_signal(risk_notes="GUARANTEED upside, Must Buy"))


def test_missing_fields_render_as_warnings_not_blanks():
    text = memo.render_memo({"ticker": "ACME"})
    assert text.count("NOT PROVIDED") >= 8


def test_ticker_mandatory_and_confidence_bounded():
    with pytest.raises(memo.MemoError):
        memo.render_memo({"signal": "x"})
    with pytest.raises(memo.MemoError):
        memo.render_memo(_signal(confidence=1.4))


def test_memo_written_to_decision_memos_dir(tmp_path):
    path = memo.write_memo(_signal(), out_dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name.startswith("ACME_")
    assert path.suffix == ".md"
    assert "Human decision" in path.read_text(encoding="utf-8")
