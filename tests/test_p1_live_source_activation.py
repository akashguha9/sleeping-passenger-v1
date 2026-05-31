"""Tests — P1 live-source activation sprint.

Proves, deterministically and with NO API keys:
  1  expanded securities master loads (incl. Spain + Italy seed coverage)
  2  aliases resolve for 12 required non-US countries
  3  ambiguous alias is never silently resolved (AMBIGUOUS_ENTITY)
  4  unmapped event is retained with a mapping failure reason
  5  missing country is enriched from mapped ticker / exchange
  6  weak country evidence stays UNKNOWN
  7  UK/EU filings provider placeholder/unavailable state is honest
  8  no fake live status when a provider is unavailable
  9  static/fallback candidates remain non-executable
 10  advisory / no-execution invariants still hold
plus: alias normalization, enrich_country tiers, metrics aggregator shape.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.entity_ticker_mapper import (
    DEFAULT_THETA_MAP,
    _load_securities_master,
    _normalize_alias,
    map_event_to_tickers,
)
from scripts.top30_country_coverage import (
    COUNTRY_CONF_FLOOR,
    country_from_exchange,
    enrich_country,
)
from scripts.global_filings_loader import (
    STATUS_NOT_ACTIVE,
    STATUS_PROVIDER_NOT_CONFIGURED,
    available_filings_providers,
    describe_filings_provider,
    load_uk_eu_filings,
)


# --- 1. expanded securities master loads ----------------------------------

def test_expanded_master_loads_with_spain_and_italy():
    master = _load_securities_master(
        str(Path(__file__).resolve().parents[1] / "configs" / "global_securities_master.yaml")
    )
    countries = {sec["country"] for sec in master.symbol_index.values()}
    assert "Spain" in countries
    assert "Italy" in countries
    # seed coverage, not a token handful
    assert len(master.symbol_index) >= 50
    # new schema fields are parsed
    reliance = master.symbol_index.get("RELIANCE.NS")
    assert reliance is not None
    assert reliance["currency"] == "INR"
    assert reliance["local_ticker"] == "RELIANCE"


# --- 2. aliases resolve for the required non-US countries -----------------

_ALIAS_CASES = [
    ("Reliance", "RELIANCE.NS", "India"),
    ("Toyota", "7203.T", "Japan"),
    ("Samsung", "005930.KS", "South Korea"),
    ("Shell", "SHEL.L", "United Kingdom"),
    ("SAP", "SAP.DE", "Germany"),
    ("LVMH", "LVMH.PA", "France"),
    ("ASML", "ASML.AS", "Netherlands"),
    ("TSMC", "2330.TW", "Taiwan"),
    ("RBC", "RY.TO", "Canada"),
    ("BHP", "BHP.AX", "Australia"),
    ("Petrobras", "PETR4.SA", "Brazil"),
    ("DBS", "D05.SI", "Singapore"),
]


@pytest.mark.parametrize("alias,ticker,country", _ALIAS_CASES)
def test_alias_resolves_for_required_country(alias, ticker, country):
    rows = map_event_to_tickers({"entity_name": alias})
    best = rows[0]
    assert best["mapping_status"] == "MAPPED", f"{alias} did not map"
    assert best["ticker"] == ticker
    assert best["country"] == country
    assert best["mapping_method"] in {"alias_index", "alias_db", "securities_master_exact"}


def test_alias_with_event_country_clears_theta():
    # An exact alias hit corroborated by the event country must score >= theta.
    rows = map_event_to_tickers({"entity_name": "TSMC", "country": "TW"})
    assert rows[0]["ticker"] == "2330.TW"
    assert rows[0]["mapping_confidence"] >= DEFAULT_THETA_MAP


def test_abbreviation_alias_that_fuzzy_would_miss():
    # "RBC" shares no name prefix with "Royal Bank of Canada"; only the alias
    # index can resolve it deterministically.
    rows = map_event_to_tickers({"entity_name": "RBC", "country": "CA"})
    assert rows[0]["ticker"] == "RY.TO"
    assert rows[0]["mapping_status"] == "MAPPED"


# --- 3. ambiguous alias is never silently resolved ------------------------

def test_ambiguous_alias_not_silently_mapped(tmp_path):
    fixture = tmp_path / "sm.yaml"
    fixture.write_text(
        textwrap.dedent(
            """
            securities:
              - canonical_symbol: ACM1.L
                exchange_code: LSE
                country: GB
                name: Acme Industrials PLC
                aliases: [Acme]
              - canonical_symbol: ACM2.DE
                exchange_code: FSE
                country: DE
                name: Acme Technologies AG
                aliases: [Acme]
            """
        ),
        encoding="utf-8",
    )
    rows = map_event_to_tickers({"entity_name": "Acme"}, securities_master_path=fixture)
    assert rows[0]["mapping_status"] == "UNMAPPED"
    assert rows[0]["mapping_failure_reason"] == "AMBIGUOUS_ENTITY"
    assert rows[0]["ticker"] is None


def test_existing_fuzzy_ambiguity_still_flags_multiple():
    rows = map_event_to_tickers({"entity_name": "iShares"})
    assert rows[0]["mapping_status"] == "UNMAPPED"
    assert rows[0]["mapping_failure_reason"] == "MULTIPLE_LOW_CONFIDENCE_MATCHES"


# --- 4. unmapped event retained with a reason -----------------------------

def test_unmapped_event_retained_with_reason():
    rows = map_event_to_tickers({"entity_name": "Totally Unknown Private Co", "country": "DE"})
    assert len(rows) == 1
    assert rows[0]["mapping_status"] == "UNMAPPED"
    assert rows[0]["ticker"] is None
    assert rows[0]["mapping_failure_reason"]


# --- 5. missing country enriched from mapped ticker / exchange ------------

def test_missing_country_enriched_from_ticker_suffix():
    # No country on the event; the .NS suffix must supply India with high conf.
    rows = map_event_to_tickers({"ticker": "RELIANCE.NS"})
    best = rows[0]
    assert best["country"] == "India"
    assert best["country_confidence"] >= 0.85
    assert best["country_method"] in {"ticker_suffix", "mapped_ticker_country"}


def test_enrich_country_from_exchange():
    out = enrich_country({"exchange": "LSE"})
    assert out["country"] == "United Kingdom"
    assert out["country_method"] == "exchange_country"
    assert out["country_confidence"] == 0.75


def test_enrich_country_priority_explicit_wins():
    out = enrich_country({"country": "Germany", "ticker": "RELIANCE.NS"})
    assert out["country"] == "Germany"
    assert out["country_confidence"] == 1.0


def test_euronext_exchange_is_ambiguous_none():
    # Euronext spans several countries -> never attributed to one.
    assert country_from_exchange("Euronext") is None


# --- 6. weak country evidence stays UNKNOWN -------------------------------

def test_weak_country_evidence_stays_unknown():
    out = enrich_country({"url": "https://example.com/story", "language": "en"})
    assert out["country"] == "UNKNOWN"
    assert out["country_confidence"] == 0.0


def test_unmapped_row_with_weak_evidence_has_no_country():
    rows = map_event_to_tickers({"headline": "markets moved", "url": "https://news.com/x"})
    best = rows[0]
    assert best["mapping_failure_reason"] == "NO_ENTITY"
    assert best["country"] is None
    assert best["country_confidence"] == 0.0


def test_country_conf_floor_is_sane():
    assert 0.0 < COUNTRY_CONF_FLOOR <= 0.5


# --- 7/8. UK/EU provider honesty + no fake live ---------------------------

def test_uk_provider_unavailable_is_honest(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    ch = describe_filings_provider("companies_house")
    assert ch["status"] == STATUS_PROVIDER_NOT_CONFIGURED
    assert ch["requires_api_key"] is True
    assert ch["api_key_present"] is False
    assert ch["is_live"] is False


def test_keyless_provider_reports_not_active():
    fca = describe_filings_provider("fca_nsm")
    assert fca["status"] == STATUS_NOT_ACTIVE
    assert fca["is_live"] is False


def test_no_provider_reports_fake_live():
    for provider in available_filings_providers():
        assert provider["is_live"] is False, f"{provider['provider']} faked live"


def test_load_uk_eu_filings_emits_no_fabricated_rows():
    events, meta = load_uk_eu_filings()
    assert events == []
    assert meta["is_live"] is False
    assert meta["executable_allowed"] is False
    assert meta["source_health"] in {STATUS_NOT_ACTIVE, STATUS_PROVIDER_NOT_CONFIGURED}
    assert meta["diagnostics"]["fresh_row_count"] == 0


# --- 9. static/fallback candidates remain non-executable ------------------

def test_static_fallback_candidate_never_executable():
    from scripts.why_today import executable_candidate

    assert (
        executable_candidate(
            why_today_score_value=1.0,
            source_health_score=1.0,
            valid_price=True,
            mapping_confidence=1.0,
            country_coverage_confidence=1.0,
            in_phantom_closed_sold=False,
            is_static_universe_only=True,
        )
        is False
    )


# --- 10. advisory / no-execution invariants -------------------------------

def _assert_locked(safety: dict) -> None:
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["can_execute"] is False
    assert safety["broker_order_id"] == "NONE"
    assert safety["human_review_required"] is True


def test_filings_loader_safety_invariants():
    _, meta = load_uk_eu_filings()
    _assert_locked(meta["safety"])
    _assert_locked(describe_filings_provider("companies_house")["safety"])


def test_metrics_aggregator_safety_and_keys():
    from scripts.discovery_baseline_metrics import (
        REQUIRED_METRIC_KEYS,
        compute_discovery_metrics,
    )

    report = compute_discovery_metrics()
    assert report["baseline_available"] is False
    for key in REQUIRED_METRIC_KEYS:
        assert key in report["metrics"], f"missing metric {key}"
    _assert_locked(report["safety"])


# --- alias normalization unit ---------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Reliance Industries Limited", "reliance industries"),
        ("Toyota Motor Corp.", "toyota motor"),
        ("DBS Group Holdings Ltd", "dbs"),  # iterative multi-suffix strip
        ("SAP SE", "sap"),
        ("Banco Santander, S.A.", "banco santander s a"),
    ],
)
def test_normalize_alias_strips_suffixes(raw, expected):
    assert _normalize_alias(raw) == expected


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
