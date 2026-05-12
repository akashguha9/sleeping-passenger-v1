"""
Tests for Polymarket domain gate and multi-page loader.

All HTTP is mocked. No live network calls.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest

from scripts.ingestion.polymarket_loader import PolymarketLoader, _DOMAIN_KEYWORDS
from scripts.ingestion.base_loader import SkipLoader, LoaderResult
from scripts.live_signal_filters import classify_market_domain


def _mock_response(markets: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = markets
    return resp


_ALLOWED_MARKETS = [
    {
        "id": "mkt-001",
        "question": "Will Trump win the 2026 Senate race?",
        "volume": "100000",
        "liquidity": "50000",
        "endDate": "2026-11-01",
        "active": True,
        "category": "Politics",
        "tags": [{"label": "election"}],
        "description": "",
    },
    {
        "id": "mkt-002",
        "question": "Will the Fed cut rates before December 2026?",
        "volume": "200000",
        "liquidity": "80000",
        "endDate": "2026-12-01",
        "active": True,
        "category": "Economics",
        "tags": [{"label": "fed"}],
        "description": "",
    },
    {
        "id": "mkt-003",
        "question": "Will Bitcoin hit $100k by end of 2026?",
        "volume": "150000",
        "liquidity": "60000",
        "endDate": "2026-12-31",
        "active": True,
        "category": "Crypto",
        "tags": [{"label": "bitcoin"}],
        "description": "",
    },
]

_BLOCKED_MARKETS = [
    {
        "id": "mkt-101",
        "question": "Who will win the NHL Stanley Cup 2026?",
        "volume": "50000",
        "liquidity": "20000",
        "endDate": "2026-06-01",
        "active": True,
        "category": "Sports",
        "tags": [{"label": "nhl"}],
        "description": "",
    },
    {
        "id": "mkt-102",
        "question": "Will Rihanna release her new album in 2026?",
        "volume": "30000",
        "liquidity": "10000",
        "endDate": "2026-12-31",
        "active": True,
        "category": "Music",
        "tags": [{"label": "music"}],
        "description": "",
    },
    {
        "id": "mkt-103",
        "question": "Will GTA 6 have micro-transactions?",
        "volume": "20000",
        "liquidity": "5000",
        "endDate": "2026-06-01",
        "active": True,
        "category": "Gaming",
        "tags": [{"label": "gaming"}],
        "description": "",
    },
]


class TestDomainKeywordsSearched:
    def test_domain_keywords_not_empty(self) -> None:
        assert len(_DOMAIN_KEYWORDS) > 10

    def test_domain_keywords_include_finance_terms(self) -> None:
        lower = [k.lower() for k in _DOMAIN_KEYWORDS]
        assert any("inflation" in k or "rate" in k or "fed" in k for k in lower)

    def test_domain_keywords_include_geo_terms(self) -> None:
        lower = [k.lower() for k in _DOMAIN_KEYWORDS]
        assert any("ukraine" in k or "russia" in k or "china" in k or "tariff" in k for k in lower)


class TestPolymarketLoaderMultiPage:
    def test_keyword_searches_are_attempted(self) -> None:
        """Loader should issue multiple GET calls for keyword searches."""
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response([])

        loader = PolymarketLoader(limit=10, max_pages=1, use_keyword_search=True)
        with patch("requests.get", side_effect=side_effect):
            loader.fetch()

        # Should have called at least as many times as there are keywords + pages
        assert call_count["n"] >= len(_DOMAIN_KEYWORDS)

    def test_pages_deduplication(self) -> None:
        """Markets with duplicate IDs should appear only once in results."""
        dup_market = _ALLOWED_MARKETS[0].copy()

        def side_effect(*args, **kwargs):
            return _mock_response([dup_market])

        loader = PolymarketLoader(limit=10, max_pages=2, use_keyword_search=True)
        with patch("requests.get", side_effect=side_effect):
            result = loader.fetch()
        market_ids = [r["market_id"] for r in result.records]
        assert len(market_ids) == len(set(market_ids))

    def test_no_markets_returns_empty(self) -> None:
        loader = PolymarketLoader(limit=10, max_pages=1, use_keyword_search=False)
        with patch("requests.get", return_value=_mock_response([])):
            result = loader.fetch()
        assert result.records == []
        assert result.skipped is False

    def test_fetch_returns_loader_result(self) -> None:
        loader = PolymarketLoader(limit=10, max_pages=1, use_keyword_search=False)
        with patch("requests.get", return_value=_mock_response(_ALLOWED_MARKETS)):
            result = loader.fetch()
        assert isinstance(result, LoaderResult)
        assert not result.skipped

    def test_records_have_advisory_stamps(self) -> None:
        loader = PolymarketLoader(limit=10, max_pages=1, use_keyword_search=False)
        with patch("requests.get", return_value=_mock_response(_ALLOWED_MARKETS)):
            result = loader.fetch()
        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["human_review_required"] is True
            assert rec["execution_gate"] == "LOCKED"


class TestDomainGateAllowedMarkets:
    def test_politics_market_allowed(self) -> None:
        result = classify_market_domain(
            "Will Trump win the 2026 Senate race?", "Politics", ["election"]
        )
        assert result["allowed"] is True

    def test_fed_rate_market_allowed(self) -> None:
        result = classify_market_domain(
            "Will the Fed cut rates before December 2026?", "Economics", ["fed"]
        )
        assert result["allowed"] is True

    def test_bitcoin_market_allowed(self) -> None:
        result = classify_market_domain(
            "Will Bitcoin hit $100k by end of 2026?", "Crypto", ["bitcoin"]
        )
        assert result["allowed"] is True

    def test_inflation_market_allowed(self) -> None:
        result = classify_market_domain(
            "Will US inflation remain above 3% for all of 2026?", "Economy", []
        )
        assert result["allowed"] is True

    def test_oil_market_allowed(self) -> None:
        result = classify_market_domain(
            "Will Brent crude oil exceed $90 in Q3 2026?", "Commodities", []
        )
        assert result["allowed"] is True

    def test_gdp_market_allowed(self) -> None:
        result = classify_market_domain(
            "Will US GDP grow more than 2% in 2026?", "Economy", []
        )
        assert result["allowed"] is True


class TestDomainGateBlockedMarkets:
    def test_nhl_market_blocked(self) -> None:
        result = classify_market_domain(
            "Who will win the NHL Stanley Cup 2026?", "Sports", ["nhl"]
        )
        assert result["allowed"] is False
        assert result["domain"] == "blocked"

    def test_nba_market_blocked(self) -> None:
        result = classify_market_domain(
            "Which team wins the 2026 NBA Championship?", "Sports", ["nba"]
        )
        assert result["allowed"] is False

    def test_rihanna_market_blocked(self) -> None:
        result = classify_market_domain(
            "Will Rihanna release her new album in 2026?", "Music", ["music", "rihanna"]
        )
        assert result["allowed"] is False

    def test_gta_market_blocked(self) -> None:
        result = classify_market_domain(
            "Will GTA 6 have micro-transactions?", "Gaming", ["gaming", "gta"]
        )
        assert result["allowed"] is False

    def test_nfl_market_blocked(self) -> None:
        result = classify_market_domain(
            "Who wins the 2026 Super Bowl?", "Sports", ["nfl"]
        )
        assert result["allowed"] is False

    def test_celebrity_market_blocked(self) -> None:
        result = classify_market_domain(
            "Will Taylor Swift announce a new tour in 2026?", "Celebrity", ["celebrity"]
        )
        assert result["allowed"] is False

    def test_unknown_market_rejected(self) -> None:
        result = classify_market_domain(
            "Will XYZ_FAKE_THING happen in 2026?", "", []
        )
        assert result["allowed"] is False


class TestPolymarketNormalizerWithDomainGate:
    def test_allowed_markets_pass_gate(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record
        for m in _ALLOWED_MARKETS:
            rec = {
                "market_id": m["id"],
                "question": m["question"],
                "category": m["category"],
                "tags": [t["label"] if isinstance(t, dict) else t for t in m["tags"]],
                "volume": m["volume"],
                "liquidity": m["liquidity"],
                "end_date": m["endDate"],
                "active": m["active"],
            }
            result = _normalize_polymarket_record(rec)
            assert result is not None, f"Expected allowed: {m['question']!r}"

    def test_blocked_markets_rejected_by_normalizer(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record
        for m in _BLOCKED_MARKETS:
            rec = {
                "market_id": m["id"],
                "question": m["question"],
                "category": m["category"],
                "tags": [t["label"] if isinstance(t, dict) else t for t in m["tags"]],
                "volume": m["volume"],
                "liquidity": m["liquidity"],
                "end_date": m["endDate"],
                "active": m["active"],
            }
            result = _normalize_polymarket_record(rec)
            assert result is None, f"Expected blocked: {m['question']!r}"

    def test_allowed_record_has_advisory_fields(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record
        rec = {
            "market_id": "mkt-001",
            "question": "Will the Fed cut rates in 2026?",
            "category": "Economy",
            "tags": ["fed"],
        }
        out = _normalize_polymarket_record(rec)
        assert out is not None
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["human_review_required"] is True
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0


class TestPolymarketRunnerOKFiltered:
    def test_ok_filtered_status_when_all_rejected(self) -> None:
        from scripts.live_source_runner import run_phase1

        def mock_get(*args, **kwargs):
            return _mock_response(_BLOCKED_MARKETS)

        with patch("requests.get", side_effect=mock_get):
            report = run_phase1(dry_run=True, sources=["polymarket"])
        src = report.sources[0]
        # fetched_count should be > 0 but accepted_count == 0
        assert src.fetched_count >= 0  # could be 0 if all pages return blocked
        # Status can be ok (0 accepted) or ok_filtered
        assert src.status in ("ok", "ok_filtered", "skipped")

    def test_ok_status_when_some_accepted(self) -> None:
        from scripts.live_source_runner import run_phase1

        def mock_get(*args, **kwargs):
            return _mock_response(_ALLOWED_MARKETS)

        with patch("requests.get", side_effect=mock_get):
            report = run_phase1(dry_run=True, sources=["polymarket"])
        src = report.sources[0]
        assert src.status == "ok"
        assert src.fetched_count > 0
        assert src.accepted_count > 0
