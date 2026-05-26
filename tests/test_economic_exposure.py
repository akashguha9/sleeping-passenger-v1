"""Tests — economic-exposure normalization + theme bucket mapping.

Test group E (theme slots) — the ticker-side half.  The slot-accounting
side of group E lives in ``test_theme_slot_accounting.py``.
"""
from __future__ import annotations

from scripts.economic_exposure import (
    THEME_AI_SEMIS_CLOUD,
    THEME_CASH_OPTIONALITY,
    THEME_DEFENSE,
    THEME_ENERGY_MATERIALS,
    THEME_EUROPE_INDUSTRIALS,
    THEME_HIGH_BETA_SPECULATIVE,
    THEME_INDIA_LEVERAGED,
    THEME_MACRO_HEDGE,
    THEME_MEGA_CAP_PLATFORM,
    THEME_OTHER,
    detect_duplicate_economic_exposure,
    map_theme_buckets,
    normalize_economic_exposure,
    theme_caps,
)


# ---------------------------------------------------------------------------
# Test E.8 — EPA:AIR and ETR:AIR merge to AIRBUS
# ---------------------------------------------------------------------------


def test_airbus_listing_variants_merge_to_one_economic_exposure() -> None:
    for variant in ("EPA:AIR", "ETR:AIR", "AIR.PA", "AIR.DE", "AIR"):
        assert normalize_economic_exposure(variant) == "AIRBUS", variant


def test_alphabet_share_classes_merge() -> None:
    assert normalize_economic_exposure("NASDAQ:GOOGL") == "ALPHABET"
    assert normalize_economic_exposure("NASDAQ:GOOG") == "ALPHABET"
    assert normalize_economic_exposure("GOOGL") == "ALPHABET"
    assert normalize_economic_exposure("GOOG") == "ALPHABET"


def test_indian_listing_variants_merge() -> None:
    assert normalize_economic_exposure("NSE:HDFCBANK") == "HDFC_BANK"
    assert normalize_economic_exposure("HDFCBANK.NS") == "HDFC_BANK"
    assert normalize_economic_exposure("NSE:RELIANCE") == "RELIANCE_INDUSTRIES"
    assert normalize_economic_exposure("RELIANCE.NS") == "RELIANCE_INDUSTRIES"


def test_unknown_ticker_degrades_to_base_form() -> None:
    # Unknown tickers preserve the normalised base so duplicate
    # detection still works between two unregistered names.
    assert normalize_economic_exposure("UNK:NEWCO.PA") == "NEWCO"
    assert normalize_economic_exposure("NEWCO") == "NEWCO"


def test_empty_input_returns_empty_string() -> None:
    assert normalize_economic_exposure(None) == ""
    assert normalize_economic_exposure("") == ""
    assert normalize_economic_exposure("   ") == ""


# ---------------------------------------------------------------------------
# Test E.1..7 — theme bucket mapping
# ---------------------------------------------------------------------------


def test_amd_maps_to_ai_semis_cloud_and_high_beta() -> None:
    themes = map_theme_buckets("AMD")
    assert THEME_AI_SEMIS_CLOUD in themes
    assert THEME_HIGH_BETA_SPECULATIVE in themes


def test_avgo_maps_to_ai_semis_cloud() -> None:
    assert THEME_AI_SEMIS_CLOUD in map_theme_buckets("AVGO")


def test_nvda_maps_to_ai_semis_cloud() -> None:
    assert THEME_AI_SEMIS_CLOUD in map_theme_buckets("NVDA")


def test_googl_maps_to_mega_cap_and_ai() -> None:
    themes = map_theme_buckets("GOOGL")
    assert THEME_MEGA_CAP_PLATFORM in themes
    assert THEME_AI_SEMIS_CLOUD in themes


def test_amzn_maps_to_mega_cap_and_ai() -> None:
    themes = map_theme_buckets("AMZN")
    assert THEME_MEGA_CAP_PLATFORM in themes
    assert THEME_AI_SEMIS_CLOUD in themes


def test_gd_maps_to_defense() -> None:
    assert THEME_DEFENSE in map_theme_buckets("GD")


def test_defense_basket_all_map_to_defense() -> None:
    for ticker in ("NOC", "LMT", "RTX", "GD", "RHM.DE", "RHM"):
        themes = map_theme_buckets(ticker)
        assert THEME_DEFENSE in themes, ticker


def test_indian_leveraged_ticker_metadata_promotes_theme() -> None:
    themes = map_theme_buckets(
        "HDFCBANK.NS", {"country": "India", "leverage": 4}
    )
    assert THEME_INDIA_LEVERAGED in themes
    # 4x leverage also flags HIGH_BETA_SPECULATIVE for risk-budget weighting.
    assert THEME_HIGH_BETA_SPECULATIVE in themes


def test_unknown_ticker_with_no_metadata_falls_to_OTHER() -> None:
    assert map_theme_buckets("ZZZ_UNKNOWN") == [THEME_OTHER]


def test_unknown_ticker_with_country_metadata_picks_up_hint() -> None:
    themes = map_theme_buckets("ZZZ_UNKNOWN", {"country": "India"})
    assert THEME_INDIA_LEVERAGED in themes


def test_cash_maps_to_cash_optionality() -> None:
    assert THEME_CASH_OPTIONALITY in map_theme_buckets("CASH")
    assert THEME_CASH_OPTIONALITY in map_theme_buckets("SGOV")


def test_gld_maps_to_macro_hedge() -> None:
    assert THEME_MACRO_HEDGE in map_theme_buckets("GLD")


def test_shell_maps_to_energy_and_europe_industrials() -> None:
    themes = map_theme_buckets("SHEL")
    assert THEME_ENERGY_MATERIALS in themes
    assert THEME_EUROPE_INDUSTRIALS in themes


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def test_duplicate_economic_exposure_detected_across_listings() -> None:
    positions = [
        {"ticker": "EPA:AIR"},
        {"ticker": "ETR:AIR"},
        {"ticker": "NVDA"},
    ]
    dups = detect_duplicate_economic_exposure(positions)
    keys = {d["economic_exposure_key"] for d in dups}
    assert keys == {"AIRBUS"}
    assert dups[0]["duplicate_count"] == 2


def test_no_duplicates_returns_empty_list() -> None:
    positions = [{"ticker": "NVDA"}, {"ticker": "GOOGL"}]
    assert detect_duplicate_economic_exposure(positions) == []


# ---------------------------------------------------------------------------
# theme_caps sanity
# ---------------------------------------------------------------------------


def test_theme_caps_warning_under_hard() -> None:
    for theme in (
        THEME_AI_SEMIS_CLOUD,
        THEME_DEFENSE,
        THEME_INDIA_LEVERAGED,
        THEME_ENERGY_MATERIALS,
        THEME_EUROPE_INDUSTRIALS,
        THEME_HIGH_BETA_SPECULATIVE,
        THEME_MACRO_HEDGE,
    ):
        caps = theme_caps(theme)
        assert caps["warning_cap"] <= caps["hard_cap"], theme
        assert caps["hard_cap"] >= 1, theme
