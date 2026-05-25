"""
Kalshi title normalization tests.

The screenshot regression had raw "yes Taylor Fritz, yes Hamad Medjedovic,
yes Joao Fonseca, ..." outcome dumps surfacing as the primary card title.
``normalize_kalshi_title`` must reject these leaks, preserve the outcomes
separately, and prefer event_title / market_title / title / question /
subtitle / ticker fallback in priority order.
"""
from __future__ import annotations

from scripts.kalshi_normalizer import (
    TITLE_CLEANED_OUTCOMES,
    TITLE_OFFICIAL_TITLE,
    TITLE_OFFICIAL_QUESTION,
    TITLE_TICKER_FALLBACK,
    normalize_kalshi_market,
    normalize_kalshi_title,
)


def test_yes_outcome_leak_is_rejected_as_primary_title():
    raw_title = (
        "yes Taylor Fritz, yes Hamad Medjedovic, yes Joao Fonseca, yes Peyton Stearns"
    )
    decision = normalize_kalshi_title(
        {
            "title": raw_title,
            "ticker": "KXMVESPORTS-2026",
        }
    )
    assert not decision["primary_title"].lower().startswith("yes ")
    assert decision["title_quality"] in {TITLE_TICKER_FALLBACK, TITLE_CLEANED_OUTCOMES}
    assert any("yes_outcome_leak" in w for w in decision["title_warnings"])
    # Outcomes preserved separately, not concatenated into the title.
    assert "Taylor Fritz" in decision["outcomes"]
    assert "Hamad Medjedovic" in decision["outcomes"]


def test_official_event_title_wins_priority_over_outcomes_or_title():
    decision = normalize_kalshi_title(
        {
            "event_title": "Texas Republican Senate nominee?",
            "title": "yes Cornyn, yes Allred",
            "outcomes": ["Cornyn", "Allred"],
            "ticker": "TXSEN-2026",
        }
    )
    assert decision["primary_title"] == "Texas Republican Senate nominee?"
    assert decision["title_source"] == "event_title"
    assert decision["title_quality"] == TITLE_OFFICIAL_TITLE


def test_question_field_is_used_when_no_title_or_event_title():
    decision = normalize_kalshi_title(
        {
            "question": "BTC price today at 6am EDT?",
            "ticker": "BTC-2026-05-25",
        }
    )
    assert decision["primary_title"] == "BTC price today at 6am EDT?"
    assert decision["title_source"] == "question"
    assert decision["title_quality"] == TITLE_OFFICIAL_QUESTION


def test_outcomes_fallback_when_only_outcomes_are_present():
    decision = normalize_kalshi_title(
        {
            "outcomes": ["Cornyn", "Allred", "Other"],
        }
    )
    assert decision["primary_title"].startswith("Kalshi multi-outcome market:")
    assert decision["title_quality"] == TITLE_CLEANED_OUTCOMES


def test_normalize_market_carries_title_decision_onto_payload():
    rec = normalize_kalshi_market(
        {
            "source": "Kalshi",
            "source_market_id": "TXSEN-2026",
            "ticker": "TXSEN-2026",
            "event_title": "Texas Republican Senate nominee?",
            "title": "yes Cornyn, yes Allred",  # raw outcome leak
            "category": "Elections",
            "outcomes": ["Cornyn", "Allred"],
            "close_time_utc": "2026-11-03T05:00:00Z",
        },
        fetched_at_utc="2026-05-25T12:00:00Z",
    )
    assert rec is not None
    assert rec["title"] == "Texas Republican Senate nominee?"
    assert rec["primary_title"] == "Texas Republican Senate nominee?"
    assert rec["title_quality"] == TITLE_OFFICIAL_TITLE
    assert "Cornyn" in rec["outcomes"]
    # Safety still intact.
    assert rec["advisory_only"] is True
    assert rec["broker_api_called"] is False
    assert rec["ai_execution_count"] == 0
