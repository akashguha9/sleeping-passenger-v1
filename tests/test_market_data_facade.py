"""Gap 2: market_data_adapter exposes a real, truthful, single-source facade.

Proves: (1) the live facade does real callable work via an injected fetcher
(no network), (2) failures stay structured and never raise, (3) the source
chain truthfully reports single-source / no-fallback / no-stale-cache, and
(4) the seeded placeholder contract is preserved unchanged.
"""

from scripts import market_data_adapter as mda


def test_live_facade_returns_real_quote_with_injected_fetcher() -> None:
    def fake_fetcher(symbol: str) -> dict:
        return {"last_price": 123.45, "currency": "USD"}

    adapter = mda.create_live_market_data_adapter(fetcher=fake_fetcher)
    result = adapter.fetch_latest_quote("AAPL")

    assert result.ok is True
    assert result.quote is not None
    assert result.quote.price == 123.45
    assert result.quote.source == "yahoo_finance"
    assert result.resolved_provider == "yahoo_finance"


def test_live_facade_failure_is_structured_and_non_raising() -> None:
    def boom(symbol: str) -> dict:
        raise RuntimeError("network down")

    adapter = mda.create_live_market_data_adapter(fetcher=boom)
    # Must not raise.
    result = adapter.fetch_latest_quote("AAPL")
    assert result.ok is False
    assert result.quote is None
    assert result.error  # structured error string present


def test_live_facade_empty_symbol_is_structured_not_crash() -> None:
    adapter = mda.create_live_market_data_adapter(fetcher=lambda s: {})
    result = adapter.fetch_latest_quote("   ")
    assert result.ok is False
    assert result.quote is None


def test_missing_price_is_not_ok() -> None:
    adapter = mda.create_live_market_data_adapter(fetcher=lambda s: {"currency": "USD"})
    result = adapter.fetch_latest_quote("AAPL")
    assert result.ok is False
    assert result.quote is None


def test_source_chain_is_truthful_single_source() -> None:
    chain = mda.market_data_source_chain()
    assert chain["primary_source"] == "yahoo_finance"
    assert chain["live_source_count"] == 1
    assert chain["fallback_sources"] == []  # no redundancy claimed
    assert chain["stale_cache_enabled"] is False  # no stale cache claimed


def test_seeded_placeholder_contract_preserved() -> None:
    # The seeded describe() must still be an explicit placeholder (consumed by
    # runtime_common / repo_operating_mode), now WITH honest source-chain.
    payload = mda.describe_market_data_adapter()
    assert payload["live_quotes_available"] is False
    assert payload["contract_state"] == "placeholder"
    assert payload["truth_origin_tags"] == ["placeholder"]
    assert payload["source_chain"]["live_source_count"] == 1
    assert payload["source_chain"]["fallback_sources"] == []
