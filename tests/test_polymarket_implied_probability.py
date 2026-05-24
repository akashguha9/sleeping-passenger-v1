"""
Polymarket implied_probability enrichment at ingestion.

Locks in the contract that every loader record carries a normalized
``implied_probability`` (0..1) and an ``implied_probability_source``
audit field so downstream consumers (disagreement scanner, frontend)
do not have to re-derive the value.

Hard contracts
--------------
- 0..1 decimals pass through unchanged.
- 0..100 cents convert to 0..1.
- ``outcomePrices`` as a JSON string and as a list both work.
- Invalid (>1, <0, non-numeric, missing) returns ``None`` and a
  ``"missing"`` source label — never silently fakes a number.
- The midpoint of bestBid/bestAsk fires only as a last resort.
"""
from __future__ import annotations

import pytest

from scripts.ingestion.polymarket_loader import (
    PolymarketLoader,
    extract_polymarket_implied_probability,
)


# ---------------------------------------------------------------------------
# Extraction primitive
# ---------------------------------------------------------------------------


class TestExtractPolymarketImpliedProbability:
    def test_canonical_implied_probability_decimal(self):
        prob, src = extract_polymarket_implied_probability({"implied_probability": 0.42})
        assert prob == pytest.approx(0.42)
        assert src == "implied_probability"

    def test_outcome_prices_as_json_string(self):
        prob, src = extract_polymarket_implied_probability(
            {"outcomePrices": '["0.62","0.38"]'}
        )
        assert prob == pytest.approx(0.62)
        assert src == "outcomePrices"

    def test_outcome_prices_as_list(self):
        prob, src = extract_polymarket_implied_probability(
            {"outcomePrices": [0.31, 0.69]}
        )
        assert prob == pytest.approx(0.31)
        assert src == "outcomePrices"

    def test_outcome_prices_snake_case_alias(self):
        prob, src = extract_polymarket_implied_probability(
            {"outcome_prices": ["0.25", "0.75"]}
        )
        assert prob == pytest.approx(0.25)
        assert src == "outcome_prices"

    def test_yes_price_as_dollars(self):
        prob, src = extract_polymarket_implied_probability({"yes_price": 0.49})
        assert prob == pytest.approx(0.49)
        assert src == "yes_price"

    def test_yes_price_as_cents_converts(self):
        prob, src = extract_polymarket_implied_probability({"yes_price": 49})
        assert prob == pytest.approx(0.49)
        assert src == "yes_price"

    def test_last_trade_price_fallback(self):
        prob, src = extract_polymarket_implied_probability({"lastTradePrice": 0.81})
        assert prob == pytest.approx(0.81)
        assert src == "lastTradePrice"

    def test_best_bid_best_ask_midpoint_as_last_resort(self):
        prob, src = extract_polymarket_implied_probability(
            {"bestBid": 0.50, "bestAsk": 0.52}
        )
        assert prob == pytest.approx(0.51)
        assert src == "bestBid_bestAsk_midpoint"

    def test_outcome_prices_take_priority_over_midpoint(self):
        prob, src = extract_polymarket_implied_probability(
            {
                "outcomePrices": [0.30, 0.70],
                "bestBid": 0.50,
                "bestAsk": 0.52,
            }
        )
        assert prob == pytest.approx(0.30)
        assert src == "outcomePrices"

    def test_implied_probability_takes_priority_over_outcome_prices(self):
        prob, src = extract_polymarket_implied_probability(
            {
                "implied_probability": 0.40,
                "outcomePrices": [0.30, 0.70],
            }
        )
        assert prob == pytest.approx(0.40)
        assert src == "implied_probability"

    @pytest.mark.parametrize(
        "raw,expected_none_reason",
        [
            ({}, "completely empty market"),
            ({"yes_price": "huh"}, "non-numeric"),
            ({"yes_price": -0.1}, "negative"),
            ({"yes_price": 250}, "out of cents range"),
            ({"implied_probability": 1.5}, "> 1"),
            ({"outcomePrices": "not-json"}, "broken JSON"),
            ({"outcomePrices": []}, "empty list"),
            ({"outcomePrices": [None, None]}, "list of None"),
            ({"bestBid": 0.6, "bestAsk": 0.5}, "ask < bid"),
        ],
    )
    def test_invalid_or_missing_returns_none_and_missing(self, raw, expected_none_reason):
        prob, src = extract_polymarket_implied_probability(raw)
        assert prob is None, f"unexpected probability for {expected_none_reason}"
        assert src == "", f"source should be empty when missing ({expected_none_reason})"

    def test_non_dict_returns_none(self):
        for bad in (None, "x", 42, [1, 2]):
            prob, src = extract_polymarket_implied_probability(bad)  # type: ignore[arg-type]
            assert prob is None
            assert src == ""


# ---------------------------------------------------------------------------
# Loader → record carries the normalised probability + source label.
# ---------------------------------------------------------------------------


class TestLoaderRecordEnrichment:
    def test_record_carries_implied_probability_and_source(self):
        loader = PolymarketLoader(limit=5)
        raw_markets = [
            {
                "id": "pm-001",
                "question": "Will the Fed cut rates in June?",
                "category": "economy",
                "outcomePrices": '["0.31","0.69"]',
                "volume": 1000,
                "liquidity": 800,
            },
            {
                "id": "pm-002",
                "question": "Will BTC close above $100k in 2026?",
                "category": "crypto",
                "yes_price": 42,  # cents
                "volume": 500,
                "liquidity": 400,
            },
            {
                "id": "pm-003",
                "question": "Will any tech IPO double on day one?",
                "category": "finance",
                # only midpoint signal
                "bestBid": 0.20,
                "bestAsk": 0.24,
            },
            {
                "id": "pm-004",
                "question": "Garbage row with no probability anywhere",
                "category": "macro",
                # nothing valid
            },
        ]
        records = loader._raw_markets_to_records(raw_markets)
        assert len(records) == 4

        by_id = {r["market_id"]: r for r in records}

        assert by_id["pm-001"]["implied_probability"] == pytest.approx(0.31)
        assert by_id["pm-001"]["implied_probability_source"] == "outcomePrices"

        assert by_id["pm-002"]["implied_probability"] == pytest.approx(0.42)
        assert by_id["pm-002"]["implied_probability_source"] == "yes_price"

        assert by_id["pm-003"]["implied_probability"] == pytest.approx(0.22)
        assert by_id["pm-003"]["implied_probability_source"] == "bestBid_bestAsk_midpoint"

        assert by_id["pm-004"]["implied_probability"] is None
        assert by_id["pm-004"]["implied_probability_source"] == "missing"

    def test_title_field_falls_back_to_question(self):
        loader = PolymarketLoader(limit=5)
        rec = loader._raw_markets_to_records(
            [{"id": "pm-x", "question": "Will the Fed cut?"}]
        )[0]
        assert rec["title"] == "Will the Fed cut?"
        assert rec["question"] == "Will the Fed cut?"
