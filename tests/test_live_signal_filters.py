"""
Tests for scripts/live_signal_filters.py

Verifies:
- blocked Polymarket examples return allowed=False
- allowed Polymarket examples return allowed=True
- blocked terms win over allowed terms when both match
- normalize_source_name maps all backend variants to dashboard labels
- rejected Polymarket items produce None from _normalize_polymarket_record
- accepted items retain all advisory-only execution-lock fields
- source normalization covers every alias in _SOURCE_NAME_MAP
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# classify_market_domain — blocked examples
# ---------------------------------------------------------------------------

class TestBlockedMarkets:
    """Each title must return allowed=False."""

    @pytest.mark.parametrize("title", [
        "Will the Buffalo Sabres win the 2026 NHL Stanley Cup?",
        "New Rihanna Album before GTA VI?",
        "New Playboi Carti Album before GTA VI?",
        "Will Jesus Christ return before GTA VI?",
        "GTA VI released before June 2026?",
        "Will the Carolina Hurricanes win the 2026 NHL Stanley Cup?",
        "Will the Colorado Avalanche win the 2026 NHL Stanley Cup?",
        "Will the Vegas Golden Knights win the 2026 NHL Stanley Cup?",
        "Will the Minnesota Wild win the 2026 NHL Stanley Cup?",
        "Will the Philadelphia Flyers win the 2026 NHL Stanley Cup?",
        "Will the Anaheim Ducks win the 2026 NHL Stanley Cup?",
        "Will the Montreal Canadiens win the 2026 NHL Stanley Cup?",
    ])
    def test_blocked_market_is_rejected(self, title: str) -> None:
        from scripts.live_signal_filters import classify_market_domain

        result = classify_market_domain(title)
        assert result["allowed"] is False, (
            f"Expected blocked but got allowed=True for: {title!r}\n"
            f"  matched_terms={result['matched_terms']}\n"
            f"  blocked_terms={result['blocked_terms']}"
        )

    def test_blocked_domain_label(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Will the Buffalo Sabres win the 2026 NHL Stanley Cup?")
        assert r["domain"] == "blocked"
        assert r["blocked_terms"]  # at least one blocked term listed

    def test_nhl_blocked_terms_present(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Will the Minnesota Wild win the 2026 NHL Stanley Cup?")
        assert "nhl" in r["blocked_terms"] or "stanley cup" in r["blocked_terms"]

    def test_gta_blocked_terms_present(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("GTA VI released before June 2026?")
        blocked = r["blocked_terms"]
        assert any(t in blocked for t in ("gta vi", "gta"))

    def test_rihanna_blocked(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("New Rihanna Album before GTA VI?")
        assert r["allowed"] is False
        assert "rihanna" in r["blocked_terms"] or "album" in r["blocked_terms"]

    def test_jesus_christ_blocked(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Will Jesus Christ return before GTA VI?")
        assert r["allowed"] is False

    def test_playboi_carti_blocked(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("New Playboi Carti Album before GTA VI?")
        assert r["allowed"] is False
        assert "playboi carti" in r["blocked_terms"]


# ---------------------------------------------------------------------------
# classify_market_domain — allowed examples
# ---------------------------------------------------------------------------

class TestAllowedMarkets:
    """Each title must return allowed=True."""

    @pytest.mark.parametrize("title,expected_domain", [
        ("US x Iran permanent peace deal by end of 2026?", "geopolitics"),
        ("Will Trump visit China in Q3 2026?", "geopolitics"),
        ("Fed Decision in June?", "finance"),
        # "rate cut" maps to economy, which outranks finance in priority
        ("How many Fed rate cuts in 2026?", "economy"),
        ("What will WTI Crude Oil hit in May 2026?", "finance"),
        ("S&P 500 up or down on May 11?", "finance"),
        ("Strait of Hormuz traffic returns to normal by July 2026?", "geopolitics"),
        ("Will the U.S. invade Iran before 2027?", "geopolitics"),
        ("April Inflation US - Annual", "economy"),
        # "interest rate" maps to economy, which outranks finance (ecb)
        ("ECB Interest Rates: June 2026", "economy"),
        ("Bank of England decision in June?", "finance"),
        ("Will China invade Taiwan by end of 2026?", "geopolitics"),
        ("US obtains Iranian enriched uranium by end of 2026?", "geopolitics"),
        ("Will Iranian regime fall by June 30?", "geopolitics"),
        ("MicroStrategy sells any Bitcoin by end of May?", "finance"),
        ("Largest Company end of May?", "finance"),
        ("NVIDIA hit price target by June 2026?", "finance"),
        ("Coinbase hit price target by Q3 2026?", "finance"),
    ])
    def test_allowed_market(self, title: str, expected_domain: str) -> None:
        from scripts.live_signal_filters import classify_market_domain

        result = classify_market_domain(title)
        assert result["allowed"] is True, (
            f"Expected allowed but got allowed=False for: {title!r}\n"
            f"  matched_terms={result['matched_terms']}\n"
            f"  blocked_terms={result['blocked_terms']}\n"
            f"  reason={result['reason']}"
        )
        assert result["domain"] == expected_domain, (
            f"Wrong domain for {title!r}: got {result['domain']!r}, "
            f"expected {expected_domain!r}"
        )
        assert result["matched_terms"]
        assert result["blocked_terms"] == []

    def test_iran_matched_in_iranian(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Will Iranian regime fall by June 30?")
        assert r["allowed"] is True
        assert "iran" in r["matched_terms"]

    def test_enriched_uranium_matched(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("US obtains Iranian enriched uranium by end of 2026?")
        assert r["allowed"] is True
        assert "enriched uranium" in r["matched_terms"]

    def test_interest_rate_substring_in_plural(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("ECB Interest Rates: June 2026")
        assert r["allowed"] is True
        assert "interest rate" in r["matched_terms"] or "ecb" in r["matched_terms"]

    def test_microstrategy_bitcoin(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("MicroStrategy sells any Bitcoin by end of May?")
        assert r["allowed"] is True
        assert "bitcoin" in r["matched_terms"] or "microstrategy" in r["matched_terms"]

    def test_largest_company(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Largest Company end of May?")
        assert r["allowed"] is True
        assert "company" in r["matched_terms"]


# ---------------------------------------------------------------------------
# classify_market_domain — blocked wins over allowed
# ---------------------------------------------------------------------------

class TestBlockedWinsOverAllowed:
    def test_blocked_wins_when_both_match(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        # "war" is allowed (geopolitics), "sports" is blocked
        title = "War of the sports rivalries championship 2026"
        r = classify_market_domain(title)
        assert r["allowed"] is False
        assert r["domain"] == "blocked"

    def test_blocked_wins_oil_plus_nhl(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        # "oil" is allowed, "nhl" is blocked
        title = "NHL teams sponsor oil companies — who wins?"
        r = classify_market_domain(title)
        assert r["allowed"] is False
        assert "nhl" in r["blocked_terms"]

    def test_blocked_wins_trump_plus_oscars(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        # "trump" is allowed (politics), "oscars" is blocked
        title = "Will Trump appear at the Oscars 2026?"
        r = classify_market_domain(title)
        assert r["allowed"] is False
        assert "oscars" in r["blocked_terms"]

    def test_blocked_reason_text(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("NHL oil revenue deal 2026")
        assert "blocked term" in r["reason"]


# ---------------------------------------------------------------------------
# classify_market_domain — unknown / no match
# ---------------------------------------------------------------------------

class TestUnknownDomain:
    def test_random_question_no_match(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Will the weather be sunny in June?")
        assert r["allowed"] is False
        assert r["domain"] == "unknown"
        assert r["matched_terms"] == []
        assert r["blocked_terms"] == []

    def test_empty_title(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("")
        assert r["allowed"] is False
        assert r["domain"] == "unknown"

    def test_category_can_provide_match(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        # Title has no match but category "politics" allows it
        r = classify_market_domain("Will X happen?", category="politics")
        assert r["allowed"] is True
        assert r["domain"] == "politics"

    def test_tags_can_provide_match(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Will X happen?", tags=["inflation", "cpi"])
        assert r["allowed"] is True
        assert r["domain"] == "economy"

    def test_category_blocked_term_rejects(self) -> None:
        from scripts.live_signal_filters import classify_market_domain

        r = classify_market_domain("Market movements in Q2", category="nhl")
        assert r["allowed"] is False
        assert r["domain"] == "blocked"


# ---------------------------------------------------------------------------
# normalize_source_name
# ---------------------------------------------------------------------------

class TestNormalizeSourceName:
    """Every backend variant must map to the correct dashboard label."""

    @pytest.mark.parametrize("backend,expected", [
        ("polymarket", "Polymarket"),
        ("Polymarket", "Polymarket"),
        ("POLYMARKET", "Polymarket"),
        ("gdelt", "GDELT"),
        ("GDELT", "GDELT"),
        ("sec", "SEC EDGAR"),
        ("sec_edgar", "SEC EDGAR"),
        ("edgar", "SEC EDGAR"),
        ("SEC_EDGAR", "SEC EDGAR"),
        ("newsapi", "NewsAPI"),
        ("news_api", "NewsAPI"),
        ("NewsAPI", "NewsAPI"),
        ("eventregistry", "Event Registry"),
        ("event_registry", "Event Registry"),
        ("Event_Registry", "Event Registry"),
        ("etherscan", "Etherscan"),
        ("Etherscan", "Etherscan"),
        ("grok", "Grok/xAI"),
        ("xai", "Grok/xAI"),
        ("grok_xai", "Grok/xAI"),
        ("grok/xai", "Grok/xAI"),
        ("Grok/xAI", "Grok/xAI"),
        ("market_data", "Market Data"),
        ("Market_Data", "Market Data"),
        ("india", "India"),
        ("India", "India"),
        ("global_filings", "Global Filings"),
        ("Global_Filings", "Global Filings"),
        ("asia_disclosure", "Asia Disclosure"),
        ("Asia_Disclosure", "Asia Disclosure"),
    ])
    def test_normalize(self, backend: str, expected: str) -> None:
        from scripts.live_signal_filters import normalize_source_name

        assert normalize_source_name(backend) == expected

    def test_unknown_passthrough(self) -> None:
        from scripts.live_signal_filters import normalize_source_name

        assert normalize_source_name("my_custom_source") == "my_custom_source"

    def test_all_map_keys_resolve(self) -> None:
        from scripts.live_signal_filters import normalize_source_name, _SOURCE_NAME_MAP

        for k, v in _SOURCE_NAME_MAP.items():
            assert normalize_source_name(k) == v, f"Failed for key {k!r}"


# ---------------------------------------------------------------------------
# _normalize_polymarket_record — integration with domain gate
# ---------------------------------------------------------------------------

class TestPolymarketNormalizerGating:
    """_normalize_polymarket_record must return None for blocked markets."""

    def _rec(self, question: str, category: str = "", tags: list | None = None) -> dict:
        return {
            "market_id": "test-123",
            "question": question,
            "volume": 1000.0,
            "liquidity": 500.0,
            "end_date": "2026-12-31",
            "active": True,
            "category": category,
            "tags": tags or [],
            "description": "",
        }

    def test_blocked_market_returns_none(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        assert _normalize_polymarket_record(
            self._rec("Will the Buffalo Sabres win the 2026 NHL Stanley Cup?")
        ) is None

    def test_blocked_gta_returns_none(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        assert _normalize_polymarket_record(
            self._rec("GTA VI released before June 2026?")
        ) is None

    def test_blocked_rihanna_returns_none(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        assert _normalize_polymarket_record(
            self._rec("New Rihanna Album before GTA VI?")
        ) is None

    def test_allowed_market_returns_dict(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        result = _normalize_polymarket_record(
            self._rec("Fed Decision in June?")
        )
        assert result is not None
        assert isinstance(result, dict)

    def test_accepted_carries_advisory_fields(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        result = _normalize_polymarket_record(
            self._rec("Will China invade Taiwan by end of 2026?")
        )
        assert result is not None
        assert result["advisory_status"] == "ADVISORY_ONLY"
        assert result["human_review_required"] is True
        assert result["execution_gate"] == "LOCKED"
        assert result["ai_execution_count"] == 0

    def test_accepted_carries_domain_fields(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        result = _normalize_polymarket_record(
            self._rec("April Inflation US - Annual")
        )
        assert result is not None
        assert "domain" in result
        assert result["domain"] != "blocked"
        assert "matched_terms" in result
        assert result["matched_terms"]

    def test_accepted_source_name(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        result = _normalize_polymarket_record(self._rec("S&P 500 end of May level?"))
        assert result is not None
        assert result["source_name"] == "polymarket"

    def test_accepted_event_id_format(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        result = _normalize_polymarket_record(self._rec("Fed Decision in June?"))
        assert result is not None
        assert result["event_id"].startswith("polymarket_")

    def test_no_broker_fields_on_accepted(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        result = _normalize_polymarket_record(
            self._rec("S&P 500 up or down on May 11?")
        )
        assert result is not None
        forbidden = {"broker_order_id", "broker_api_called", "executed", "trade_id"}
        assert not forbidden & set(result.keys()), (
            f"Unexpected broker fields: {forbidden & set(result.keys())}"
        )

    def test_all_blocked_examples_return_none(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        blocked_titles = [
            "Will the Buffalo Sabres win the 2026 NHL Stanley Cup?",
            "New Rihanna Album before GTA VI?",
            "New Playboi Carti Album before GTA VI?",
            "Will Jesus Christ return before GTA VI?",
            "GTA VI released before June 2026?",
            "Will the Carolina Hurricanes win the 2026 NHL Stanley Cup?",
            "Will the Colorado Avalanche win the 2026 NHL Stanley Cup?",
            "Will the Vegas Golden Knights win the 2026 NHL Stanley Cup?",
            "Will the Minnesota Wild win the 2026 NHL Stanley Cup?",
            "Will the Philadelphia Flyers win the 2026 NHL Stanley Cup?",
            "Will the Anaheim Ducks win the 2026 NHL Stanley Cup?",
            "Will the Montreal Canadiens win the 2026 NHL Stanley Cup?",
        ]
        for title in blocked_titles:
            assert _normalize_polymarket_record(self._rec(title)) is None, (
                f"Expected None (blocked) but got a record for: {title!r}"
            )

    def test_all_allowed_examples_return_dict(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        allowed_titles = [
            "US x Iran permanent peace deal by end of 2026?",
            "Will Trump visit China in Q3 2026?",
            "Fed Decision in June?",
            "How many Fed rate cuts in 2026?",
            "What will WTI Crude Oil hit in May 2026?",
            "S&P 500 up or down on May 11?",
            "Strait of Hormuz traffic returns to normal by July 2026?",
            "Will the U.S. invade Iran before 2027?",
            "April Inflation US - Annual",
            "ECB Interest Rates: June 2026",
            "Bank of England decision in June?",
            "Will China invade Taiwan by end of 2026?",
            "US obtains Iranian enriched uranium by end of 2026?",
            "Will Iranian regime fall by June 30?",
            "MicroStrategy sells any Bitcoin by end of May?",
            "Largest Company end of May?",
            "NVIDIA hit price target by June 2026?",
            "Coinbase hit price target by Q3 2026?",
        ]
        for title in allowed_titles:
            result = _normalize_polymarket_record(self._rec(title))
            assert result is not None, (
                f"Expected a record (allowed) but got None for: {title!r}"
            )


# ---------------------------------------------------------------------------
# Missing API key diagnostic
# ---------------------------------------------------------------------------

class TestMissingKeyDiagnostic:
    """Ensure SourceRunResult carries status_detail and missing_env_var."""

    def test_source_run_result_has_diagnostic_fields(self) -> None:
        from scripts.live_source_runner import SourceRunResult

        s = SourceRunResult(
            source_name="newsapi",
            status="skipped",
            skipped_reason="NEWS_API_KEY missing",
            status_detail="MISSING_API_KEY",
            missing_env_var="NEWS_API_KEY",
        )
        assert s.status_detail == "MISSING_API_KEY"
        assert s.missing_env_var == "NEWS_API_KEY"

    def test_source_run_result_to_dict_includes_diagnostic(self) -> None:
        from scripts.live_source_runner import SourceRunResult

        d = SourceRunResult(
            source_name="etherscan",
            status="skipped",
            status_detail="MISSING_API_KEY",
            missing_env_var="ETHERSCAN_API_KEY",
        ).to_dict()
        assert "status_detail" in d
        assert "missing_env_var" in d
        assert d["missing_env_var"] == "ETHERSCAN_API_KEY"

    def test_source_run_result_accepted_rejected_counts(self) -> None:
        from scripts.live_source_runner import SourceRunResult

        s = SourceRunResult(
            source_name="polymarket",
            status="ok",
            fetched_count=100,
            accepted_count=42,
            rejected_count=58,
        )
        assert s.fetched_count == 100
        assert s.accepted_count == 42
        assert s.rejected_count == 58
        d = s.to_dict()
        assert d["accepted_count"] == 42
        assert d["rejected_count"] == 58


# ---------------------------------------------------------------------------
# Advisory contract — still enforced after gating changes
# ---------------------------------------------------------------------------

class TestAdvisoryContractUnchanged:
    def test_phase1_report_advisory_fields(self) -> None:
        from scripts.live_source_runner import Phase1RunReport

        r = Phase1RunReport(dry_run=True, run_at="t")
        assert r.advisory_status == "ADVISORY_ONLY"
        assert r.execution_gate == "LOCKED"
        assert r.ai_execution_count == 0
        assert r.human_review_required is True

    def test_no_broker_fields_in_phase1_report(self) -> None:
        from scripts.live_source_runner import Phase1RunReport

        d = Phase1RunReport(dry_run=True, run_at="t").to_dict()
        forbidden = {"trade_id", "broker_order_id", "executed", "order_id"}
        assert not forbidden & set(d.keys())

    def test_normalize_gdelt_advisory(self) -> None:
        from scripts.live_source_runner import _normalize_gdelt_record

        rec = {"url": "https://x.com/a", "title": "News", "seendate": "2026-05-09"}
        out = _normalize_gdelt_record(rec)
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["human_review_required"] is True
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0

    def test_normalize_sec_advisory(self) -> None:
        from scripts.live_source_runner import _normalize_sec_record

        rec = {"cik": "123", "form_type": "10-K", "filing_date": "2026-01-01",
               "accession_number": "001"}
        out = _normalize_sec_record(rec)
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0
