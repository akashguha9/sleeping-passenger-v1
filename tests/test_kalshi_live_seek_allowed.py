"""Tests for the Kalshi live smoke ``--seek-allowed`` mode and the
HTTP-resilience metrics emitted alongside it.

Every test in this module is fully mocked — no live HTTP fires.  The
fixtures cover:

- Allowed records are recovered when only a deeper page contains them
  (the weather-heavy demo first page problem).
- Honest status when upstream is reachable but no allowed records pass
  the seven-category gate.
- Financials → finance mapping via official_metadata only.
- Esports never leaks into crypto, even with seek-allowed enabled.
- Partial /events enrichment failure is non-fatal and surfaces metrics.
- HTTP 429 / 5xx / timeout each persist a structured source-health
  status and never leak secrets.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.ingestion.kalshi_live_client import KalshiLiveClient
from src.ingestion.kalshi_live_config import load_kalshi_live_config
from src.ingestion.kalshi_live_loader import (
    SOURCE_ERROR_TIMEOUT,
    SOURCE_LIVE_VERIFIED_EMPTY_SCOPE,
    SOURCE_RATE_LIMITED,
    run_live_kalshi_smoke,
)


SECRET_API_KEY_ID = "deadbeef-cafe-1234-5678-abcdefabcdef"


@pytest.fixture
def gen_key(tmp_path: Path) -> Path:
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    p = tmp_path / "seek_allowed.key"
    p.write_bytes(pem)
    return p


def _env(key_path: Path) -> dict[str, str]:
    return {
        "KALSHI_ENV": "demo",
        "KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2",
        "KALSHI_WS_BASE_URL": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
        "KALSHI_API_KEY_ID": SECRET_API_KEY_ID,
        "KALSHI_PRIVATE_KEY_PATH": str(key_path),
        "KALSHI_ENABLE_AUTH": "true",
        "KALSHI_READ_ONLY": "true",
        "KALSHI_ENABLE_TRADING": "false",
        "KALSHI_ORDER_PLACEMENT_ENABLED": "false",
        "KALSHI_BROKER_API_CALLED": "false",
        "KALSHI_USE_MOCK_FIXTURES": "false",
        "KALSHI_FRESHNESS_TTL_SECONDS": "21600",
    }


def _client_with_pages(pages: list[dict]) -> MagicMock:
    fake = MagicMock(spec=KalshiLiveClient)
    fake.auth_used = True
    fake.base_url = "https://external-api.demo.kalshi.co/trade-api/v2"
    fake.get_exchange_status.return_value = {"exchange_active": True}
    fake.get_events.return_value = {"events": []}
    fake.get_event.return_value = {"event": {}}
    page_iter = iter(pages)

    def _next(*args, **kwargs):
        try:
            return next(page_iter)
        except StopIteration:
            return {"markets": [], "cursor": None}

    fake.get_markets.side_effect = _next
    return fake


def test_seek_allowed_paginates_until_allowed_found(tmp_path: Path, gen_key: Path):
    cfg = load_kalshi_live_config(environ=_env(gen_key))
    page1 = {
        "markets": [
            {
                "ticker": "WEATHER-1",
                "title": "Will it rain in Austin?",
                "category": "Weather",
                "close_time": "2026-06-30T00:00:00Z",
            }
        ],
        "cursor": "p2",
    }
    page2 = {
        "markets": [
            {
                "ticker": "WTI-JUN-2026",
                "title": "Will WTI crude close above $80 by end of June 2026?",
                "category": "Commodities",
                "close_time": "2026-06-30T00:00:00Z",
            }
        ],
        "cursor": None,
    }
    fake = _client_with_pages([page1, page2])
    health = tmp_path / "kalshi_source_health.json"
    quarantine = tmp_path / "kalshi_quarantine.jsonl"

    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=5,
        limit=100,
        dry_run=True,
        seek_allowed=True,
        min_allowed=1,
        health_path=health,
        quarantine_path=quarantine,
    )

    assert result.status == "ok"
    assert result.records_allowed >= 1
    assert result.allowed_found is True
    assert result.first_allowed_seen_at_page == 2
    assert result.pages_scanned == 2
    summary = json.loads(health.read_text(encoding="utf-8"))
    assert summary["seek_allowed"] is True
    assert summary["allowed_found"] is True
    assert summary["pages_scanned"] == 2
    assert summary["accepted_sample_titles"]
    # Secrets must NOT appear in the artifact.
    blob = json.dumps(summary)
    assert SECRET_API_KEY_ID not in blob
    assert "KALSHI-ACCESS-KEY" not in blob


def test_seek_allowed_honest_empty_scope(tmp_path: Path, gen_key: Path):
    cfg = load_kalshi_live_config(environ=_env(gen_key))
    pages = [
        {
            "markets": [
                {
                    "ticker": f"W-{i}",
                    "title": "Will it rain?",
                    "category": "Weather",
                    "close_time": "2026-06-30T00:00:00Z",
                }
                for i in range(5)
            ],
            "cursor": None,
        }
    ]
    fake = _client_with_pages(pages)
    health = tmp_path / "kalshi_source_health.json"
    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=3,
        limit=100,
        seek_allowed=True,
        min_allowed=1,
        health_path=health,
        quarantine_path=tmp_path / "q.jsonl",
    )
    assert result.status == "ok"
    assert result.records_allowed == 0
    assert result.records_seen_total == 5
    summary = json.loads(health.read_text(encoding="utf-8"))
    assert summary["source_freshness_status"] == SOURCE_LIVE_VERIFIED_EMPTY_SCOPE
    # Honesty: this is NOT a failure status.
    assert summary["status"] == "OK"


def test_financials_maps_to_finance_only_via_official_metadata(
    tmp_path: Path, gen_key: Path
):
    cfg = load_kalshi_live_config(environ=_env(gen_key))
    page = {
        "markets": [
            {
                "ticker": "FIN-1",
                "title": "Will S&P 500 close above 6000 on June 30 2026?",
                "category": "Financials",
                "close_time": "2026-06-30T20:00:00Z",
            }
        ],
        "cursor": None,
    }
    fake = _client_with_pages([page])
    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=1,
        limit=20,
        dry_run=True,
        health_path=tmp_path / "h.json",
        quarantine_path=tmp_path / "q.jsonl",
    )
    assert result.records_allowed == 1
    assert "finance" in result.accepted_category_counts


def test_esports_never_maps_to_crypto_under_seek_allowed(
    tmp_path: Path, gen_key: Path
):
    cfg = load_kalshi_live_config(environ=_env(gen_key))
    page1 = {
        "markets": [
            {
                "ticker": "KXMVESPORTSMULTIGAME-1234",
                "title": "Esports multigame featuring BTC stream",
                "category": "Esports",
                "close_time": "2026-07-01T00:00:00Z",
            }
        ],
        "cursor": "p2",
    }
    page2 = {
        "markets": [
            {
                "ticker": "BTCMAY-2026",
                "title": "How high will Bitcoin get in May?",
                "category": "Crypto",
                "close_time": "2026-05-31T23:59:00Z",
            }
        ],
        "cursor": None,
    }
    fake = _client_with_pages([page1, page2])
    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=5,
        limit=20,
        seek_allowed=True,
        min_allowed=1,
        health_path=tmp_path / "h.json",
        quarantine_path=tmp_path / "q.jsonl",
    )
    assert result.records_allowed == 1
    assert result.accepted_category_counts.get("crypto", 0) == 1
    assert "esports" not in result.accepted_category_counts
    assert "Esports" not in result.accepted_category_counts


def test_partial_event_enrichment_failure_is_non_fatal(
    tmp_path: Path, gen_key: Path
):
    cfg = load_kalshi_live_config(environ=_env(gen_key))
    page = {
        "markets": [
            {
                "ticker": "BTCMAY-2026",
                "title": "How high will Bitcoin get in May?",
                "category": "Crypto",
                "event_ticker": "BTC-2026",
                "close_time": "2026-05-31T23:59:00Z",
            },
            {
                "ticker": "FIN-1",
                "title": "Will S&P 500 close above 6000?",
                "category": "Finance",
                "event_ticker": "SPX-2026",
                "close_time": "2026-06-30T00:00:00Z",
            },
        ],
        "cursor": None,
    }
    fake = _client_with_pages([page])
    # Bulk /events returns nothing (forces per-event enrichment).
    fake.get_events.return_value = {"events": []}

    def _per_event(ticker):
        # First lookup succeeds, second fails.  Loader must continue and
        # still surface accepted-records for the page.
        if ticker == "BTC-2026":
            return {"event": {"event_ticker": ticker, "category": "Crypto"}}
        raise RuntimeError("HTTP 404")

    fake.get_event.side_effect = _per_event

    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=1,
        limit=20,
        dry_run=True,
        health_path=tmp_path / "h.json",
        quarantine_path=tmp_path / "q.jsonl",
    )
    assert result.status == "ok"
    assert result.records_allowed == 2
    assert result.event_enrichment_attempted == 2
    assert result.event_enrichment_succeeded == 1
    assert result.event_enrichment_failed == 1
    assert 0.0 < result.event_enrichment_failure_rate <= 1.0


def _exc_with_status(status_code: int, exc_cls=RuntimeError) -> Exception:
    response = MagicMock()
    response.status_code = status_code
    exc = exc_cls(f"http {status_code}")
    exc.response = response
    return exc


def test_rate_limit_writes_rate_limit_status(tmp_path: Path, gen_key: Path):
    cfg = load_kalshi_live_config(environ=_env(gen_key))
    fake = MagicMock(spec=KalshiLiveClient)
    fake.auth_used = True
    fake.base_url = cfg.api_base_url
    fake.get_exchange_status.return_value = {"exchange_active": True}
    fake.get_events.return_value = {"events": []}
    fake.get_event.return_value = {"event": {}}
    fake.get_markets.side_effect = _exc_with_status(429)

    health = tmp_path / "h.json"
    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=1,
        limit=20,
        dry_run=True,
        health_path=health,
        quarantine_path=tmp_path / "q.jsonl",
    )
    assert result.status == "error"
    summary = json.loads(health.read_text(encoding="utf-8"))
    assert summary["source_freshness_status"] == SOURCE_RATE_LIMITED
    assert summary["http_status"] == 429
    blob = json.dumps(summary)
    assert SECRET_API_KEY_ID not in blob


def test_5xx_writes_source_error(tmp_path: Path, gen_key: Path):
    cfg = load_kalshi_live_config(environ=_env(gen_key))
    fake = MagicMock(spec=KalshiLiveClient)
    fake.auth_used = True
    fake.base_url = cfg.api_base_url
    fake.get_exchange_status.return_value = {"exchange_active": True}
    fake.get_events.return_value = {"events": []}
    fake.get_event.return_value = {"event": {}}
    fake.get_markets.side_effect = _exc_with_status(503)

    health = tmp_path / "h.json"
    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=1,
        limit=20,
        dry_run=True,
        health_path=health,
        quarantine_path=tmp_path / "q.jsonl",
    )
    assert result.status == "error"
    summary = json.loads(health.read_text(encoding="utf-8"))
    assert summary["source_freshness_status"] == "SOURCE_ERROR"
    assert summary["http_status"] == 503


def test_timeout_writes_source_error_timeout(tmp_path: Path, gen_key: Path):
    cfg = load_kalshi_live_config(environ=_env(gen_key))

    class FakeTimeout(Exception):
        pass

    FakeTimeout.__name__ = "ConnectTimeout"

    fake = MagicMock(spec=KalshiLiveClient)
    fake.auth_used = True
    fake.base_url = cfg.api_base_url
    fake.get_exchange_status.return_value = {"exchange_active": True}
    fake.get_events.return_value = {"events": []}
    fake.get_event.return_value = {"event": {}}
    fake.get_markets.side_effect = FakeTimeout("timed out")

    health = tmp_path / "h.json"
    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=1,
        limit=20,
        dry_run=True,
        health_path=health,
        quarantine_path=tmp_path / "q.jsonl",
    )
    assert result.status == "error"
    summary = json.loads(health.read_text(encoding="utf-8"))
    assert summary["source_freshness_status"] == SOURCE_ERROR_TIMEOUT
