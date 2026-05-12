"""
Comprehensive hardening tests for all fixed live source loaders.

Coverage
--------
- Polymarket allow/block domain gate
- Status semantics: OK, OK_FILTERED, SKIPPED, RATE_LIMITED, TIMEOUT, PLACEHOLDER, HTTP_ERROR
- SEC EDGAR missing CIK → clean SKIPPED
- Etherscan placeholder/malformed address rejection
- Grok/xAI XAI_MODEL env var, 400 handling, model fallback
- GDELT 429 → RATE_LIMITED, timeout → TIMEOUT
- Global Filings all-placeholder → PLACEHOLDER
- Asia Disclosure all-placeholder → PLACEHOLDER
- Safety invariants (advisory_status, execution_gate, human_review_required)
- No broker/order/private-key logic

All tests are zero-network — HTTP mocked via unittest.mock.patch.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(payload: object, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    resp.raise_for_status.return_value = None
    return resp


def _mock_http_error(status_code: int, message: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = message
    from requests.exceptions import HTTPError
    resp.raise_for_status.side_effect = HTTPError(f"{status_code} {message}")
    return resp


# ============================================================================
# 1. Polymarket domain gate — allow / block
# ============================================================================


class TestPolymarketDomainGate:
    """Tests that the classify_market_domain filter correctly gates markets."""

    def _classify(self, title, category=None, tags=None):
        from scripts.live_signal_filters import classify_market_domain
        return classify_market_domain(title, category, tags)

    # --- Allowed examples ---
    def test_inflation_market_allowed(self):
        r = self._classify("Will US inflation exceed 3% in 2026?")
        assert r["allowed"] is True
        assert r["domain"] in ("economy", "finance")

    def test_fed_rate_cut_allowed(self):
        r = self._classify("Will the Fed cut rates at the March 2026 FOMC?")
        assert r["allowed"] is True

    def test_election_market_allowed(self):
        r = self._classify("Who will win the 2026 US Senate election?")
        assert r["allowed"] is True
        assert r["domain"] == "politics"

    def test_bitcoin_market_allowed(self):
        r = self._classify("Will Bitcoin exceed $100k by end of 2026?")
        assert r["allowed"] is True

    def test_ukraine_war_market_allowed(self):
        r = self._classify("Will Ukraine-Russia ceasefire be signed in 2026?")
        assert r["allowed"] is True
        assert r["domain"] == "geopolitics"

    def test_trump_market_allowed(self):
        r = self._classify("Will Trump sign a new tariff bill?")
        assert r["allowed"] is True

    def test_sanctions_market_allowed(self):
        r = self._classify("Will new sanctions on Iran be imposed?")
        assert r["allowed"] is True

    def test_treasury_yields_allowed(self):
        r = self._classify("Will 10-year Treasury yields exceed 5%?")
        assert r["allowed"] is True

    def test_spx_market_allowed(self):
        r = self._classify("Will the S&P 500 hit 6000 by year end?")
        assert r["allowed"] is True

    # --- Blocked examples ---
    def test_nba_market_blocked(self):
        r = self._classify("Who will win the 2026 NBA Championship?")
        assert r["allowed"] is False
        assert r["domain"] == "blocked"

    def test_nhl_market_blocked(self):
        r = self._classify("Which team wins the Stanley Cup?")
        assert r["allowed"] is False

    def test_rihanna_market_blocked(self):
        r = self._classify("Will Rihanna release a new album in 2026?")
        assert r["allowed"] is False

    def test_gta_market_blocked(self):
        r = self._classify("When will GTA VI release?")
        assert r["allowed"] is False

    def test_oscar_market_blocked(self):
        r = self._classify("Who will win the Oscar for Best Picture?")
        assert r["allowed"] is False

    def test_formula1_market_blocked(self):
        r = self._classify("Who wins the F1 championship?")
        assert r["allowed"] is False

    def test_soccer_market_blocked(self):
        r = self._classify("Will Spain win the Soccer World Cup?")
        assert r["allowed"] is False

    def test_nfl_market_blocked(self):
        r = self._classify("Super Bowl winner 2026 NFL?")
        assert r["allowed"] is False

    def test_meme_market_blocked(self):
        r = self._classify("Jesus Christ is rising again meme market")
        assert r["allowed"] is False

    # --- Unknown (no match) ---
    def test_empty_title_unknown(self):
        r = self._classify("")
        assert r["allowed"] is False

    def test_unrelated_title_unknown(self):
        r = self._classify("Random unrelated statement about cats and dogs")
        assert r["allowed"] is False
        assert r["domain"] == "unknown"

    # --- Normalization roundtrip ---
    def test_normalize_polymarket_allowed_returns_dict(self):
        from scripts.live_source_runner import _normalize_polymarket_record
        rec = {
            "market_id": "abc",
            "question": "Will the Fed cut rates in 2026?",
            "volume": 1000.0,
        }
        out = _normalize_polymarket_record(rec)
        assert out is not None
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["execution_gate"] == "LOCKED"
        assert out["human_review_required"] is True
        assert out["ai_execution_count"] == 0

    def test_normalize_polymarket_blocked_returns_none(self):
        from scripts.live_source_runner import _normalize_polymarket_record
        rec = {
            "market_id": "nba-001",
            "question": "Who wins the 2026 NBA Finals?",
        }
        assert _normalize_polymarket_record(rec) is None

    def test_ok_filtered_status_when_all_rejected(self):
        """Runner returns ok_filtered when Polymarket source works but all markets blocked."""
        blocked_markets = [
            {"id": "s1", "question": "Who wins the 2026 NBA Finals?", "active": True},
            {"id": "s2", "question": "Will Rihanna release an album?", "active": True},
        ]
        from scripts.ingestion.base_loader import SkipLoader
        with patch("requests.get", return_value=_mock_resp(blocked_markets)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True, sources=["polymarket"])

        poly = next(s for s in report.sources if s.source_name == "polymarket")
        assert poly.status == "ok_filtered"
        assert poly.fetched_count == 2
        assert poly.rejected_count == 2
        assert poly.accepted_count == 0

    def test_ok_status_when_some_allowed(self):
        """Runner returns ok when at least some markets are allowed."""
        markets = [
            {"id": "e1", "question": "Will Fed cut rates?", "active": True},
            {"id": "s2", "question": "Who wins NBA Finals?", "active": True},
        ]
        from scripts.ingestion.base_loader import SkipLoader
        with patch("requests.get", return_value=_mock_resp(markets)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True, sources=["polymarket"])

        poly = next(s for s in report.sources if s.source_name == "polymarket")
        assert poly.status == "ok"
        assert poly.accepted_count >= 1
        assert poly.rejected_count >= 1


# ============================================================================
# 2. Status semantics
# ============================================================================


class TestStatusSemantics:
    """Verify the new canonical status values from runners."""

    def test_gdelt_429_yields_rate_limited(self):
        from scripts.ingestion.gdelt_loader import GDELTLoader
        resp = _mock_http_error(429, "rate limited")
        resp.status_code = 429
        resp.raise_for_status.return_value = None  # don't raise — we check status code
        loader = GDELTLoader()
        with patch("requests.get", return_value=resp):
            result = loader.safe_fetch()
        assert result.skipped is True
        assert "[RATE_LIMITED]" in result.skip_reason

    def test_gdelt_timeout_yields_timeout_status(self):
        import requests as req_module
        from scripts.ingestion.gdelt_loader import GDELTLoader
        loader = GDELTLoader()
        with patch("requests.get", side_effect=req_module.exceptions.Timeout("timed out")):
            result = loader.safe_fetch()
        assert result.skipped is True
        assert "[TIMEOUT]" in result.skip_reason

    def test_phase1_runner_rate_limited_status(self):
        from scripts.ingestion.base_loader import SkipLoader
        from scripts.ingestion.gdelt_loader import GDELTLoader

        def fake_fetch(self):
            from scripts.ingestion.base_loader import SkipLoader as SL
            raise SL("[RATE_LIMITED] GDELT API returned 429")

        from scripts.live_source_runner import run_phase1
        with patch.object(GDELTLoader, "fetch", fake_fetch):
            with (
                patch("scripts.ingestion.polymarket_loader.PolymarketLoader.fetch",
                      side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch",
                      side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True, sources=["gdelt"])

        gdelt = next(s for s in report.sources if s.source_name == "gdelt")
        assert gdelt.status == "rate_limited"

    def test_phase1_runner_timeout_status(self):
        from scripts.ingestion.base_loader import SkipLoader
        from scripts.ingestion.gdelt_loader import GDELTLoader

        def fake_fetch(self):
            from scripts.ingestion.base_loader import SkipLoader as SL
            raise SL("[TIMEOUT] GDELT API timed out after 15s")

        from scripts.live_source_runner import run_phase1
        with patch.object(GDELTLoader, "fetch", fake_fetch):
            with (
                patch("scripts.ingestion.polymarket_loader.PolymarketLoader.fetch",
                      side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch",
                      side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True, sources=["gdelt"])

        gdelt = next(s for s in report.sources if s.source_name == "gdelt")
        assert gdelt.status == "timeout"

    def test_phase2_runner_rate_limited_status(self):
        from scripts.ingestion.base_loader import SkipLoader
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        def fake_fetch(self):
            from scripts.ingestion.base_loader import SkipLoader as SL
            raise SL("[RATE_LIMITED] NewsAPI 429")

        from scripts.live_source_runner_phase2 import run_phase2
        with patch.object(NewsAPILoader, "fetch", fake_fetch):
            report = run_phase2(dry_run=True, sources=["newsapi"])

        src = next(s for s in report.sources if s.source_name == "newsapi")
        assert src.status == "rate_limited"

    def test_global_filings_placeholder_status(self):
        """All placeholder providers → placeholder status."""
        from scripts.ingestion.base_loader import SkipLoader
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        from scripts.live_source_runner_phase2 import run_phase2
        with patch.object(GlobalFilingsLoader, "fetch", side_effect=SkipLoader("[PLACEHOLDER] all providers inactive")):
            report = run_phase2(dry_run=True, sources=["global_filings"])
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        assert gf.status == "placeholder"

    def test_asia_disclosure_placeholder_status(self):
        """All providers inactive → placeholder status."""
        from scripts.live_source_runner_phase2 import run_phase2
        report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        assert asia.status == "placeholder"


# ============================================================================
# 3. SEC EDGAR — missing CIK
# ============================================================================


class TestSECEdgarMissingCIK:
    def test_skip_when_no_cik(self):
        os.environ["SEC_USER_AGENT"] = "TestAgent test@example.com"
        try:
            from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
            loader = SECEdgarLoader(cik=None)
            result = loader.safe_fetch()
            assert result.skipped is True
            assert "No CIK" in result.skip_reason or "no cik" in result.skip_reason.lower()
        finally:
            os.environ.pop("SEC_USER_AGENT", None)

    def test_skip_reason_mentions_cik(self):
        os.environ["SEC_USER_AGENT"] = "TestAgent test@example.com"
        try:
            from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
            loader = SECEdgarLoader(cik=None)
            result = loader.safe_fetch()
            assert "cik" in result.skip_reason.lower()
        finally:
            os.environ.pop("SEC_USER_AGENT", None)

    def test_does_not_call_http_when_no_cik(self):
        os.environ["SEC_USER_AGENT"] = "TestAgent test@example.com"
        try:
            from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
            loader = SECEdgarLoader(cik=None)
            with patch("requests.get") as mock_get:
                loader.safe_fetch()
                mock_get.assert_not_called()
        finally:
            os.environ.pop("SEC_USER_AGENT", None)

    def test_runner_phase1_sec_skipped_without_cik(self):
        os.environ["SEC_USER_AGENT"] = "TestAgent test@example.com"
        try:
            from scripts.ingestion.base_loader import SkipLoader
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.polymarket_loader.PolymarketLoader.fetch",
                      side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch",
                      side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True, sources=["sec_edgar"], sec_cik=None)
            sec = next(s for s in report.sources if s.source_name == "sec_edgar")
            assert sec.status == "skipped"
            assert sec.fetched_count == 0
        finally:
            os.environ.pop("SEC_USER_AGENT", None)

    def test_skip_without_user_agent(self):
        os.environ.pop("SEC_USER_AGENT", None)
        from scripts.ingestion.sec_edgar_loader import SECEdgarLoader
        loader = SECEdgarLoader(cik="0000320193")
        result = loader.safe_fetch()
        assert result.skipped is True


# ============================================================================
# 4. Etherscan address validation
# ============================================================================


class TestEtherscanAddressValidation:
    def _set_key(self):
        os.environ["ETHERSCAN_API_KEY"] = "test-key-123"

    def _clear_key(self):
        os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_placeholder_address_rejected(self):
        self._set_key()
        try:
            from scripts.ingestion.etherscan_loader import EtherscanLoader
            loader = EtherscanLoader(address="0xYOUR_PUBLIC_ETH_ADDRESS")
            result = loader.safe_fetch()
            assert result.skipped is True
            assert "placeholder" in result.skip_reason.lower()
        finally:
            self._clear_key()

    def test_malformed_address_rejected(self):
        self._set_key()
        try:
            from scripts.ingestion.etherscan_loader import EtherscanLoader
            loader = EtherscanLoader(address="notanaddress")
            result = loader.safe_fetch()
            assert result.skipped is True
            assert "malformed" in result.skip_reason.lower()
        finally:
            self._clear_key()

    def test_too_short_address_rejected(self):
        self._set_key()
        try:
            from scripts.ingestion.etherscan_loader import EtherscanLoader
            loader = EtherscanLoader(address="0xdeadbeef")
            result = loader.safe_fetch()
            assert result.skipped is True
        finally:
            self._clear_key()

    def test_valid_address_accepted(self):
        self._set_key()
        try:
            from scripts.ingestion.etherscan_loader import EtherscanLoader
            valid_addr = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"
            loader = EtherscanLoader(address=valid_addr)
            payload = {"status": "1", "message": "OK", "result": []}
            with patch("requests.get", return_value=_mock_resp(payload)):
                result = loader.safe_fetch()
            assert not result.skipped
        finally:
            self._clear_key()

    def test_no_address_skips_cleanly(self):
        self._set_key()
        try:
            from scripts.ingestion.etherscan_loader import EtherscanLoader
            loader = EtherscanLoader(address=None)
            result = loader.safe_fetch()
            assert result.skipped is True
            assert "address" in result.skip_reason.lower()
        finally:
            self._clear_key()

    def test_validate_eth_address_helper(self):
        from scripts.ingestion.etherscan_loader import _validate_eth_address
        assert _validate_eth_address("0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae") is None
        assert _validate_eth_address("0xYOUR_PUBLIC_ETH_ADDRESS") is not None
        assert _validate_eth_address("not_an_address") is not None
        assert _validate_eth_address("0x" + "a" * 39) is not None  # 1 char short
        assert _validate_eth_address("0x" + "a" * 40) is None     # exactly right


# ============================================================================
# 5. Grok/xAI fixes
# ============================================================================


class TestGrokFixes:
    _GROK_RESPONSE = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "interpreted_topic": "Rate policy",
                        "narrative_frame": "Higher for longer",
                        "contradiction_flags": [],
                        "confidence_score": 0.75,
                        "summary_text": "Markets pricing in extended high rates.",
                    }),
                }
            }
        ]
    }

    def test_default_model_is_grok_3_mini(self):
        from scripts.ingestion.grok_interpreter import _DEFAULT_MODEL
        assert _DEFAULT_MODEL == "grok-3-mini"

    def test_xai_model_env_var_used(self):
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["model"] = (json or {}).get("model")
            return _mock_resp(self._GROK_RESPONSE)

        with patch.dict(os.environ, {"XAI_API_KEY": "test-k", "XAI_MODEL": "grok-2-latest"}):
            with patch("requests.post", side_effect=fake_post):
                gi = GrokInterpreter()
                gi.fetch()

        assert captured.get("model") == "grok-2-latest"

    def test_constructor_model_used_when_no_env_model(self):
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["model"] = (json or {}).get("model")
            return _mock_resp(self._GROK_RESPONSE)

        with patch.dict(os.environ, {"XAI_API_KEY": "test-k"}, clear=False):
            os.environ.pop("XAI_MODEL", None)
            with patch("requests.post", side_effect=fake_post):
                gi = GrokInterpreter(model="grok-custom-model")
                gi.fetch()

        assert captured.get("model") == "grok-custom-model"

    def test_400_bad_request_raises_skip_loader(self):
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import SkipLoader

        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.text = '{"error": "invalid model"}'
        bad_resp.raise_for_status.return_value = None

        with patch.dict(os.environ, {"XAI_API_KEY": "test-k"}):
            with patch("requests.post", return_value=bad_resp):
                gi = GrokInterpreter()
                with pytest.raises(SkipLoader) as exc:
                    gi.fetch()
                # Should mention 400 but NOT expose the API key
                assert "400" in str(exc.value)
                assert "test-k" not in str(exc.value)

    def test_400_response_body_sanitized_no_key(self):
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import SkipLoader

        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.text = '{"error": "bad model name"}'
        bad_resp.raise_for_status.return_value = None

        api_key = "SUPERSECRET_KEY_NEVER_EXPOSE"
        with patch.dict(os.environ, {"XAI_API_KEY": api_key}):
            with patch("requests.post", return_value=bad_resp):
                gi = GrokInterpreter()
                try:
                    gi.fetch()
                except SkipLoader as exc:
                    assert api_key not in str(exc)

    def test_grok_timeout_raises_skip_loader(self):
        import requests as req_module
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import SkipLoader

        with patch.dict(os.environ, {"XAI_API_KEY": "test-k"}):
            with patch("requests.post", side_effect=req_module.exceptions.Timeout("timeout")):
                gi = GrokInterpreter()
                result = gi.safe_fetch()
                assert result.skipped is True
                assert "[TIMEOUT]" in result.skip_reason

    def test_grok_payload_has_messages(self):
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["payload"] = json
            return _mock_resp(self._GROK_RESPONSE)

        with patch.dict(os.environ, {"XAI_API_KEY": "test-k"}):
            with patch("requests.post", side_effect=fake_post):
                gi = GrokInterpreter()
                gi.fetch()

        assert "messages" in captured["payload"]
        messages = captured["payload"]["messages"]
        assert isinstance(messages, list)
        assert len(messages) >= 2
        roles = {m["role"] for m in messages}
        assert "system" in roles
        assert "user" in roles


# ============================================================================
# 6. GDELT rate limiting and timeout
# ============================================================================


class TestGDELTRobustness:
    def test_429_response_returns_rate_limited_reason(self):
        from scripts.ingestion.gdelt_loader import GDELTLoader
        resp = MagicMock()
        resp.status_code = 429
        resp.raise_for_status.return_value = None
        with patch("requests.get", return_value=resp):
            result = GDELTLoader().safe_fetch()
        assert result.skipped is True
        assert "[RATE_LIMITED]" in result.skip_reason

    def test_timeout_returns_timeout_reason(self):
        import requests as req_module
        from scripts.ingestion.gdelt_loader import GDELTLoader
        with patch("requests.get", side_effect=req_module.exceptions.Timeout("too slow")):
            result = GDELTLoader().safe_fetch()
        assert result.skipped is True
        assert "[TIMEOUT]" in result.skip_reason

    def test_network_error_not_rate_limited(self):
        from scripts.ingestion.gdelt_loader import GDELTLoader
        with patch("requests.get", side_effect=Exception("network unreachable")):
            result = GDELTLoader().safe_fetch()
        assert result.skipped is True
        assert "[RATE_LIMITED]" not in result.skip_reason
        assert "[TIMEOUT]" not in result.skip_reason
        assert "unreachable" in result.skip_reason.lower()

    def test_200_response_returns_articles(self):
        from scripts.ingestion.gdelt_loader import GDELTLoader
        payload = {
            "articles": [
                {"url": "https://ex.com/1", "title": "Inflation rises", "seendate": "2026-05-10",
                 "domain": "ex.com", "language": "English", "sourcecountry": "US"},
            ]
        }
        with patch("requests.get", return_value=_mock_resp(payload)):
            result = GDELTLoader().safe_fetch()
        assert not result.skipped
        assert len(result.records) == 1


# ============================================================================
# 7. Global Filings — all placeholder
# ============================================================================


class TestGlobalFilingsPlaceholder:
    def test_all_providers_inactive(self):
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader, _PROVIDER_CONFIGS
        # sec_efts is the only active provider; all others should be inactive placeholders
        for name, conf in _PROVIDER_CONFIGS.items():
            if name == "sec_efts":
                assert conf["active"] is True, f"Provider 'sec_efts' should be active"
            else:
                assert conf["active"] is False, f"Provider {name!r} should be inactive (placeholder)"

    def test_loader_skips_with_placeholder_reason(self):
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        loader = GlobalFilingsLoader(providers=["hkex"])
        result = loader.safe_fetch()
        assert result.skipped is True
        assert "placeholder" in result.skip_reason.lower()

    def test_asx_inactive(self):
        from scripts.ingestion.global_filings_loader import _PROVIDER_CONFIGS
        assert _PROVIDER_CONFIGS["asx"]["active"] is False

    def test_runner_reports_placeholder_status(self):
        from scripts.ingestion.base_loader import SkipLoader
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        from scripts.live_source_runner_phase2 import run_phase2
        with patch.object(GlobalFilingsLoader, "fetch", side_effect=SkipLoader("[PLACEHOLDER] all providers inactive")):
            report = run_phase2(dry_run=True, sources=["global_filings"])
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        assert gf.status == "placeholder"

    def test_au_region_no_active_providers(self):
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        loader = GlobalFilingsLoader(region="AU")
        result = loader.safe_fetch()
        assert result.skipped is True


# ============================================================================
# 8. Asia Disclosure — all placeholder
# ============================================================================


class TestAsiaDisclosurePlaceholder:
    def test_all_providers_inactive(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader, _PROVIDER_CONFIGS
        for name, conf in _PROVIDER_CONFIGS.items():
            assert conf["active"] is False, f"Asia provider {name!r} should be inactive"

    def test_loader_skips_with_placeholder_reason(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader()
        result = loader.safe_fetch()
        assert result.skipped is True
        assert "placeholder" in result.skip_reason.lower()

    def test_runner_reports_placeholder_status(self):
        from scripts.live_source_runner_phase2 import run_phase2
        report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        assert asia.status == "placeholder"


# ============================================================================
# 9. Safety invariants on every normalized record
# ============================================================================


class TestSafetyInvariants:
    _REQUIRED = {
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "human_review_required": True,
        "ai_execution_count": 0,
    }

    def _check(self, rec: dict) -> None:
        for field, expected in self._REQUIRED.items():
            assert rec.get(field) == expected, (
                f"{field} should be {expected!r}, got {rec.get(field)!r}"
            )
        # Must not contain broker / order / execution fields
        forbidden = {"place_order", "execute_trade", "private_key", "wallet_sign"}
        for f in forbidden:
            assert f not in rec, f"Forbidden field {f!r} found in record"

    def test_polymarket_record_invariants(self):
        from scripts.live_source_runner import _normalize_polymarket_record
        rec = {"market_id": "x", "question": "Will inflation rise?"}
        out = _normalize_polymarket_record(rec)
        assert out is not None
        self._check(out)

    def test_gdelt_record_invariants(self):
        from scripts.live_source_runner import _normalize_gdelt_record
        out = _normalize_gdelt_record({"url": "https://x.com", "title": "test"})
        self._check(out)

    def test_sec_edgar_record_invariants(self):
        from scripts.live_source_runner import _normalize_sec_record
        out = _normalize_sec_record({"cik": "123", "accession_number": "001", "form_type": "10-K"})
        self._check(out)

    def test_newsapi_record_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_newsapi_record
        out = _normalize_newsapi_record({"url": "https://x.com", "title": "test"})
        self._check(out)
        assert out.get("broker_api_called") is False

    def test_etherscan_record_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_etherscan_record
        out = _normalize_etherscan_record({"hash": "0xabc", "from_address": "0x1", "to_address": "0x2"})
        self._check(out)
        assert out.get("broker_api_called") is False

    def test_grok_record_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_grok_record
        out = _normalize_grok_record({"source_prompt": "q", "created_at": "ts"})
        self._check(out)
        assert out.get("broker_api_called") is False

    def test_india_record_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_india_record
        out = _normalize_india_record({"regulatory_source": "nse", "index_name": "NIFTY 50"})
        self._check(out)

    def test_global_filings_record_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_global_filings_record
        out = _normalize_global_filings_record({
            "issuer_name": "BHP", "ticker_or_identifier": "BHP",
            "exchange_or_regulator": "ASX", "jurisdiction": "AU",
            "disclosure_type": "announcement", "provider": "asx",
        })
        self._check(out)
        assert out.get("broker_api_called") is False
        assert out.get("broker_order_id") == "NONE"

    def test_asia_disclosure_record_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_asia_disclosure_record
        out = _normalize_asia_disclosure_record({
            "issuer_name": "Tencent", "provider": "hkex", "jurisdiction": "HK",
        })
        self._check(out)
        assert out.get("broker_api_called") is False
        assert out.get("broker_order_id") == "NONE"

    def test_market_data_record_invariants(self):
        from scripts.live_source_runner_phase2 import _normalize_market_data_record
        out = _normalize_market_data_record({"symbol": "SPY", "timestamp": "2026-05-10"})
        self._check(out)
        assert out.get("broker_api_called") is False


# ============================================================================
# 10. DB cleanup — classify_row function
# ============================================================================


class TestDBCleanup:
    def test_classify_allowed_market(self):
        from scripts.cleanup_polymarket_db import _classify_row
        row = {
            "raw_payload": json.dumps({
                "title": "Will the Fed cut rates in 2026?",
                "category": "finance",
            })
        }
        assert _classify_row(row) is True

    def test_classify_blocked_market(self):
        from scripts.cleanup_polymarket_db import _classify_row
        row = {
            "raw_payload": json.dumps({
                "title": "Who wins the 2026 NBA championship?",
                "category": "sports",
            })
        }
        assert _classify_row(row) is False

    def test_cleanup_dry_run_no_delete(self, tmp_path):
        from scripts.cleanup_polymarket_db import run_cleanup
        from scripts.persistence import init_schema, insert_signal_event

        db = tmp_path / "test.db"
        init_schema(db)
        # Insert a blocked market
        payload = {"title": "Who wins NBA Finals?", "source_name": "polymarket"}
        insert_signal_event("pm-001", "polymarket", payload, "2026-05-10", db_path=db)

        result = run_cleanup(dry_run=True, db_path=db)
        assert result["would_delete"] == 1
        assert result["deleted"] == 0  # dry run — nothing deleted

    def test_cleanup_write_deletes_blocked(self, tmp_path):
        from scripts.cleanup_polymarket_db import run_cleanup
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        db = tmp_path / "test.db"
        init_schema(db)
        insert_signal_event(
            "pm-001", "polymarket",
            {"title": "Who wins NBA Finals?"},
            "2026-05-10", db_path=db
        )
        insert_signal_event(
            "pm-002", "polymarket",
            {"title": "Will Fed cut rates?"},
            "2026-05-10", db_path=db
        )

        result = run_cleanup(dry_run=False, db_path=db)
        assert result["deleted"] == 1
        assert result["kept"] == 1

        remaining = get_signal_events(source_name="polymarket", db_path=db)
        assert len(remaining) == 1
        # The remaining row should be the allowed one
        payload = remaining[0]["raw_payload"]
        assert "Fed" in (payload.get("title") or "")

    def test_cleanup_does_not_touch_other_sources(self, tmp_path):
        from scripts.cleanup_polymarket_db import run_cleanup
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        db = tmp_path / "test.db"
        init_schema(db)
        # Blocked Polymarket row
        insert_signal_event(
            "pm-001", "polymarket",
            {"title": "Who wins NBA Finals?"},
            "2026-05-10", db_path=db
        )
        # Non-polymarket rows that must NOT be touched
        insert_signal_event("na-001", "newsapi", {"title": "Inflation data"}, "2026-05-10", db_path=db)
        insert_signal_event("er-001", "event_registry", {"title": "GDP data"}, "2026-05-10", db_path=db)

        run_cleanup(dry_run=False, db_path=db)

        news_events = get_signal_events(source_name="newsapi", db_path=db)
        er_events = get_signal_events(source_name="event_registry", db_path=db)
        assert len(news_events) == 1
        assert len(er_events) == 1
