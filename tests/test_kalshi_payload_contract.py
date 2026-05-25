"""
Frontend/API payload contract tests for the Kalshi tab.

Asserts every accepted Kalshi payload carries:
- mvp_category in the seven-slug allowlist
- display_category set to the matching human label
- category_allowed=true and visible_in_kalshi_feed=true
- source_freshness_status, market_activity_status, ui_badge_status
- full advisory-safety block

And that quarantined records emit visible_in_kalshi_feed=false with a
machine-readable quarantine_reason — never the misleading CRYPTO label.
"""
from __future__ import annotations

from scripts.ingestion.kalshi_loader import partition_kalshi_records
from scripts.kalshi_category_governance import ALLOWED_KALSHI_CATEGORIES, DISPLAY_LABELS


def test_accepted_payload_contract_is_complete():
    records = [
        {
            "source": "kalshi",
            "ticker": "BTCMAY-2026",
            "title": "How high will Bitcoin get in May?",
            "category": "Crypto",
            "close_time_utc": "2026-05-31T23:59:00Z",
        }
    ]
    accepted, quarantined = partition_kalshi_records(
        records, fetched_at_utc="2026-05-25T12:00:00Z"
    )
    assert len(accepted) == 1
    assert len(quarantined) == 0
    rec = accepted[0]
    assert rec["mvp_category"] in ALLOWED_KALSHI_CATEGORIES
    assert rec["display_category"] == DISPLAY_LABELS[rec["mvp_category"]]
    assert rec["category_allowed"] is True
    assert rec["visible_in_kalshi_feed"] is True
    assert rec["quarantine_reason"] == ""
    # Freshness + activity badges present.
    assert rec["source_freshness_status"]
    assert rec["market_activity_status"]
    assert rec["ui_badge_status"]
    # Safety block intact.
    assert rec["advisory_only"] is True
    assert rec["human_review_required"] is True
    assert rec["broker_api_called"] is False
    assert rec["ai_execution_count"] == 0


def test_kxmvesports_quarantined_with_machine_readable_reason_not_crypto():
    records = [
        {
            "source": "kalshi",
            "ticker": "KXMVESPORTSMULTIGAMEEXTENDED-S2026376EC71BC21-CAF0CE6479C",
            "event_ticker": "KXMVESPORTS-2026",
            "title": "yes Taylor Fritz, yes Hamad Medjedovic, yes Joao Fonseca, yes Peyton Stearns",
            "category": "",
            "tags": ["tennis", "atp"],
        }
    ]
    accepted, quarantined = partition_kalshi_records(
        records, fetched_at_utc="2026-05-25T12:00:00Z"
    )
    assert accepted == []
    assert len(quarantined) == 1
    q = quarantined[0]
    assert q["visible_in_kalshi_feed"] is False
    assert q["category_allowed"] is False
    # Reason is OUT_OF_SCOPE-class, NOT misleading CRYPTO.
    assert q["mvp_category"] is None
    assert "crypto" not in (q["quarantine_reason"] or "").lower()
    assert (
        q["quarantine_reason"].startswith("ticker_pattern_rejected")
        or q["quarantine_reason"].startswith("category_explicitly_rejected")
        or q["quarantine_reason"].startswith("category_not_in_allowlist")
    )
    # Safety block intact even on quarantined records.
    assert q["advisory_only"] is True
    assert q["broker_api_called"] is False
    assert q["ai_execution_count"] == 0


def test_quarantined_records_never_classified_as_any_allowlist_slug():
    """No quarantine reason / category may falsely surface as one of the
    seven allowed display labels — the screenshot bug was esports being
    rendered as CRYPTO."""
    bad_inputs = [
        {"ticker": "KXMVESPORTS-1", "title": "tennis", "category": "esports"},
        {"ticker": "ATPTOUR-99", "title": "yes Carlos Alcaraz, yes Sinner", "category": ""},
        {"ticker": "OSCAR-2027", "title": "Best Picture nominee?", "category": "entertainment"},
        {"ticker": "RANDOM-XYZ", "title": "Mystery question", "category": "trending"},
    ]
    _, quarantined = partition_kalshi_records(
        bad_inputs, fetched_at_utc="2026-05-25T12:00:00Z"
    )
    assert len(quarantined) == len(bad_inputs)
    for q in quarantined:
        assert q["mvp_category"] is None
        assert q["visible_in_kalshi_feed"] is False
        for label in DISPLAY_LABELS.values():
            # The reason text may mention the input category but must not
            # claim the record IS in any allowed slug.
            assert q.get("display_category") != label
