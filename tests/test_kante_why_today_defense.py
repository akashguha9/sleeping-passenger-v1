"""Tests — P6 Kanté defensive why-today scoring.

The Kanté adjustment is DEFENSIVE: it rewards covered names and punishes
price-only names with a live-news / mapping gap, and it NEVER unlocks execution.
  1. RHM.DE with price but no news/mapping cannot become executable.
  2. RHM.DE with price + fresh mapped news improves why_today.
  3. A static-universe candidate with a valid price is never executable.
  4. A non-L_today prior-only name is never executable.
  5. No trading/execution unlock.
"""
from __future__ import annotations

from scripts.why_today import (
    KANTE_COVERAGE_COMPLETE,
    KANTE_PRICE_CONFIRMED_WATCH,
    KANTE_WATCHLIST_DATA_INSUFFICIENT,
    executable_candidate,
    extended_why_today_kante,
    kante_candidate_classification,
    kante_why_today_adjustment,
)

BASE = 0.50


# --- adjustment math --------------------------------------------------------

def test_price_only_name_is_penalised():
    # Germany RHM.DE: valid price, but news_support=0 and mapping_support=0.
    adj = kante_why_today_adjustment(
        country_coverage=0,
        price_support=True,
        news_support=False,
        mapping_support=False,
        valid_price=True,
        provider_redundancy_score=0.0,
    )
    # -0.20 (news gap) - 0.20 (mapping gap) = -0.40
    assert adj == -0.40
    final = extended_why_today_kante(
        BASE, country_coverage=0, price_support=True,
        news_support=False, mapping_support=False, valid_price=True,
    )
    assert final == round(max(0.0, BASE - 0.40), 4)
    assert final < BASE  # price-only name is pushed DOWN


def test_covered_name_is_rewarded():
    adj = kante_why_today_adjustment(
        country_coverage=1,
        price_support=True,
        news_support=True,
        mapping_support=True,
        valid_price=True,
        provider_redundancy_score=0.6,
    )
    # +0.10 coverage + 0.05 redundancy, no penalties
    assert adj == 0.15
    final = extended_why_today_kante(
        BASE, country_coverage=1, price_support=True,
        news_support=True, mapping_support=True, valid_price=True,
        provider_redundancy_score=0.6,
    )
    assert final == round(BASE + 0.15, 4)
    assert final > BASE


def test_extension_is_clamped():
    assert extended_why_today_kante(0.95, country_coverage=1, price_support=True,
                                    news_support=True, mapping_support=True,
                                    valid_price=True, provider_redundancy_score=1.0) <= 1.0
    assert extended_why_today_kante(0.05, country_coverage=0, price_support=True,
                                    news_support=False, mapping_support=False) >= 0.0


# --- classification ---------------------------------------------------------

def test_price_only_classifies_watchlist_data_insufficient():
    cls = kante_candidate_classification(
        in_l_today=True, is_static_universe_only=False,
        price_support=True, news_support=False, mapping_support=False,
    )
    assert cls == KANTE_WATCHLIST_DATA_INSUFFICIENT


def test_price_and_news_but_no_mapping_is_watchlist():
    cls = kante_candidate_classification(
        in_l_today=True, is_static_universe_only=False,
        price_support=True, news_support=True, mapping_support=False,
    )
    assert cls == KANTE_WATCHLIST_DATA_INSUFFICIENT


def test_price_no_news_with_mapping_is_price_confirmed_watch():
    cls = kante_candidate_classification(
        in_l_today=True, is_static_universe_only=False,
        price_support=True, news_support=False, mapping_support=True,
    )
    assert cls == KANTE_PRICE_CONFIRMED_WATCH


def test_full_coverage_is_complete_candidate():
    cls = kante_candidate_classification(
        in_l_today=True, is_static_universe_only=False,
        price_support=True, news_support=True, mapping_support=True,
    )
    assert cls == KANTE_COVERAGE_COMPLETE


# --- hard guards: never executable ------------------------------------------

def test_price_only_rhm_not_executable():
    # Acceptance 1: price but no mapping -> mapping_confidence below theta and
    # country_coverage_confidence 0 -> not executable, regardless of why_today.
    assert (
        executable_candidate(
            why_today_score_value=1.0,
            source_health_score=1.0,
            valid_price=True,
            mapping_confidence=0.0,
            country_coverage_confidence=0.0,
            in_phantom_closed_sold=False,
            is_static_universe_only=False,
        )
        is False
    )


def test_static_candidate_with_price_never_executable():
    assert (
        executable_candidate(
            why_today_score_value=1.0,
            source_health_score=1.0,
            valid_price=True,
            mapping_confidence=1.0,
            country_coverage_confidence=1.0,
            in_phantom_closed_sold=False,
            is_static_universe_only=True,  # static -> hard False
        )
        is False
    )


def test_non_l_today_prior_only_not_executable():
    cls = kante_candidate_classification(
        in_l_today=False, is_static_universe_only=False,
        price_support=True, news_support=True, mapping_support=True,
    )
    assert cls == "MODEL_PRIOR_ONLY"


def test_full_coverage_rhm_may_be_executable_but_still_advisory():
    # Acceptance 2 corollary: with full coverage the gate MAY pass, but the
    # function still requires advisory_only + human_review_required (defaults).
    ok = executable_candidate(
        why_today_score_value=0.9,
        source_health_score=0.9,
        valid_price=True,
        mapping_confidence=0.85,
        country_coverage_confidence=1.0,
        in_phantom_closed_sold=False,
        is_static_universe_only=False,
    )
    assert ok is True
    # Removing the human-review invariant must flip it back to non-executable.
    assert (
        executable_candidate(
            why_today_score_value=0.9, source_health_score=0.9, valid_price=True,
            mapping_confidence=0.85, country_coverage_confidence=1.0,
            in_phantom_closed_sold=False, is_static_universe_only=False,
            human_review_required=False,
        )
        is False
    )
