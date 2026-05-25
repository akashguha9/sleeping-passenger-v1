"""
Kalshi category governance tests.

Covers the seven-tab allowlist, explicit/inferred rejections, the
KXMVESPORTS ticker regression, and the safety invariants every
``CategoryDecision`` must carry.
"""
from __future__ import annotations

import pytest

from scripts.kalshi_category_governance import (
    ALLOWED_KALSHI_CATEGORIES,
    CATEGORY_SOURCE_KEYWORD,
    CATEGORY_SOURCE_OFFICIAL,
    CATEGORY_SOURCE_ROUTE,
    CATEGORY_SOURCE_TICKER,
    DISPLAY_LABELS,
    QUARANTINE_EXPLICIT_REJECTED,
    QUARANTINE_NOT_IN_ALLOWLIST,
    QUARANTINE_NO_USABLE_METADATA,
    QUARANTINE_TICKER_REJECTED,
    normalize_kalshi_category,
)


@pytest.mark.parametrize(
    "raw,slug",
    [
        ("Elections", "elections"),
        ("Politics", "politics"),
        ("Crypto", "crypto"),
        ("Commodities", "commodities"),
        ("Economics", "economics"),
        ("Finance", "finance"),
        ("Tech & Science", "tech_science"),
        ("tech and science", "tech_science"),
        ("technology", "tech_science"),
    ],
)
def test_allowed_categories_normalize_to_canonical_slug(raw, slug):
    decision = normalize_kalshi_category(raw)
    assert decision["category_allowed"] is True
    assert decision["mvp_category"] == slug
    assert decision["display_category"] == DISPLAY_LABELS[slug]
    assert decision["category_source"] == CATEGORY_SOURCE_OFFICIAL
    assert decision["quarantine_reason"] == ""
    assert decision["safety"]["advisory_only"] is True
    assert decision["safety"]["broker_api_called"] is False
    assert decision["safety"]["ai_execution_count"] == 0
    assert decision["safety"]["execution_locked"] is True


@pytest.mark.parametrize(
    "raw",
    [
        "Sports", "esports", "e-sports", "gaming", "culture", "climate",
        "mentions", "entertainment", "trending", "weather", "other",
        "Multi-Game", "tennis", "golf", "lifestyle",
    ],
)
def test_explicitly_rejected_categories_quarantine(raw):
    decision = normalize_kalshi_category(raw)
    assert decision["category_allowed"] is False
    assert decision["mvp_category"] is None
    assert decision["display_category"] is None
    assert decision["quarantine_reason"].startswith(QUARANTINE_EXPLICIT_REJECTED)
    # Safety must still be present on every rejected decision.
    assert decision["safety"]["advisory_only"] is True
    assert decision["safety"]["execution_locked"] is True
    assert decision["safety"]["broker_api_called"] is False


@pytest.mark.parametrize("raw", [None, "", "   ", "unknown-category-xyz"])
def test_unknown_or_missing_categories_quarantine(raw):
    decision = normalize_kalshi_category(raw)
    assert decision["category_allowed"] is False
    assert decision["mvp_category"] is None
    assert decision["quarantine_reason"] in {
        QUARANTINE_NOT_IN_ALLOWLIST,
        QUARANTINE_NO_USABLE_METADATA,
    }


def test_source_route_can_rescue_a_missing_category():
    decision = normalize_kalshi_category(
        "",
        source_route="elections",
    )
    assert decision["category_allowed"] is True
    assert decision["mvp_category"] == "elections"
    assert decision["category_source"] == CATEGORY_SOURCE_ROUTE


def test_ticker_prefix_can_rescue_btc():
    decision = normalize_kalshi_category("", ticker="BTCMAY-2026")
    assert decision["category_allowed"] is True
    assert decision["mvp_category"] == "crypto"
    # Could be ticker_fallback or keyword_fallback depending on inference path.
    assert decision["category_source"] in {CATEGORY_SOURCE_TICKER, CATEGORY_SOURCE_KEYWORD}


def test_kxmvesports_ticker_is_hard_rejected_even_if_crypto_inference_would_fire():
    # The screenshot regression: KXMVESPORTSMULTIGAMEEXTENDED was being
    # mis-classified as CRYPTO.  The governance layer must hard-reject
    # before any inference layer runs.
    decision = normalize_kalshi_category(
        "",
        ticker="KXMVESPORTSMULTIGAMEEXTENDED-S2026376EC71BC21-CAF0CE6479C",
        event_metadata={"title": "Will Bitcoin reach $100k this week?"},
    )
    assert decision["category_allowed"] is False
    assert decision["mvp_category"] is None
    assert decision["quarantine_reason"].startswith(QUARANTINE_TICKER_REJECTED)
    # Either ESPORTS or MVESPORTS substring match is acceptable — both
    # mean "out of scope, do not classify as crypto".
    assert any(
        token in decision["quarantine_reason"].lower()
        for token in ("esports", "mvesports", "multigame")
    )
    assert decision["safety"]["broker_api_called"] is False


def test_allowed_slugs_are_exactly_seven():
    assert ALLOWED_KALSHI_CATEGORIES == {
        "elections", "politics", "crypto", "commodities",
        "economics", "finance", "tech_science",
    }
    assert set(DISPLAY_LABELS) == ALLOWED_KALSHI_CATEGORIES
