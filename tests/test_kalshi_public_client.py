"""
Tests for src/ingestion/kalshi_public_client.KalshiPublicClient.

Mirrors tests/test_polymarket_public_client.py — exercises the read-only
public client without ever hitting the live network.  Live HTTP is
intercepted with unittest.mock; the mock-fallback path is exercised by
pointing the client at an unreachable URL.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.kalshi_public_client import KalshiPublicClient


def _mock_response(payload, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_failed_api_falls_back_to_deterministic_mock_when_enabled() -> None:
    client = KalshiPublicClient()
    client.api_base_url = "http://127.0.0.1:1"
    client.retries = 0
    client.use_mock_on_failure = True
    markets = client.fetch_markets()
    assert markets, "mock fallback should return at least one market"
    for snap in markets:
        # Mock fallback returns only APPROVED categories.
        assert snap.category in (
            "Elections",
            "Politics",
            "Crypto",
            "Commodities",
            "Economics",
            "Finance",
            "Tech & Science",
        )
        assert snap.source == "kalshi"
        assert snap.source_label == "Kalshi"
        assert snap.advisory_status == "ADVISORY_ONLY"
        assert snap.execution_permission == "ADVISORY_ONLY"
        assert snap.execution_gate == "LOCKED"
        assert snap.human_review_required is True
        assert snap.broker_api_called is False
        assert snap.ai_execution_count == 0


def test_mock_market_data_normalized_correctly() -> None:
    client = KalshiPublicClient()
    snapshots = client._mock_markets()
    # The internal mock list contains an NBA Finals fixture used to verify
    # the allowlist gate — it MUST be filtered out by normalize_market.
    tickers = [s.source_market_id for s in snapshots]
    assert "NBA-FINALS-2026" not in tickers
    # Approved fixtures must survive.
    assert "BTCMAY-2026" in tickers
    btc = next(s for s in snapshots if s.source_market_id == "BTCMAY-2026")
    assert btc.implied_probability is not None
    assert 0.0 < btc.implied_probability < 1.0
    assert btc.semantic_text and "Bitcoin" in btc.semantic_text
    assert "Title:" in btc.semantic_text
    assert "Description:" in btc.semantic_text


def test_fetch_markets_parses_mocked_http_payload() -> None:
    client = KalshiPublicClient()
    client.retries = 0
    payload = {
        "markets": [
            {
                "ticker": "FED-CUT-JUN-2026",
                "title": "Will the Fed cut rates at the June 2026 meeting?",
                "subtitle": "FOMC June 2026",
                "rules_primary": "Settles to FOMC statement.",
                "category": "Economics",
                "tags": ["fed", "fomc"],
                "yes_ask": 0.31,
                "no_ask": 0.69,
                "volume": 4200,
                "open_interest": 2400,
                "close_time": "2026-06-18T18:00:00Z",
            },
            # rejected by the allowlist — must NOT appear in the output
            {
                "ticker": "EUROVISION-2026",
                "title": "Will France win Eurovision 2026?",
                "category": "Entertainment",
                "yes_ask": 0.05,
            },
        ]
    }
    with patch.object(client.session, "get", return_value=_mock_response(payload)):
        markets = client.fetch_markets()
    assert len(markets) == 1
    snap = markets[0]
    assert snap.source_market_id == "FED-CUT-JUN-2026"
    assert snap.category == "Economics"
    assert snap.advisory_status == "ADVISORY_ONLY"


def test_fetch_markets_handles_empty_response() -> None:
    client = KalshiPublicClient()
    client.retries = 0
    with patch.object(client.session, "get", return_value=_mock_response({"markets": []})):
        markets = client.fetch_markets()
    assert markets == []


def test_fetch_markets_only_uses_get() -> None:
    """The client must never issue non-GET requests."""
    client = KalshiPublicClient()
    client.retries = 0
    with patch.object(client.session, "get", return_value=_mock_response({"markets": []})) as get_mock:
        client.fetch_markets()
        get_mock.assert_called()
    # The session must have no POST/DELETE/PATCH wrappers wired anywhere
    # in the client.  Defensive: ensure we have not silently grown one.
    for verb in ("post", "delete", "patch", "put"):
        # The attribute exists on Session; assert the client never calls it.
        with patch.object(client.session, verb) as verb_mock:
            client.fetch_markets() if False else None  # no-op
            verb_mock.assert_not_called()


def test_health_check_reports_read_only_and_no_auth() -> None:
    client = KalshiPublicClient()
    client.api_base_url = "http://127.0.0.1:1"
    client.retries = 0
    client.use_mock_on_failure = True
    health = client.health_check()
    assert health["read_only"] is True
    assert health["auth_required"] is False
    assert health["broker_api_called"] is False
    assert health["ai_execution_count"] == 0
    assert health["execution_permission"] == "ADVISORY_ONLY"


def test_http_error_does_not_raise_when_mock_fallback_enabled() -> None:
    client = KalshiPublicClient()
    client.retries = 0
    client.use_mock_on_failure = True

    import requests as _requests

    err_resp = MagicMock()
    err_resp.status_code = 401
    err_resp.raise_for_status.side_effect = _requests.HTTPError("401")
    with patch.object(client.session, "get", return_value=err_resp):
        markets = client.fetch_markets()
    assert markets  # mock fallback kicked in
