"""
Live-source registry integration tests for Kalshi.
"""
from __future__ import annotations

from scripts.live_source_registry import (
    ALL_SOURCE_KEYS,
    ADAPTER_PARTIAL,
    get_source_family,
    list_live_source_families,
)
from scripts.live_signal_filters import normalize_source_name


def test_kalshi_registered_after_polymarket():
    families = list_live_source_families()
    keys = [f["source_key"] for f in families]
    assert "kalshi" in keys
    assert "polymarket" in keys
    assert keys.index("kalshi") == keys.index("polymarket") + 1


def test_kalshi_registry_entry_advisory_only_and_no_execution():
    entry = get_source_family("kalshi")
    assert entry["display_name"] == "Kalshi"
    assert entry["advisory_only"] is True
    assert entry["can_execute"] is False
    assert entry["adapter_status"] == ADAPTER_PARTIAL
    # Kalshi loader is wired but no API key is required to run; the env
    # key is informational only.
    assert entry["requires_api_key"] is False
    assert "KALSHI_API_KEY" in entry["env_keys"]


def test_all_source_keys_includes_kalshi():
    assert "kalshi" in ALL_SOURCE_KEYS


def test_source_name_map_kalshi_label():
    assert normalize_source_name("kalshi") == "Kalshi"
    assert normalize_source_name("KALSHI") == "Kalshi"
    assert normalize_source_name(" Kalshi ") == "Kalshi"
