"""Tests — deterministic news entity + country enrichment (P1).

Proves the 10 acceptance points: confident entities map to local tickers,
ambiguous/weak headline mentions never auto-map, null country is enriched from
the mapped ticker, unmapped rows are retained with a reason, and a deterministic
fixture lifts C_news / C_mapping above zero.
"""
from __future__ import annotations

import pytest

from scripts.news_entity_country_enrichment import (
    THETA_ENTITY,
    apply_news_enrichment,
    enrich_news_event,
)
from scripts.top30_country_coverage import build_country_coverage_from_payload
from scripts.discovery_baseline_metrics import compute_discovery_metrics


def _news(headline, summary="", **extra):
    row = {"headline": headline, "summary": summary, "freshness": "FRESH_TODAY",
           "is_live": True}
    row.update(extra)
    return row


# 1-4: confident entities map to the right local ticker + country -------------

@pytest.mark.parametrize(
    "headline,summary,ticker,country",
    [
        ("Toyota raises outlook", "Toyota Motor reported record profit", "7203.T", "Japan"),
        ("Rheinmetall wins defense order", "Rheinmetall shares jump", "RHM.DE", "Germany"),
        ("Reliance Industries posts profit", "Reliance gains on retail", "RELIANCE.NS", "India"),
        ("TSMC expands capacity", "TSMC raises capex; TSMC demand strong", "2330.TW", "Taiwan"),
    ],
)
def test_confident_news_entity_maps(headline, summary, ticker, country):
    enr = enrich_news_event(_news(headline, summary))
    assert enr["valid_news_mapping"] is True
    assert enr["ticker"] == ticker
    assert enr["country"] == country
    assert enr["entity_extraction_confidence"] >= THETA_ENTITY
    assert enr["mapping_confidence"] >= 0.70


# 5: ambiguous / common-word headline mention does not randomly map -----------

def test_shell_headline_only_does_not_map():
    enr = enrich_news_event(_news("Shell game roils the markets"))
    # A single bare headline mention scores 0.45 < 0.60 -> not a valid mapping.
    assert enr["valid_news_mapping"] is False
    assert enr["entity_extraction_confidence"] < THETA_ENTITY
    assert enr["mapping_failure_reason"] in {
        "INSUFFICIENT_ENTITY_CONFIDENCE", "NO_ENTITY"
    }


def test_two_distinct_strong_entities_are_ambiguous():
    enr = enrich_news_event(
        _news("Toyota and Sony announce joint venture",
              "Toyota and Sony will co-develop; Toyota and Sony deepen ties")
    )
    assert enr["valid_news_mapping"] is False
    assert enr["mapping_failure_reason"] == "AMBIGUOUS_ENTITY"
    assert enr["ticker"] is None


# 6: null country enriched from the mapped ticker -----------------------------

def test_null_country_enriched_from_ticker():
    enr = enrich_news_event(_news("Toyota raises outlook", "Toyota Motor profit"))
    assert enr["country"] == "Japan"
    assert enr["country_confidence"] >= 0.60
    assert enr["country_method"] in {"ticker_suffix", "mapped_ticker_country"}


# 7: weak / no-entity evidence stays UNKNOWN ----------------------------------

def test_weak_evidence_stays_unknown():
    enr = enrich_news_event(_news("markets moved sharply today"))
    assert enr["entity_name"] is None
    assert enr["country"] == "UNKNOWN"
    assert enr["country_confidence"] == 0.0
    assert enr["mapping_failure_reason"] == "NO_ENTITY"


# 8: unmapped rows are retained (never dropped) -------------------------------

def test_unmapped_news_row_is_retained_with_reason():
    event = _news("Shell game roils the markets")
    out = apply_news_enrichment(event)
    # The original row survives, no fabricated entity, reason recorded.
    assert out["headline"] == event["headline"]
    assert out.get("entity_name") in (None, "")
    assert out["valid_news_mapping"] is False
    assert out["news_mapping_failure_reason"]


# 9-10: deterministic fixture lifts C_news / C_mapping and mapped count -------

def _build_enriched_payload():
    raw_news = [
        _news("Toyota raises outlook", "Toyota Motor reported record profit"),
        _news("Rheinmetall wins defense order", "Rheinmetall shares jump"),
        _news("markets moved sharply today"),  # stays unmapped/UNKNOWN
    ]
    enriched = [apply_news_enrichment(n) for n in raw_news]
    payload = {
        "price_movers": {"movers": []},
        "news_events": {"events": enriched},
        "filings_events": {"events": []},
    }
    return raw_news, enriched, payload


def test_c_news_and_c_mapping_positive_on_fixture():
    _, enriched, payload = _build_enriched_payload()
    # Two enriched rows now carry a country; build a mapping-rows view from them.
    mapping_rows = [
        {"mapping_confidence": e.get("country_confidence", 0.0) and 0.85,
         "country": e["country"], "ticker": e.get("ticker")}
        for e in enriched if e.get("valid_news_mapping")
    ]
    cov = build_country_coverage_from_payload(
        payload, mapping_rows=mapping_rows, universe_records=[]
    )
    assert cov["ratios"]["C_news"] > 0.0
    assert cov["ratios"]["C_mapping"] > 0.0


def test_mapped_events_rise_after_enrichment():
    raw_news, enriched, _ = _build_enriched_payload()
    before = compute_discovery_metrics(
        {"price_movers": {"movers": []},
         "news_events": {"events": raw_news},
         "filings_events": {"events": []}}
    )["metrics"]
    after = compute_discovery_metrics(
        {"price_movers": {"movers": []},
         "news_events": {"events": enriched},
         "filings_events": {"events": []}}
    )["metrics"]
    assert after["mapped_events_count"] > before["mapped_events_count"]
    assert after["unmapped_events_count"] < before["unmapped_events_count"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
