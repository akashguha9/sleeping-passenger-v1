"""Tests for the canonical Asia Disclosure country list.

The Asia Disclosure section/tab inside Live Signals must include exactly
the 11 Asia countries below (India excluded — India has its own
dedicated source family).  Tests verify the canonical list directly,
the tabular rows have the expected columns, and the India-specific
loader path is untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


EXPECTED_COUNTRIES = [
    "China",
    "Japan",
    "Russia",
    "South Korea",
    "Turkey",
    "Indonesia",
    "Saudi Arabia",
    "Taiwan",
    "Israel",
    "Singapore",
    "United Arab Emirates",
]


def test_asia_disclosure_country_list_matches_canonical_set():
    from scripts.ingestion.asia_disclosure_loader import (
        get_asia_disclosure_countries,
    )

    countries = get_asia_disclosure_countries()
    assert countries == EXPECTED_COUNTRIES


def test_india_is_not_in_asia_disclosure_list():
    from scripts.ingestion.asia_disclosure_loader import (
        get_asia_disclosure_countries,
        ASIA_DISCLOSURE_COUNTRIES,
    )

    assert "India" not in get_asia_disclosure_countries()
    assert "India" not in ASIA_DISCLOSURE_COUNTRIES


def test_asia_disclosure_country_rows_shape_and_status():
    from scripts.ingestion.asia_disclosure_loader import (
        get_asia_disclosure_country_rows,
    )

    rows = get_asia_disclosure_country_rows()
    assert len(rows) == 11

    required_columns = {"country", "disclosure_source", "source_url", "status", "notes"}
    countries_seen: list[str] = []
    for row in rows:
        assert required_columns <= set(row.keys()), f"missing columns in {row!r}"
        assert row["status"] == "Active", f"row not Active: {row!r}"
        # No invented URLs — placeholders must be empty strings, not fake
        # http(s) endpoints.  This guards against accidental URL fabrication.
        assert not row["source_url"] or row["source_url"].startswith(
            ("http://", "https://")
        )
        countries_seen.append(row["country"])
    assert countries_seen == EXPECTED_COUNTRIES


def test_asia_disclosure_country_rows_have_no_fake_urls():
    from scripts.ingestion.asia_disclosure_loader import (
        get_asia_disclosure_country_rows,
    )

    rows = get_asia_disclosure_country_rows()
    # The canonical rows ship blank URLs; if any non-blank URL is added in
    # the future it MUST be a real http(s) URL, never a fabricated string
    # like "example.com" or "TBD" or "<insert here>".
    placeholder_tokens = ("example.com", "TBD", "todo", "fake", "<", "?")
    for row in rows:
        url = row["source_url"]
        if not url:
            continue
        lower = url.lower()
        for bad in placeholder_tokens:
            assert bad not in lower, f"placeholder/fake URL detected: {url!r}"


def test_india_loader_remains_untouched():
    """India still has its own loader/source-family entry — Asia Disclosure
    work must not remove or weaken that path."""
    from scripts.live_source_registry import (
        get_source_family,
        ALL_SOURCE_KEYS,
    )

    assert "india" in ALL_SOURCE_KEYS
    india = get_source_family("india")
    assert india["adapter_status"] == "implemented"
    # India is its own family; its display name explicitly references
    # the regulators it covers (NSE/RBI/SEBI).
    assert "India" in india["display_name"] or "india" in india["display_name"].lower()


def test_asia_disclosure_source_family_remains_planned():
    """The source-health registry classification can remain planned/not
    scored — that is correct and honest until a real integration exists.
    Country-list configuration and source-health scoring are intentionally
    independent layers."""
    from scripts.live_source_registry import get_source_family

    family = get_source_family("asia_disclosure")
    assert family["adapter_status"] == "planned"
    assert family["tier"] == "planned"
