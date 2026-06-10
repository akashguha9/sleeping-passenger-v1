"""Prediction-market normalization adapter invariants (offline only)."""

from __future__ import annotations

import pytest

from src.alpha.adapters.prediction_market_adapter import (
    compute_probability_edge,
    convert_to_prediction_market_signal,
    derive_market_probability,
    normalize_probability,
    probability_confirmation_score,
)


def test_normalize_probability_fraction_and_cents() -> None:
    assert normalize_probability(0.42) == pytest.approx(0.42)
    assert normalize_probability(42) == pytest.approx(0.42)
    assert normalize_probability("0.31") == pytest.approx(0.31)


def test_normalize_probability_clamps_and_rejects_garbage() -> None:
    assert normalize_probability(-3.0) == 0.0
    assert normalize_probability(250) == 1.0  # 250 cents clamps to 1.0
    assert normalize_probability("not a number") is None
    assert normalize_probability(None) is None
    assert normalize_probability(True) is None
    assert normalize_probability(float("nan")) is None


def test_bid_ask_midpoint() -> None:
    estimate = derive_market_probability(
        {"yes_bid": 0.40, "yes_ask": 0.44, "source": "kalshi"}
    )
    assert estimate["probability"] == pytest.approx(0.42)
    assert estimate["method"] == "bid_ask_mid"
    assert estimate["spread"] == pytest.approx(0.04)


def test_yes_bid_derived_from_no_ask() -> None:
    estimate = derive_market_probability(
        {"yes_ask": 0.42, "no_ask": 0.58, "source": "kalshi"}
    )
    # yes_bid = 1 - 0.58 = 0.42 -> mid = 0.42, spread = 0.
    assert estimate["probability"] == pytest.approx(0.42)
    assert estimate["spread"] == pytest.approx(0.0)


def test_wider_spread_reduces_confidence() -> None:
    tight = derive_market_probability(
        {"yes_bid": 0.41, "yes_ask": 0.43, "source": "kalshi"}
    )
    wide = derive_market_probability(
        {"yes_bid": 0.30, "yes_ask": 0.54, "source": "kalshi"}
    )
    assert wide["confidence"] < tight["confidence"]
    assert wide["confidence"] == 0.0  # spread beyond cap is worthless


def test_last_price_fallback_has_lower_confidence_than_quote() -> None:
    quote = derive_market_probability(
        {"yes_bid": 0.40, "yes_ask": 0.42, "source": "kalshi"}
    )
    last = derive_market_probability({"last_price": 0.41, "source": "kalshi"})
    assert last["method"] == "last_price"
    assert last["confidence"] < quote["confidence"]
    assert "bid_ask_quote" in last["missing_inputs"]


def test_no_market_data_neutral_fallback() -> None:
    estimate = derive_market_probability({"source": "kalshi"})
    assert estimate["probability"] == 0.5
    assert estimate["confidence"] == 0.0
    assert estimate["method"] == "neutral_fallback"
    assert "market_probability" in estimate["missing_inputs"]


def test_manual_stub_source_quality_below_kalshi() -> None:
    kalshi = derive_market_probability(
        {"yes_bid": 0.40, "yes_ask": 0.42, "source": "kalshi"}
    )
    stub = derive_market_probability({"yes_bid": 0.40, "yes_ask": 0.42})
    assert stub["source"] == "manual_stub"
    assert stub["confidence"] < kalshi["confidence"]


def test_compute_probability_edge_clamps() -> None:
    assert compute_probability_edge(0.7, 0.4) == pytest.approx(0.3)
    assert compute_probability_edge(5.0, -1.0) == pytest.approx(1.0)


def test_convert_kalshi_mock_snapshot_deterministically() -> None:
    from src.ingestion.kalshi_public_client import KalshiPublicClient

    client = KalshiPublicClient()
    snapshots = client._mock_markets()  # deterministic fixture, no network
    assert snapshots, "mock fixture must yield markets"
    first = convert_to_prediction_market_signal(snapshots[0], 0.50).to_dict()
    second = convert_to_prediction_market_signal(snapshots[0], 0.50).to_dict()
    assert first == second
    assert first["source"] == "kalshi"
    assert 0.0 <= first["market_probability"] <= 1.0
    assert first["probability_edge"] == pytest.approx(
        first["model_probability"] - first["market_probability"]
    )


def test_convert_plain_dict_event() -> None:
    signal = convert_to_prediction_market_signal(
        {
            "event_name": "infrastructure bill passes",
            "yes_bid": 0.30,
            "yes_ask": 0.34,
            "resolution_date": "2026-12-31",
            "source": "kalshi",
        },
        model_probability=0.41,
    )
    assert signal.market_probability == pytest.approx(0.32)
    assert signal.probability_edge == pytest.approx(0.09)
    assert signal.derivation_method == "bid_ask_mid"


def test_missing_model_probability_yields_zero_edge_and_is_reported() -> None:
    signal = convert_to_prediction_market_signal(
        {"yes_bid": 0.30, "yes_ask": 0.34, "source": "kalshi"}
    )
    assert signal.probability_edge == 0.0
    assert "model_probability" in signal.missing_inputs


def test_probability_confirmation_score_neutral_and_bounded() -> None:
    assert probability_confirmation_score(0.0, 100.0) == 50.0
    assert probability_confirmation_score(0.3, 0.0) == 50.0  # no confidence, no move
    assert probability_confirmation_score(1.0, 100.0) == 100.0
    assert probability_confirmation_score(-1.0, 100.0) == 0.0
    high_conf = probability_confirmation_score(0.2, 90.0)
    low_conf = probability_confirmation_score(0.2, 20.0)
    assert high_conf > low_conf > 50.0


def test_adapter_module_makes_no_network_calls() -> None:
    import src.alpha.adapters.prediction_market_adapter as adapter

    source = open(adapter.__file__).read()
    for fragment in ("requests.", "urllib", "httpx", "socket"):
        assert fragment not in source
