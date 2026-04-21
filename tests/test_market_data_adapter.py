from scripts.market_data_adapter import (
    MarketDataQuote,
    YahooFinanceMarketDataAdapter,
    create_market_data_adapter,
)


def test_create_market_data_adapter_unknown_provider_is_deterministic() -> None:
    adapter = create_market_data_adapter("madeup_provider")
    result = adapter.fetch_latest_quote("TLT")

    assert result.ok is False
    assert result.quote is None
    assert result.retriable is False
    assert "Unsupported provider" in str(result.error)


def test_yahoo_adapter_cache_path() -> None:
    adapter = YahooFinanceMarketDataAdapter()

    calls = {"count": 0}

    def fake_download(symbol: str) -> MarketDataQuote:
        calls["count"] += 1
        return MarketDataQuote(
            symbol=symbol,
            price=99.5,
            currency="USD",
            source="yahoo_finance",
            as_of="2026-04-21T12:00:00+00:00",
        )

    adapter._download_quote = fake_download  # type: ignore[attr-defined]

    first = adapter.fetch_latest_quote("tlt")
    second = adapter.fetch_latest_quote("TLT")

    assert first.ok is True
    assert second.ok is True
    assert first.quote is not None
    assert second.quote is not None
    assert first.quote.price == 99.5
    assert second.quote.price == 99.5
    assert calls["count"] == 1


def test_yahoo_adapter_import_failure_is_deterministic() -> None:
    adapter = YahooFinanceMarketDataAdapter()

    def fake_download(symbol: str) -> MarketDataQuote:
        raise ImportError("No module named 'yfinance'")

    adapter._download_quote = fake_download  # type: ignore[attr-defined]

    result = adapter.fetch_latest_quote("TLT")

    assert result.ok is False
    assert result.quote is None
    assert result.retriable is False
    assert "yfinance import unavailable" in str(result.error)