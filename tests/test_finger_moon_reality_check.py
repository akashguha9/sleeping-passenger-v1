"""Finger / moon reality check — pointers are not the moon.

Proves AI/news/Polymarket/narrative alone cannot constitute reality
confirmation (pointer-dominance warning fires), while price + volume + filings
raise it, and the source truth hierarchy is exposed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import finger_moon_reality_check as fm


def test_pointers_alone_cannot_be_truth():
    """Loud AI consensus / Polymarket / narrative with no real anchor raises
    the pointer-dominance warning and a low reality score."""
    rep = fm.compute_reality_confirmation(
        ai_consensus=1.0, polymarket_odds=1.0, narrative_strength=1.0,
        price_confirmation=0.0, volume_confirmation=0.0,
        filing_or_official_confirmation=0.0, liquidity_confirmation=0.0,
    )
    assert rep["pointer_dominance_warning"] is True
    assert rep["reality_confirmation_score"] < 2.0
    assert "price" in rep["missing_reality_anchor"]


def test_real_anchors_raise_reality_confirmation():
    pointers = fm.compute_reality_confirmation(ai_consensus=1.0, narrative_strength=1.0)
    anchored = fm.compute_reality_confirmation(
        price_confirmation=0.9, volume_confirmation=0.9,
        filing_or_official_confirmation=0.9, source_credibility=0.9,
        liquidity_confirmation=0.8, outcome_or_moltbook_confirmation=0.8,
    )
    assert anchored["reality_confirmation_score"] > pointers["reality_confirmation_score"]
    assert anchored["pointer_dominance_warning"] is False
    assert anchored["missing_reality_anchor"] == []


def test_source_truth_hierarchy_orders_filings_above_ai():
    rep = fm.compute_reality_confirmation(price_confirmation=0.5)
    hierarchy = rep["source_truth_hierarchy"]
    assert hierarchy.index("filings_official") < hierarchy.index("ai_output")
    assert hierarchy.index("price") < hierarchy.index("polymarket")


def test_advisory_stamps_present():
    rep = fm.compute_reality_confirmation(price_confirmation=0.5)
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
