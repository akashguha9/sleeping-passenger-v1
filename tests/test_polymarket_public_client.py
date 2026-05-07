from src.ingestion.polymarket_public_client import PolymarketPublicClient


def test_failed_api_handled_gracefully() -> None:
    client = PolymarketPublicClient()
    client.gamma_base_url = "http://127.0.0.1:1"
    client.clob_base_url = "http://127.0.0.1:1"
    markets = client.fetch_markets()
    assert markets
    assert markets[0].market_id


def test_mock_market_data_normalized_correctly() -> None:
    client = PolymarketPublicClient()
    market = client._mock_markets()[0]
    assert 0.0 < market.implied_probability < 1.0
    assert market.source == "polymarket_public"
