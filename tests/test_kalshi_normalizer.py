"""
Kalshi normalizer / category allowlist / safety field tests.

No network.  Pure-function tests over scripts/kalshi_normalizer.py.
"""
from __future__ import annotations

import pytest

from scripts.kalshi_normalizer import (
    CANONICAL_CATEGORIES,
    CANONICAL_SOURCE,
    CANONICAL_SOURCE_LABEL,
    EXPLICIT_REJECTED_CATEGORIES,
    KALSHI_CATEGORY_MAP,
    build_kalshi_semantic_text,
    classify_kalshi_category,
    is_kalshi_source,
    kalshi_safety_stamps,
    normalize_kalshi_market,
    normalize_kalshi_source_name,
    stable_kalshi_event_id,
)


# ---------------------------------------------------------------------------
# Source-name normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["kalshi", "Kalshi", "KALSHI", " kalshi ", " KALSHI\t", "kalshi.com"],
)
def test_source_name_variants_normalize_to_kalshi(raw):
    assert normalize_kalshi_source_name(raw) == CANONICAL_SOURCE
    assert is_kalshi_source(raw) is True


@pytest.mark.parametrize("raw", ["", None, 123, "polymarket", "gdelt", "kalshi-bad"])
def test_unrelated_source_names_are_not_kalshi(raw):
    assert normalize_kalshi_source_name(raw) is None
    assert is_kalshi_source(raw) is False


# ---------------------------------------------------------------------------
# Category allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Elections", "Elections"),
        ("elections", "Elections"),
        ("election", "Elections"),
        ("Politics", "Politics"),
        ("political", "Politics"),
        ("Crypto", "Crypto"),
        ("cryptocurrency", "Crypto"),
        ("bitcoin", "Crypto"),
        ("Commodities", "Commodities"),
        ("commodity", "Commodities"),
        ("Economics", "Economics"),
        ("economy", "Economics"),
        ("macro", "Economics"),
        ("Finance", "Finance"),
        ("financial", "Finance"),
        ("markets", "Finance"),
        ("tech & science", "Tech & Science"),
        ("tech and science", "Tech & Science"),
        ("technology", "Tech & Science"),
        ("science", "Tech & Science"),
        ("tech_science", "Tech & Science"),
    ],
)
def test_allowed_categories_are_allowed(raw, expected):
    result = classify_kalshi_category(raw)
    assert result["allowed"] is True
    assert result["display_category"] == expected
    assert result["display_category"] in CANONICAL_CATEGORIES


@pytest.mark.parametrize(
    "raw",
    ["Sports", "sports", "Culture", "Climate", "Social", "Entertainment", "lifestyle"],
)
def test_explicitly_rejected_categories_are_rejected(raw):
    result = classify_kalshi_category(raw)
    assert result["allowed"] is False
    assert result["display_category"] is None
    assert raw.lower() in EXPLICIT_REJECTED_CATEGORIES or "not in the approved" in result["reason"]


@pytest.mark.parametrize("raw", [None, "", "   ", "unknown-category-xyz"])
def test_missing_or_unknown_category_rejected(raw):
    result = classify_kalshi_category(raw)
    assert result["allowed"] is False
    assert result["display_category"] is None


def test_tag_fallback_only_fires_when_category_missing():
    # Missing category but a tag matches → allowed
    result = classify_kalshi_category("", tags=["bitcoin"])
    assert result["allowed"] is True
    assert result["display_category"] == "Crypto"
    # Explicit rejected category beats the tag — tags do NOT override
    result_explicit = classify_kalshi_category("Sports", tags=["bitcoin"])
    assert result_explicit["allowed"] is False


def test_category_map_keys_all_lowercase():
    for key in KALSHI_CATEGORY_MAP:
        assert key == key.lower(), f"map key {key!r} must be lowercase"
    for value in KALSHI_CATEGORY_MAP.values():
        assert value in CANONICAL_CATEGORIES


# ---------------------------------------------------------------------------
# Safety stamps
# ---------------------------------------------------------------------------


def test_safety_stamps_match_advisory_contract():
    stamps = kalshi_safety_stamps()
    assert stamps["advisory_status"] == "ADVISORY_ONLY"
    assert stamps["execution_permission"] == "ADVISORY_ONLY"
    assert stamps["execution_gate"] == "LOCKED"
    assert stamps["human_review_required"] is True
    assert stamps["advisory_only"] is True
    assert stamps["broker_api_called"] is False
    assert stamps["ai_execution_count"] == 0


def test_safety_stamps_return_fresh_dict():
    a = kalshi_safety_stamps()
    a["broker_api_called"] = True
    b = kalshi_safety_stamps()
    assert b["broker_api_called"] is False, "stamps must not share mutable state"


# ---------------------------------------------------------------------------
# Composite semantic_text
# ---------------------------------------------------------------------------


def test_composite_semantic_text_includes_more_than_title():
    text = build_kalshi_semantic_text(
        {
            "title": "How high will Bitcoin get in May?",
            "description": (
                "Market resolves based on whether Bitcoin reaches a specified price during May."
            ),
            "rules": "Uses stated settlement source and event window.",
            "outcomes": ["Yes", "No"],
            "category": "Crypto",
            "tags": ["Bitcoin", "BTC", "May", "price level"],
            "close_time_utc": "2026-05-31T23:59:00Z",
        }
    )
    assert "Title:" in text
    assert "Description:" in text
    assert "Rules:" in text
    assert "Outcomes:" in text
    assert "Category: Crypto" in text
    assert "Tags:" in text
    assert "Close:" in text
    # cross-venue compatibility — Polymarket would say "What price will Bitcoin hit in May?"
    # Both should share enough lexical surface to be matchable by a sentence
    # embedding model.
    assert "Bitcoin" in text
    assert "May" in text


def test_composite_semantic_text_omits_empty_sections():
    text = build_kalshi_semantic_text({"title": "X"})
    assert "Title: X" in text
    assert "Rules:" not in text
    assert "Outcomes:" not in text


# ---------------------------------------------------------------------------
# normalize_kalshi_market — happy path + rejection path
# ---------------------------------------------------------------------------


def _btc_payload(**overrides):
    base = {
        "source": "Kalshi",
        "source_market_id": "BTCMAY-2026",
        "title": "How high will Bitcoin get in May?",
        "description": (
            "Market resolves based on whether Bitcoin reaches a specified price during May."
        ),
        "rules": "Settles to BTC/USD print on Coinbase.",
        "category": "Crypto",
        "tags": ["bitcoin"],
        "yes_price": 0.42,
        "no_price": 0.58,
        "volume": 1250,
        "open_interest": 800,
        "close_time_utc": "2026-05-31T23:59:00Z",
        "market_url": "https://kalshi.com/markets/BTCMAY-2026",
    }
    base.update(overrides)
    return base


def test_normalize_happy_path_carries_all_safety_fields():
    rec = normalize_kalshi_market(_btc_payload(), fetched_at_utc="2026-05-24T00:00:00Z")
    assert rec is not None
    assert rec["source"] == "kalshi"
    assert rec["source_label"] == "Kalshi"
    assert rec["source_market_id"] == "BTCMAY-2026"
    assert rec["category"] == "Crypto"
    assert rec["title"]
    assert rec["semantic_text"] and "Title:" in rec["semantic_text"]
    assert rec["advisory_status"] == "ADVISORY_ONLY"
    assert rec["execution_permission"] == "ADVISORY_ONLY"
    assert rec["execution_gate"] == "LOCKED"
    assert rec["human_review_required"] is True
    assert rec["advisory_only"] is True
    assert rec["broker_api_called"] is False
    assert rec["ai_execution_count"] == 0


def test_normalize_rejects_sports():
    assert normalize_kalshi_market(_btc_payload(category="Sports")) is None


def test_normalize_rejects_missing_category():
    assert normalize_kalshi_market(_btc_payload(category=None, tags=[])) is None


def test_normalize_rejects_non_kalshi_source():
    bad = _btc_payload()
    bad["source"] = "polymarket"
    assert normalize_kalshi_market(bad) is None


def test_normalize_rejects_missing_required_fields():
    assert normalize_kalshi_market(_btc_payload(source_market_id="")) is None
    assert normalize_kalshi_market(_btc_payload(title="")) is None


def test_normalize_yes_price_in_cents_converts_to_probability():
    rec = normalize_kalshi_market(_btc_payload(yes_price=42), fetched_at_utc="now")
    assert rec is not None
    # 42 cents → 0.42 probability
    assert rec["yes_price"] == 42.0
    assert pytest.approx(rec["implied_probability"], rel=1e-6) == 0.42


# ---------------------------------------------------------------------------
# Stable event id
# ---------------------------------------------------------------------------


def test_stable_event_id_is_deterministic():
    a = stable_kalshi_event_id("BTCMAY-2026")
    b = stable_kalshi_event_id("BTCMAY-2026")
    assert a == b
    assert a.startswith("kalshi_")
