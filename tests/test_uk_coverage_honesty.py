"""Tests — P5 UK coverage honesty.

UK price support is real (Yahoo), but Companies House / RNS news+mapping are
absent unless configured. This proves the UK path stays HONEST:
  1. UK prices valid but no UK news/mapping -> coverage(UK)=0, readiness improves.
  2. Companies House / RNS provider-not-configured is reported honestly.
  3. No fake UK rows are fabricated.
  4. A fixture fresh UK news row (Shell) + price can lift coverage(UK)=1.
  5. A private/unlisted Companies House company never becomes tradable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.country_coverage_proof import build_proof_from_sqlite_bridge
from scripts.entity_ticker_mapper import map_event_to_tickers
from scripts.global_filings_loader import (
    STATUS_PROVIDER_NOT_CONFIGURED,
    describe_filings_provider,
    load_uk_eu_filings,
)
from scripts.persistence import insert_signal_event
from scripts.why_today import executable_candidate

NOW = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
FRESH_ISO = NOW.isoformat()


def _uk(proof):
    return next(r for r in proof["country_rows"] if r["country"] == "United Kingdom")


# --- 1: price-only UK is uncovered but readiness improves -------------------

def test_uk_price_only_is_uncovered_but_ready(tmp_path):
    db = tmp_path / "signals.db"  # no signal_events inserted
    proof = build_proof_from_sqlite_bridge(
        db,
        payload_dir=tmp_path / "dp",
        price_rows=[{"ticker": "SHEL.L", "country": "United Kingdom", "valid_price": True}],
        now_utc=NOW,
    )
    uk = _uk(proof)
    assert uk["universe_loaded"] == 1
    assert uk["price_support"] == 1
    assert uk["news_support"] == 0
    assert uk["mapping_support"] == 0
    assert uk["coverage"] == 0
    # readiness improves via price (universe 0.2 + price 0.2 = 0.4), not 0.
    assert uk["target_readiness"] >= 0.4
    assert "news_support" in uk["missing_layers"]
    assert "mapping_support" in uk["missing_layers"]


# --- 2 + 3: CH/RNS provider honesty, no fabricated rows ---------------------

def test_companies_house_not_configured_is_honest(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    ch = describe_filings_provider("companies_house")
    assert ch["status"] == STATUS_PROVIDER_NOT_CONFIGURED
    assert ch["is_live"] is False


def test_uk_eu_filings_emits_no_fabricated_rows():
    events, meta = load_uk_eu_filings()
    assert events == []
    assert meta["is_live"] is False
    assert meta["executable_allowed"] is False


# --- 4: fixture fresh UK news row lifts coverage -----------------------------

def test_fixture_uk_news_lifts_coverage(tmp_path):
    db = tmp_path / "signals.db"
    insert_signal_event(
        event_id="evt-shell-uk-1",
        source_name="gdelt",
        raw_payload={
            "title": "Shell reports record UK quarterly profit",
            "summary": "Shell plc lifted guidance today.",
            "published_at": FRESH_ISO,
            "country": "United Kingdom",
            "sourcecountry": "United Kingdom",
        },
        fetched_at=FRESH_ISO,
        db_path=db,
    )
    proof = build_proof_from_sqlite_bridge(
        db,
        payload_dir=tmp_path / "dp",
        price_rows=[{"ticker": "SHEL.L", "country": "United Kingdom", "valid_price": True}],
        now_utc=NOW,
    )
    uk = _uk(proof)
    assert uk["news_support"] == 1
    assert uk["mapping_support"] == 1
    assert uk["coverage"] == 1
    assert proof["C_global"] == round(1 / 30, 4)
    assert proof["first_covered_country"] == "United Kingdom"


# --- 5: a private/unlisted Companies House company is never tradable ---------

def test_private_companies_house_company_not_tradable():
    rows = map_event_to_tickers({"entity_name": "Tiny Private Holdings Ltd", "country": "GB"})
    best = rows[0]
    assert best["mapping_status"] == "UNMAPPED"
    assert best["ticker"] is None
    # Even if every other gate were green, an unmapped private co can't execute.
    assert (
        executable_candidate(
            why_today_score_value=1.0,
            source_health_score=1.0,
            valid_price=True,
            mapping_confidence=0.0,  # unmapped -> below theta
            country_coverage_confidence=0.0,
            in_phantom_closed_sold=False,
            is_static_universe_only=False,
        )
        is False
    )
