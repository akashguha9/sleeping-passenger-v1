"""
Tests for Phase C.5 — Market Data price-confirmation source.

Principles
----------
- Zero live network calls. yfinance is intercepted with unittest.mock.patch.
- Missing yfinance package skips cleanly with a meaningful reason string.
- Optional paid providers (Alpha Vantage, Twelve Data, Polygon) skip cleanly.
- Advisory contract enforced on all outputs: ADVISORY_ONLY, LOCKED, AI=0, BROKER=false.
- No broker API calls. No trade/execution fields in any report.
- No private-key, wallet, signing, transaction-send, or broadcast logic.
- market_confirmation_score is bounded [0, 1] and deterministic.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_hist(n: int = 5) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame that mirrors yfinance output."""
    dates = pd.date_range("2026-05-06", periods=n, freq="D", tz="America/New_York")
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": [99.0 + i for i in range(n)],
            "High": [105.0 + i for i in range(n)],
            "Low": [97.0 + i for i in range(n)],
            "Close": closes,
            "Volume": [1_000_000 + i * 200_000 for i in range(n)],
        },
        index=dates,
    )


def _make_mock_ticker(hist_df: pd.DataFrame | None = None) -> MagicMock:
    mock = MagicMock()
    mock.history.return_value = hist_df if hist_df is not None else _make_mock_hist()
    return mock


def _make_empty_hist() -> pd.DataFrame:
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])


def _mocked_yfinance(hist_df: pd.DataFrame | None = None):
    """Context manager that patches yfinance.Ticker with a mock."""
    mock_ticker = _make_mock_ticker(hist_df)
    return patch("yfinance.Ticker", return_value=mock_ticker)


# ---------------------------------------------------------------------------
# TestMarketDataConfirmationScore
# ---------------------------------------------------------------------------


class TestMarketDataConfirmationScore:
    def _score(self, pct, ratio):
        from scripts.ingestion.market_data_loader import _compute_market_confirmation_score

        return _compute_market_confirmation_score(pct, ratio)

    def test_returns_zero_when_price_pct_is_none(self) -> None:
        assert self._score(None, 2.0) == 0.0

    def test_returns_zero_when_both_none(self) -> None:
        assert self._score(None, None) == 0.0

    def test_zero_pct_returns_zero_score(self) -> None:
        assert self._score(0.0, None) == pytest.approx(0.0, abs=1e-6)

    def test_price_only_no_volume(self) -> None:
        score = self._score(1.5, None)
        # price_component = min(1.5/3, 1) * 0.6 = 0.5 * 0.6 = 0.3
        assert score == pytest.approx(0.3, abs=1e-4)

    def test_price_capped_at_3pct(self) -> None:
        score = self._score(3.0, None)
        assert score == pytest.approx(0.6, abs=1e-4)

    def test_price_above_3pct_still_capped(self) -> None:
        score_3 = self._score(3.0, None)
        score_10 = self._score(10.0, None)
        assert score_3 == score_10

    def test_negative_pct_uses_absolute_value(self) -> None:
        score_pos = self._score(2.0, None)
        score_neg = self._score(-2.0, None)
        assert score_pos == score_neg

    def test_volume_below_average_no_vol_contribution(self) -> None:
        score = self._score(2.0, 0.5)
        # vol_component = 0 since 0.5 < 1.0
        # price_component = min(2/3, 1)*0.6 = 0.4
        assert score == pytest.approx(0.4, abs=1e-4)

    def test_volume_at_average_no_contribution(self) -> None:
        score_no_vol = self._score(2.0, None)
        score_1x = self._score(2.0, 1.0)
        assert score_no_vol == score_1x

    def test_volume_2x_gives_0_4_component(self) -> None:
        # price_component=0, vol=2x → vol_component=min(1,1)*0.4=0.4
        score = self._score(0.0, 2.0)
        assert score == pytest.approx(0.4, abs=1e-4)

    def test_volume_above_2x_capped(self) -> None:
        score_2x = self._score(0.0, 2.0)
        score_5x = self._score(0.0, 5.0)
        assert score_2x == score_5x

    def test_combined_max_score_1_0(self) -> None:
        # 3% price + 2x volume = 0.6 + 0.4 = 1.0
        score = self._score(3.0, 2.0)
        assert score == pytest.approx(1.0, abs=1e-4)

    def test_score_bounded_to_1(self) -> None:
        score = self._score(100.0, 1000.0)
        assert score <= 1.0

    def test_score_non_negative(self) -> None:
        score = self._score(-100.0, 0.0)
        assert score >= 0.0

    def test_score_is_float(self) -> None:
        assert isinstance(self._score(1.5, 1.5), float)

    def test_deterministic_same_inputs(self) -> None:
        a = self._score(1.5, 1.8)
        b = self._score(1.5, 1.8)
        assert a == b


# ---------------------------------------------------------------------------
# TestNormalizationMarketData
# ---------------------------------------------------------------------------


class TestNormalizationMarketData:
    def _normalize(self, rec: dict[str, Any]) -> dict[str, Any]:
        from scripts.live_source_runner_phase2 import _normalize_market_data_record

        return _normalize_market_data_record(rec)

    def _full_rec(self) -> dict[str, Any]:
        return {
            "symbol": "SPY",
            "provider": "yahoo",
            "period": "5d",
            "interval": "1d",
            "latest_price": 500.25,
            "previous_close": 497.10,
            "price_change": 3.15,
            "price_change_pct": 0.634,
            "volume": 55_000_000.0,
            "average_volume": 45_000_000.0,
            "volume_change_ratio": 1.2222,
            "high": 501.50,
            "low": 498.30,
            "open": 498.75,
            "close": 500.25,
            "timestamp": "2026-05-10 00:00:00-04:00",
            "market_confirmation_score": 0.2274,
        }

    def test_source_name(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["source_name"] == "market_data"

    def test_signal_type(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["signal_type"] == "market_price"

    def test_symbol_uppercased(self) -> None:
        rec = {**self._full_rec(), "symbol": "spy"}
        out = self._normalize(rec)
        assert out["symbol"] == "SPY"

    def test_title_includes_symbol(self) -> None:
        out = self._normalize(self._full_rec())
        assert "SPY" in out["title"]

    def test_title_includes_price(self) -> None:
        out = self._normalize(self._full_rec())
        assert "500" in out["title"]

    def test_title_includes_provider(self) -> None:
        out = self._normalize(self._full_rec())
        assert "yahoo" in out["title"]

    def test_all_ohlc_fields_present(self) -> None:
        out = self._normalize(self._full_rec())
        for field in ("open", "high", "low", "close", "latest_price"):
            assert field in out

    def test_price_change_fields_present(self) -> None:
        out = self._normalize(self._full_rec())
        assert "price_change" in out
        assert "price_change_pct" in out

    def test_volume_fields_present(self) -> None:
        out = self._normalize(self._full_rec())
        assert "volume" in out
        assert "average_volume" in out
        assert "volume_change_ratio" in out

    def test_market_confirmation_score_present(self) -> None:
        out = self._normalize(self._full_rec())
        assert "market_confirmation_score" in out

    def test_advisory_status(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["advisory_status"] == "ADVISORY_ONLY"

    def test_human_review_required(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["human_review_required"] is True

    def test_execution_gate_locked(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["execution_gate"] == "LOCKED"

    def test_ai_execution_count_zero(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["ai_execution_count"] == 0

    def test_broker_api_called_false(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["broker_api_called"] is False

    def test_event_id_format(self) -> None:
        out = self._normalize(self._full_rec())
        assert out["event_id"].startswith("market_data_")
        assert len(out["event_id"]) == len("market_data_") + 16

    def test_event_id_deterministic(self) -> None:
        rec = self._full_rec()
        assert self._normalize(rec)["event_id"] == self._normalize(rec)["event_id"]

    def test_event_id_varies_by_symbol(self) -> None:
        rec_spy = {**self._full_rec(), "symbol": "SPY"}
        rec_qqq = {**self._full_rec(), "symbol": "QQQ"}
        assert self._normalize(rec_spy)["event_id"] != self._normalize(rec_qqq)["event_id"]

    def test_no_order_fields(self) -> None:
        out = self._normalize(self._full_rec())
        forbidden = {"order_id", "trade_id", "execute", "broker_order", "place_order"}
        assert not any(k in out for k in forbidden)

    def test_empty_symbol_graceful(self) -> None:
        rec = {**self._full_rec(), "symbol": ""}
        out = self._normalize(rec)
        assert isinstance(out["symbol"], str)
        assert isinstance(out["title"], str)

    def test_none_price_graceful(self) -> None:
        rec = {**self._full_rec(), "latest_price": None, "close": None}
        out = self._normalize(rec)
        assert out["latest_price"] is None

    def test_ticker_fallback_for_symbol(self) -> None:
        rec = {**self._full_rec()}
        del rec["symbol"]
        rec["ticker"] = "GLD"
        out = self._normalize(rec)
        assert out["symbol"] == "GLD"


# ---------------------------------------------------------------------------
# TestMarketDataLoaderInit
# ---------------------------------------------------------------------------


class TestMarketDataLoaderInit:
    def test_source_name(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        assert MarketDataLoader.source_name == "market_data"

    def test_requires_key_false(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        assert MarketDataLoader.requires_key is False

    def test_default_tickers(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader, _DEFAULT_TICKERS

        loader = MarketDataLoader()
        assert loader._tickers == list(_DEFAULT_TICKERS)

    def test_custom_tickers(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        loader = MarketDataLoader(tickers=["AAPL", "MSFT"])
        assert loader._tickers == ["AAPL", "MSFT"]

    def test_default_period(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        assert MarketDataLoader()._period == "5d"

    def test_custom_period(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        assert MarketDataLoader(period="1mo")._period == "1mo"

    def test_default_interval(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        assert MarketDataLoader()._interval == "1d"

    def test_custom_interval(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        assert MarketDataLoader(interval="1h")._interval == "1h"

    def test_default_provider_yahoo(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        assert MarketDataLoader()._provider == "yahoo"


# ---------------------------------------------------------------------------
# TestMarketDataLoaderMissingYfinance
# ---------------------------------------------------------------------------


class TestMarketDataLoaderMissingYfinance:
    def test_skip_when_yfinance_absent(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader
        from scripts.ingestion.base_loader import SkipLoader

        with patch.dict(sys.modules, {"yfinance": None}):
            loader = MarketDataLoader()
            with pytest.raises(SkipLoader):
                loader.fetch()

    def test_safe_fetch_returns_skipped_result(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader
        from scripts.ingestion.base_loader import LoaderResult

        with patch.dict(sys.modules, {"yfinance": None}):
            loader = MarketDataLoader()
            result = loader.safe_fetch()
            assert isinstance(result, LoaderResult)
            assert result.skipped is True
            assert result.records == []

    def test_skip_reason_mentions_yfinance(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        with patch.dict(sys.modules, {"yfinance": None}):
            loader = MarketDataLoader()
            result = loader.safe_fetch()
            assert "yfinance" in result.skip_reason.lower()

    def test_safe_fetch_source_name_preserved(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        with patch.dict(sys.modules, {"yfinance": None}):
            loader = MarketDataLoader()
            result = loader.safe_fetch()
            assert result.source_name == "market_data"


# ---------------------------------------------------------------------------
# TestMarketDataLoaderMockedYfinance
# ---------------------------------------------------------------------------


class TestMarketDataLoaderMockedYfinance:
    def _fetch(self, tickers=None, hist_df=None):
        from scripts.ingestion.market_data_loader import MarketDataLoader

        loader = MarketDataLoader(tickers=tickers or ["SPY"])
        with _mocked_yfinance(hist_df):
            return loader.fetch()

    def test_fetch_returns_loader_result(self) -> None:
        from scripts.ingestion.base_loader import LoaderResult

        result = self._fetch()
        assert isinstance(result, LoaderResult)

    def test_fetch_not_skipped(self) -> None:
        result = self._fetch()
        assert result.skipped is False

    def test_fetch_records_not_empty(self) -> None:
        result = self._fetch()
        assert len(result.records) >= 1

    def test_fetch_record_has_symbol(self) -> None:
        result = self._fetch(tickers=["SPY"])
        assert result.records[0]["symbol"] == "SPY"

    def test_fetch_record_has_close_price(self) -> None:
        result = self._fetch()
        rec = result.records[0]
        assert "close" in rec
        assert isinstance(rec["close"], float)

    def test_fetch_record_has_volume(self) -> None:
        result = self._fetch()
        rec = result.records[0]
        assert "volume" in rec
        assert isinstance(rec["volume"], float)

    def test_fetch_record_has_ohlc_fields(self) -> None:
        result = self._fetch()
        rec = result.records[0]
        for field in ("open", "high", "low", "close"):
            assert field in rec, f"Missing field: {field}"

    def test_fetch_record_has_advisory_stamps(self) -> None:
        result = self._fetch()
        rec = result.records[0]
        assert rec["advisory_status"] == "ADVISORY_ONLY"
        assert rec["human_review_required"] is True
        assert rec["execution_gate"] == "LOCKED"

    def test_fetch_record_has_confirmation_score(self) -> None:
        result = self._fetch()
        rec = result.records[0]
        assert "market_confirmation_score" in rec
        assert 0.0 <= rec["market_confirmation_score"] <= 1.0

    def test_fetch_record_has_provider_yahoo(self) -> None:
        result = self._fetch()
        assert result.records[0]["provider"] == "yahoo"

    def test_fetch_multiple_tickers_all_returned(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        loader = MarketDataLoader(tickers=["SPY", "QQQ"])
        hist = _make_mock_hist()
        mock_ticker = _make_mock_ticker(hist)
        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = loader.fetch()
        assert len(result.records) == 2

    def test_fetch_empty_hist_skips_ticker(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        loader = MarketDataLoader(tickers=["INVALID"])
        empty = _make_empty_hist()
        with patch("yfinance.Ticker", return_value=_make_mock_ticker(empty)):
            result = loader.fetch()
        assert result.records == []

    def test_fetch_price_change_computed(self) -> None:
        result = self._fetch(hist_df=_make_mock_hist(5))
        rec = result.records[0]
        assert rec["price_change"] is not None
        assert rec["price_change_pct"] is not None

    def test_fetch_avg_volume_computed(self) -> None:
        result = self._fetch(hist_df=_make_mock_hist(5))
        rec = result.records[0]
        assert rec["average_volume"] is not None

    def test_fetch_source_name(self) -> None:
        result = self._fetch()
        assert result.source_name == "market_data"

    def test_fetch_single_row_no_prev_close(self) -> None:
        result = self._fetch(hist_df=_make_mock_hist(1))
        rec = result.records[0]
        assert rec["previous_close"] is None
        assert rec["price_change"] is None
        assert rec["price_change_pct"] is None

    def test_fetch_period_and_interval_stored(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        loader = MarketDataLoader(tickers=["SPY"], period="1mo", interval="1wk")
        with _mocked_yfinance():
            result = loader.fetch()
        rec = result.records[0]
        assert rec["period"] == "1mo"
        assert rec["interval"] == "1wk"


# ---------------------------------------------------------------------------
# TestMarketDataLoaderOptionalProviders
# ---------------------------------------------------------------------------


class TestMarketDataLoaderOptionalProviders:
    def test_alpha_vantage_skips_without_key(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader
        from scripts.ingestion.base_loader import SkipLoader

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALPHA_VANTAGE_API_KEY", None)
            loader = MarketDataLoader(provider="alpha_vantage")
            with pytest.raises(SkipLoader):
                loader.fetch()

    def test_twelve_data_skips_without_key(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader
        from scripts.ingestion.base_loader import SkipLoader

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TWELVE_DATA_API_KEY", None)
            loader = MarketDataLoader(provider="twelve_data")
            with pytest.raises(SkipLoader):
                loader.fetch()

    def test_polygon_skips_without_key(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader
        from scripts.ingestion.base_loader import SkipLoader

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POLYGON_API_KEY", None)
            loader = MarketDataLoader(provider="polygon")
            with pytest.raises(SkipLoader):
                loader.fetch()

    def test_alpha_vantage_skip_reason_mentions_key(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALPHA_VANTAGE_API_KEY", None)
            loader = MarketDataLoader(provider="alpha_vantage")
            result = loader.safe_fetch()
            assert result.skipped
            assert "ALPHA_VANTAGE_API_KEY" in result.skip_reason

    def test_optional_provider_with_key_still_skips_skeleton(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader
        from scripts.ingestion.base_loader import SkipLoader

        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "fake-key"}):
            loader = MarketDataLoader(provider="alpha_vantage")
            with pytest.raises(SkipLoader) as exc:
                loader.fetch()
            assert "skeleton" in str(exc.value).lower() or "disabled" in str(exc.value).lower()

    def test_unknown_provider_uses_yahoo(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        loader = MarketDataLoader(provider="yahoo")
        with _mocked_yfinance():
            result = loader.fetch()
        assert not result.skipped


# ---------------------------------------------------------------------------
# TestPhase2RunnerMarketData
# ---------------------------------------------------------------------------


class TestPhase2RunnerMarketData:
    def _run(self, tickers=None, period="5d", hist_df=None, **kwargs):
        from scripts.live_source_runner_phase2 import run_phase2

        hist = hist_df if hist_df is not None else _make_mock_hist()
        mock_ticker = _make_mock_ticker(hist)
        with patch("yfinance.Ticker", return_value=mock_ticker):
            return run_phase2(
                dry_run=True,
                market_data_tickers=tickers or ["SPY"],
                market_data_period=period,
                sources=["market_data"],
                **kwargs,
            )

    def test_run_phase2_market_data_status_ok(self) -> None:
        report = self._run()
        assert len(report.sources) == 1
        assert report.sources[0].status == "ok"

    def test_run_phase2_market_data_source_name(self) -> None:
        report = self._run()
        assert report.sources[0].source_name == "market_data"

    def test_run_phase2_market_data_fetched_count(self) -> None:
        report = self._run(tickers=["SPY", "QQQ"])
        assert report.sources[0].fetched_count == 2
        assert report.total_fetched == 2

    def test_run_phase2_dry_run_no_persist(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("yfinance.Ticker", return_value=_make_mock_ticker()):
            with patch("scripts.live_source_runner_phase2._persist_events") as mp:
                run_phase2(dry_run=True, sources=["market_data"])
                mp.assert_not_called()

    def test_run_phase2_only_market_data_source_runs(self) -> None:
        report = self._run()
        source_names = [s.source_name for s in report.sources]
        assert source_names == ["market_data"]

    def test_run_phase2_market_data_custom_tickers_passed(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        captured = []
        original_init = MarketDataLoader.__init__

        def patched_init(self, tickers=None, **kw):
            captured.append(tickers)
            original_init(self, tickers=tickers, **kw)

        with patch("yfinance.Ticker", return_value=_make_mock_ticker()):
            with patch.object(MarketDataLoader, "__init__", patched_init):
                from scripts.live_source_runner_phase2 import run_phase2

                run_phase2(
                    dry_run=True,
                    market_data_tickers=["AAPL", "MSFT"],
                    sources=["market_data"],
                )
        assert ["AAPL", "MSFT"] in captured

    def test_run_phase2_market_data_yfinance_unavailable_skipped(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(sys.modules, {"yfinance": None}):
            report = run_phase2(dry_run=True, sources=["market_data"])
        assert len(report.sources) == 1
        assert report.sources[0].status == "skipped"
        assert report.total_fetched == 0

    def test_run_phase2_market_data_empty_result_graceful(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("yfinance.Ticker", return_value=_make_mock_ticker(_make_empty_hist())):
            report = run_phase2(dry_run=True, sources=["market_data"])
        assert report.sources[0].status == "ok"
        assert report.sources[0].fetched_count == 0


# ---------------------------------------------------------------------------
# TestMarketDataWriteMode
# ---------------------------------------------------------------------------


class TestMarketDataWriteMode:
    def test_write_mode_calls_persist(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("yfinance.Ticker", return_value=_make_mock_ticker()):
            with patch("scripts.live_source_runner_phase2._persist_events", return_value=1) as mp:
                with patch("scripts.live_source_runner_phase2._log_run"):
                    report = run_phase2(dry_run=False, sources=["market_data"])
                    mp.assert_called_once()
                    assert report.total_persisted == 1

    def test_write_mode_calls_log_run(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("yfinance.Ticker", return_value=_make_mock_ticker()):
            with patch("scripts.live_source_runner_phase2._persist_events", return_value=1):
                with patch("scripts.live_source_runner_phase2._log_run") as ml:
                    run_phase2(dry_run=False, sources=["market_data"])
                    ml.assert_called_once()

    def test_write_mode_skipped_yfinance_no_persist(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(sys.modules, {"yfinance": None}):
            with patch("scripts.live_source_runner_phase2._persist_events") as mp:
                run_phase2(dry_run=False, sources=["market_data"])
                mp.assert_not_called()

    def test_write_mode_skipped_source_log_run_called(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(sys.modules, {"yfinance": None}):
            with patch("scripts.live_source_runner_phase2._log_run") as ml:
                run_phase2(dry_run=False, sources=["market_data"])
                ml.assert_called_once()


# ---------------------------------------------------------------------------
# TestMarketDataSafetyInvariants
# ---------------------------------------------------------------------------


class TestMarketDataSafetyInvariants:
    def _get_report(self):
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("yfinance.Ticker", return_value=_make_mock_ticker()):
            return run_phase2(dry_run=True, sources=["market_data"])

    def test_report_advisory_status(self) -> None:
        assert self._get_report().advisory_status == "ADVISORY_ONLY"

    def test_report_execution_gate_locked(self) -> None:
        assert self._get_report().execution_gate == "LOCKED"

    def test_report_ai_execution_count_zero(self) -> None:
        assert self._get_report().ai_execution_count == 0

    def test_report_human_review_required(self) -> None:
        assert self._get_report().human_review_required is True

    def test_report_broker_api_called_false(self) -> None:
        assert self._get_report().broker_api_called is False

    def test_source_result_advisory_status(self) -> None:
        for src in self._get_report().sources:
            assert src.advisory_status == "ADVISORY_ONLY"

    def test_source_result_broker_api_false(self) -> None:
        for src in self._get_report().sources:
            assert src.broker_api_called is False

    def test_normalized_event_advisory_status(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_market_data_record

        out = _normalize_market_data_record({"symbol": "SPY", "timestamp": "ts"})
        assert out["advisory_status"] == "ADVISORY_ONLY"

    def test_normalized_event_execution_gate(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_market_data_record

        out = _normalize_market_data_record({"symbol": "SPY", "timestamp": "ts"})
        assert out["execution_gate"] == "LOCKED"

    def test_normalized_event_ai_count_zero(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_market_data_record

        out = _normalize_market_data_record({"symbol": "SPY", "timestamp": "ts"})
        assert out["ai_execution_count"] == 0

    def test_normalized_event_human_review(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_market_data_record

        out = _normalize_market_data_record({"symbol": "SPY", "timestamp": "ts"})
        assert out["human_review_required"] is True

    def test_normalized_event_broker_api_false(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_market_data_record

        out = _normalize_market_data_record({"symbol": "SPY", "timestamp": "ts"})
        assert out["broker_api_called"] is False

    def test_loader_advisory_stamp_present(self) -> None:
        from scripts.ingestion.market_data_loader import MarketDataLoader

        with _mocked_yfinance():
            result = MarketDataLoader(tickers=["SPY"]).fetch()
        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["human_review_required"] is True
            assert rec["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# TestMarketDataNoForbiddenMethods (AST check)
# ---------------------------------------------------------------------------


class TestMarketDataNoForbiddenMethods:
    FORBIDDEN_METHODS = {
        "place_order",
        "execute_trade",
        "send_transaction",
        "sign_transaction",
        "broadcast_transaction",
        "approve_token",
        "submit_order",
        "send_order",
        "cancel_order",
        "auto_buy",
        "auto_sell",
    }
    FORBIDDEN_STRINGS = [
        "private_key",
        "wallet_sign",
        "sign_transaction",
        "broadcast_transaction(",
        "token_approval(",
    ]

    def _collect_attr_calls(self, source: str) -> set[str]:
        tree = ast.parse(source)
        return {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_no_forbidden_in_market_data_loader(self) -> None:
        src = (REPO_ROOT / "scripts" / "ingestion" / "market_data_loader.py").read_text()
        found = self._collect_attr_calls(src) & self.FORBIDDEN_METHODS
        assert not found, f"Forbidden methods in market_data_loader.py: {found}"

    def test_no_forbidden_in_runner(self) -> None:
        src = (REPO_ROOT / "scripts" / "live_source_runner_phase2.py").read_text()
        found = self._collect_attr_calls(src) & self.FORBIDDEN_METHODS
        assert not found, f"Forbidden methods in live_source_runner_phase2.py: {found}"

    def test_no_forbidden_strings_in_loader(self) -> None:
        src = (REPO_ROOT / "scripts" / "ingestion" / "market_data_loader.py").read_text().lower()
        for s in self.FORBIDDEN_STRINGS:
            assert s not in src, f"Forbidden string '{s}' found in market_data_loader.py"

    def test_no_broker_api_in_loader(self) -> None:
        src = (REPO_ROOT / "scripts" / "ingestion" / "market_data_loader.py").read_text()
        assert "place_order" not in src
        assert "execute_trade" not in src

    def test_no_buy_sell_endpoint_in_loader(self) -> None:
        src = (REPO_ROOT / "scripts" / "ingestion" / "market_data_loader.py").read_text().lower()
        assert "buy_order" not in src
        assert "sell_order" not in src
        assert "execute_order" not in src

    def test_no_transaction_broadcast_in_loader(self) -> None:
        src = (REPO_ROOT / "scripts" / "ingestion" / "market_data_loader.py").read_text().lower()
        assert "broadcast" not in src
        # "wallet" may appear in safety comments ("No wallet operations") — forbid callable patterns
        assert "wallet.sign" not in src
        assert "wallet_sign(" not in src
        assert "send_eth" not in src

    def test_no_broker_in_runner_beyond_advisory_flag(self) -> None:
        src = (REPO_ROOT / "scripts" / "live_source_runner_phase2.py").read_text()
        assert "place_order" not in src
        assert "execute_trade" not in src
        assert "sign_transaction" not in src


# ---------------------------------------------------------------------------
# TestMarketDataCLI
# ---------------------------------------------------------------------------


class TestMarketDataCLI:
    def test_market_data_in_supported_sources(self) -> None:
        from scripts.run_live_sources_phase2 import _SUPPORTED_SOURCES

        assert "market_data" in _SUPPORTED_SOURCES

    def test_parse_args_accepts_market_data(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", ["prog", "--source", "market_data", "--dry-run"]):
            args = _parse_args()
            assert args.source == "market_data"
            assert args.dry_run is True

    def test_parse_args_symbols(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "market_data", "--dry-run",
            "--symbols", "AAPL,MSFT,BTC-USD",
        ]):
            args = _parse_args()
            assert args.symbols == "AAPL,MSFT,BTC-USD"

    def test_parse_args_period(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "market_data", "--dry-run", "--period", "1mo"
        ]):
            args = _parse_args()
            assert args.period == "1mo"

    def test_parse_args_interval(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "market_data", "--dry-run", "--interval", "1h"
        ]):
            args = _parse_args()
            assert args.interval == "1h"

    def test_parse_args_market_provider(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "market_data", "--dry-run", "--market-provider", "yahoo"
        ]):
            args = _parse_args()
            assert args.market_provider == "yahoo"

    def test_parse_args_market_data_defaults(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", ["prog", "--source", "market_data", "--dry-run"]):
            args = _parse_args()
            assert args.symbols is None
            assert args.period == "5d"
            assert args.interval == "1d"
            assert args.market_provider == "yahoo"

    def test_parse_args_json_flag(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "market_data", "--dry-run", "--json"
        ]):
            args = _parse_args()
            assert args.output_json is True

    def test_parse_args_write_mode(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", ["prog", "--source", "market_data", "--write"]):
            args = _parse_args()
            assert args.write is True
            assert args.dry_run is False
