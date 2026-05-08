"""Tests for the read-only loaders.

We never make real network calls. Each test either:
  - patches the loader's ``_http_get`` with a fixture, or
  - verifies that the loader skips cleanly when its API key is absent, or
  - exercises the offline path (CSV / placeholder).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ingestion.broker_csv_loader import BrokerCSVLoader  # noqa: E402
from scripts.ingestion.etherscan_loader import EtherscanLoader  # noqa: E402
from scripts.ingestion.evm_chain_loader import EVMChainLoader  # noqa: E402
from scripts.ingestion.gdelt_loader import GDELTLoader  # noqa: E402
from scripts.ingestion.grok_interpreter import GrokInterpreter  # noqa: E402
from scripts.ingestion.market_data_loader import MarketDataLoader  # noqa: E402
from scripts.ingestion.newsapi_loader import NewsAPILoader  # noqa: E402
from scripts.ingestion.polymarket_loader import PolymarketLoader  # noqa: E402
from scripts.ingestion.sec_edgar_loader import SECEdgarLoader  # noqa: E402
from scripts.ingestion.solscan_loader import SolscanLoader  # noqa: E402
from scripts.normalization.signal_event_schema import (  # noqa: E402
    ADVISORY_ONLY,
    SignalEvent,
)


def _strip_keys(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Polymarket — public read-only
# ---------------------------------------------------------------------------


def test_polymarket_loader_normalizes_public_market(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = PolymarketLoader()
    fake_payload = [
        {
            "id": "abc",
            "question": "Will X happen?",
            "slug": "will-x-happen",
            "lastTradePrice": 0.42,
            "volume24hr": 12345.6,
            "description": "test market",
        }
    ]
    monkeypatch.setattr(loader, "_http_get", lambda *a, **kw: fake_payload)
    result = loader.fetch(limit=5)
    assert result.status == "ok"
    assert len(result.events) == 1
    event = result.events[0]
    assert isinstance(event, SignalEvent)
    assert event.source_type == "prediction_market"
    assert event.execution_permission == ADVISORY_ONLY
    assert event.human_review_required is True
    assert event.numeric_signal.probability == pytest.approx(0.42)
    assert event.url == "https://polymarket.com/event/will-x-happen"


def test_polymarket_loader_has_no_auth_or_trading_imports() -> None:
    src = Path(REPO_ROOT / "scripts" / "ingestion" / "polymarket_loader.py").read_text()
    for token in (
        "place_order",
        "submit_order",
        "execute_trade",
        "private_key",
        "Bearer ",
        "Authorization",
        "X-API-KEY",
    ):
        assert token not in src, f"polymarket loader unexpectedly references {token!r}"


# ---------------------------------------------------------------------------
# GDELT — read-only, network errors must not crash
# ---------------------------------------------------------------------------


def test_gdelt_loader_handles_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = GDELTLoader()

    def _boom(*_a, **_kw):
        raise RuntimeError("dns fail")

    monkeypatch.setattr(loader, "_http_get", _boom)
    result = loader.fetch(query="fed rate")
    assert result.status == "error"
    assert "dns fail" in (result.error or "")


def test_gdelt_loader_normalizes_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    loader = GDELTLoader()
    payload = {
        "articles": [
            {
                "title": "Headline 1",
                "url": "https://example.com/a",
                "seendate": "20251108T120000Z",
                "domain": "example.com",
                "excerpt": "summary",
            }
        ]
    }
    monkeypatch.setattr(loader, "_http_get", lambda *a, **kw: payload)
    result = loader.fetch(query="fed")
    assert result.status == "ok"
    assert result.events[0].source_type == "news_event"


# ---------------------------------------------------------------------------
# SEC EDGAR — must skip without SEC_USER_AGENT
# ---------------------------------------------------------------------------


def test_sec_edgar_skips_without_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    _strip_keys(monkeypatch, "SEC_USER_AGENT")
    loader = SECEdgarLoader()
    result = loader.fetch(cik="320193")
    assert result.status == "skipped"
    assert "SEC_USER_AGENT" in (result.skipped_reason or "")


def test_sec_edgar_normalizes_filings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "Test contact@example.com")
    loader = SECEdgarLoader()
    payload = {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q"],
                "accessionNumber": ["0000320193-25-000001", "0000320193-25-000002"],
                "filingDate": ["2025-01-02", "2025-02-03"],
                "primaryDocument": ["a.htm", "b.htm"],
            }
        },
    }
    monkeypatch.setattr(loader, "_http_get", lambda *a, **kw: payload)
    result = loader.fetch(cik="320193", limit=2)
    assert result.status == "ok"
    assert len(result.events) == 2
    assert result.events[0].source_type == "official_filing"
    assert result.events[0].url and "Archives/edgar/data" in result.events[0].url


# ---------------------------------------------------------------------------
# Etherscan — must skip without API key
# ---------------------------------------------------------------------------


def test_etherscan_skips_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _strip_keys(monkeypatch, "ETHERSCAN_API_KEY")
    loader = EtherscanLoader()
    result = loader.fetch(address="0xabc")
    assert result.status == "skipped"
    assert "ETHERSCAN_API_KEY" in (result.skipped_reason or "")


def test_etherscan_normalizes_token_transfer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETHERSCAN_API_KEY", "TEST")
    loader = EtherscanLoader()
    payload = {
        "status": "1",
        "result": [
            {
                "from": "0xfrom",
                "to": "0xto",
                "value": str(2 * 10 ** 18),
                "tokenDecimal": "18",
                "tokenSymbol": "USDC",
                "hash": "0xdeadbeef",
                "timeStamp": "1735689600",
            }
        ],
    }
    monkeypatch.setattr(loader, "_http_get", lambda *a, **kw: payload)
    result = loader.fetch(address="0xabc")
    assert result.status == "ok"
    assert result.events[0].source_type == "onchain"
    assert result.events[0].asset_tags == ["USDC"]


# ---------------------------------------------------------------------------
# Market data placeholder + Broker CSV
# ---------------------------------------------------------------------------


def test_market_data_skips_without_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("not installed for test")
        return real_import(name, *args, **kwargs)

    if isinstance(__builtins__, dict):
        monkeypatch.setitem(__builtins__, "__import__", fake_import)
    else:
        monkeypatch.setattr(__builtins__, "__import__", fake_import)
    loader = MarketDataLoader()
    result = loader.fetch(ticker="AAPL")
    assert result.status == "skipped"


def test_broker_csv_loader_reads_local_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "journal.csv"
    csv_path.write_text(
        "ticker,side,quantity,price,timestamp\nAAPL,BUY,10,100.0,2025-01-02\n",
        encoding="utf-8",
    )
    loader = BrokerCSVLoader()
    result = loader.read(csv_path=csv_path)
    assert result.status == "ok"
    assert len(result.events) == 1
    assert result.events[0].source_type == "portfolio_truth"


def test_broker_csv_loader_skips_without_path() -> None:
    result = BrokerCSVLoader().read()
    assert result.status == "skipped"


# ---------------------------------------------------------------------------
# Placeholder loaders skip cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "loader_cls,env_names",
    [
        (NewsAPILoader, ("NEWSAPI_KEY",)),
        (GrokInterpreter, ("GROK_API_KEY",)),
        (SolscanLoader, ("SOLSCAN_API_KEY",)),
    ],
)
def test_placeholder_loaders_skip_cleanly(
    loader_cls, env_names, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strip_keys(monkeypatch, *env_names)
    result = loader_cls().fetch()
    assert result.status == "skipped"


def test_evm_chain_loader_skips_each_chain_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _strip_keys(
        monkeypatch,
        "BSCSCAN_API_KEY",
        "POLYGONSCAN_API_KEY",
        "ARBISCAN_API_KEY",
        "BASESCAN_API_KEY",
    )
    loader = EVMChainLoader()
    for chain in ("bsc", "polygon", "arbitrum", "base"):
        result = loader.fetch(chain=chain)
        assert result.status == "skipped"


def test_evm_chain_loader_unsupported_chain() -> None:
    result = EVMChainLoader().fetch(chain="unsupported")
    assert result.status == "error"
