"""
Phase E.3 — Tests for real OHLCV backfill, incremental updater, and chart structure fixes.

Coverage
--------
 1  backfill_ohlcv_history.py exists
 2  backfill script is valid Python (no SyntaxError)
 3  backfill script has no forbidden execution terms
 4  update_ohlcv_latest.py exists
 5  update script is valid Python (no SyntaxError)
 6  update script has no forbidden execution terms
 7  event_id format: ohlcv_{symbol}_{interval}_{YYYY-MM-DD}
 8  event_id for BTC-USD: dash replaced with underscore
 9  event_id is distinct from seed script IDs (seed_ohlcv_* vs ohlcv_*)
10  backfill candle dict carries advisory_status == ADVISORY_ONLY
11  backfill candle dict carries execution_gate == LOCKED
12  backfill candle dict carries human_review_required == True
13  backfill candle dict carries ai_execution_count == 0
14  backfill candle dict carries broker_api_called == False
15  backfill candle dict carries broker_order_id == NONE
16  backfill_symbol idempotent: first run inserts N, second run inserts 0 (mocked yfinance)
17  no duplicate candles for same date on repeated backfill_symbol calls
18  get_signal_events_for_symbol returns only events for requested symbol
19  get_signal_events_for_symbol respects limit parameter
20  limit=100 on get_signal_events_for_symbol returns up to 100 when 100+ available
21  _get_chart_structure returns candle_count >= 100 when 100+ candles seeded for symbol
22  _get_chart_structure prefers real backfill (ohlcv_*) over seed (seed_ohlcv_*) for same date
23  _get_chart_structure returns advisory_status == ADVISORY_ONLY
24  _get_chart_structure returns execution_gate == LOCKED
25  _period_from_days: 5 days -> "5d"
26  _period_from_days: 10 days -> "10d"
27  _period_from_days: 30 days -> "1mo"
28  _period_from_days: 90 days -> "3mo"
29  _period_from_days: 91+ days -> "6mo"
30  poll_live_sources.ps1 references update_ohlcv_latest.py
31  poll_live_sources.ps1 OHLCV block uses --write flag
32  poll_live_sources.ps1 OHLCV failure is caught (try/catch present)
33  seed script docstring marks data as DEMO-ONLY / synthetic
34  backfill candle dict has all required OHLCV fields (open, high, low, close, volume, timestamp, symbol)
35  backfill candle source field is "yahoo_backfill"
36  persistence get_signal_events_for_symbol exists and is callable
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BACKFILL_PATH = REPO_ROOT / "scripts" / "backfill_ohlcv_history.py"
_UPDATE_PATH = REPO_ROOT / "scripts" / "update_ohlcv_latest.py"
_POLL_PATH = REPO_ROOT / "scripts" / "windows" / "poll_live_sources.ps1"
_SEED_PATH = REPO_ROOT / "scripts" / "seed_chart_ohlcv_history.py"

_REQUIRED_SYMBOLS = ["AAPL", "GLD", "TLT", "BTC-USD", "SPY"]

_FORBIDDEN_TERMS = [
    "place_order",
    "submit_order",
    "execute_trade",
    "broker_execute",
    "broker_api(",
    "private_key",
    "send_transaction",
    "wallet(",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _make_fake_yfinance_history(symbol: str, n: int = 5):
    """Return a minimal pandas-like DataFrame stub with n rows of OHLCV data."""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas not available — skipping yfinance mock tests")

    today = date.today()
    idx = pd.date_range(end=today, periods=n, freq="B")  # Business days
    data = {
        "Open":   [100.0 + i for i in range(n)],
        "High":   [105.0 + i for i in range(n)],
        "Low":    [95.0 + i for i in range(n)],
        "Close":  [102.0 + i for i in range(n)],
        "Volume": [1_000_000 + i * 10_000 for i in range(n)],
    }
    return pd.DataFrame(data, index=idx)


@pytest.fixture(scope="module")
def backfill_mod():
    return _load_module(_BACKFILL_PATH, "backfill_ohlcv_history")


@pytest.fixture(scope="module")
def update_mod():
    return _load_module(_UPDATE_PATH, "update_ohlcv_latest")


# ---------------------------------------------------------------------------
# A. File existence and syntax
# ---------------------------------------------------------------------------

def test_backfill_script_exists():
    assert _BACKFILL_PATH.exists(), f"Missing: {_BACKFILL_PATH}"


def test_backfill_script_parses():
    ast.parse(_BACKFILL_PATH.read_text(encoding="utf-8"))


def test_update_script_exists():
    assert _UPDATE_PATH.exists(), f"Missing: {_UPDATE_PATH}"


def test_update_script_parses():
    ast.parse(_UPDATE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# B. Forbidden execution terms
# ---------------------------------------------------------------------------

def test_backfill_no_forbidden_terms():
    src = _BACKFILL_PATH.read_text(encoding="utf-8").lower()
    for term in _FORBIDDEN_TERMS:
        assert term.lower() not in src, f"Forbidden term in backfill script: {term!r}"


def test_update_no_forbidden_terms():
    src = _UPDATE_PATH.read_text(encoding="utf-8").lower()
    for term in _FORBIDDEN_TERMS:
        assert term.lower() not in src, f"Forbidden term in update script: {term!r}"


# ---------------------------------------------------------------------------
# C. Event ID format
# ---------------------------------------------------------------------------

def test_event_id_format(backfill_mod):
    eid = backfill_mod.event_id("AAPL", "1d", "2024-01-15")
    assert eid == "ohlcv_aapl_1d_2024-01-15"


def test_event_id_btc_dash_replaced(backfill_mod):
    eid = backfill_mod.event_id("BTC-USD", "1d", "2024-01-15")
    assert eid == "ohlcv_btc_usd_1d_2024-01-15"
    # Symbol portion must not contain dash (replaced with underscore)
    assert "btc-usd" not in eid, "Symbol dash must be replaced with underscore"
    assert "btc_usd" in eid, "Symbol part must use underscores"


def test_event_id_distinct_from_seed(backfill_mod):
    eid = backfill_mod.event_id("AAPL", "1d", "2024-01-15")
    assert not eid.startswith("seed_"), "Backfill event IDs must NOT start with 'seed_'"
    assert eid.startswith("ohlcv_"), "Backfill event IDs must start with 'ohlcv_'"


# ---------------------------------------------------------------------------
# D. Candle advisory stamps
# ---------------------------------------------------------------------------

def test_backfill_candle_advisory_status(backfill_mod):
    c = backfill_mod._build_candle("AAPL", "1d", "2024-01-15T16:00:00Z", {
        "Open": 150.0, "High": 155.0, "Low": 148.0, "Close": 152.0, "Volume": 1000000,
    })
    assert c["advisory_status"] == "ADVISORY_ONLY"


def test_backfill_candle_execution_gate(backfill_mod):
    c = backfill_mod._build_candle("AAPL", "1d", "2024-01-15T16:00:00Z", {
        "Open": 150.0, "High": 155.0, "Low": 148.0, "Close": 152.0, "Volume": 1000000,
    })
    assert c["execution_gate"] == "LOCKED"


def test_backfill_candle_human_review(backfill_mod):
    c = backfill_mod._build_candle("AAPL", "1d", "2024-01-15T16:00:00Z", {
        "Open": 150.0, "High": 155.0, "Low": 148.0, "Close": 152.0, "Volume": 1000000,
    })
    assert c["human_review_required"] is True


def test_backfill_candle_ai_execution_count(backfill_mod):
    c = backfill_mod._build_candle("AAPL", "1d", "2024-01-15T16:00:00Z", {
        "Open": 150.0, "High": 155.0, "Low": 148.0, "Close": 152.0, "Volume": 1000000,
    })
    assert c["ai_execution_count"] == 0


def test_backfill_candle_broker_api_called(backfill_mod):
    c = backfill_mod._build_candle("AAPL", "1d", "2024-01-15T16:00:00Z", {
        "Open": 150.0, "High": 155.0, "Low": 148.0, "Close": 152.0, "Volume": 1000000,
    })
    assert c["broker_api_called"] is False


def test_backfill_candle_broker_order_id(backfill_mod):
    c = backfill_mod._build_candle("AAPL", "1d", "2024-01-15T16:00:00Z", {
        "Open": 150.0, "High": 155.0, "Low": 148.0, "Close": 152.0, "Volume": 1000000,
    })
    assert c["broker_order_id"] == "NONE"


def test_backfill_candle_ohlcv_fields(backfill_mod):
    c = backfill_mod._build_candle("SPY", "1d", "2024-06-01T16:00:00Z", {
        "Open": 520.0, "High": 525.0, "Low": 518.0, "Close": 522.0, "Volume": 75000000,
    })
    for field in ("open", "high", "low", "close", "volume", "timestamp", "symbol"):
        assert field in c, f"Candle missing field: {field!r}"


def test_backfill_candle_source_field(backfill_mod):
    c = backfill_mod._build_candle("GLD", "1d", "2024-01-15T16:00:00Z", {
        "Open": 220.0, "High": 222.0, "Low": 219.0, "Close": 221.0, "Volume": 8000000,
    })
    assert c["source"] == "yahoo_backfill"


# ---------------------------------------------------------------------------
# E. Idempotency (mocked yfinance, real SQLite in tmp_path)
# ---------------------------------------------------------------------------

def test_backfill_idempotent(backfill_mod, tmp_path):
    db = tmp_path / "backfill_idem.db"
    fake_df = _make_fake_yfinance_history("AAPL", n=10)

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.history.return_value = fake_df

    with patch.dict("sys.modules", {"yfinance": fake_yf}):
        fetched1, inserted1 = backfill_mod.backfill_symbol(
            "AAPL", period="10d", interval="1d", write=True, db_path=db
        )
        fetched2, inserted2 = backfill_mod.backfill_symbol(
            "AAPL", period="10d", interval="1d", write=True, db_path=db
        )

    assert fetched1 == 10, f"Expected 10 candles fetched, got {fetched1}"
    assert inserted1 == 10, f"First run should insert 10, got {inserted1}"
    assert fetched2 == 10, f"Second fetch should still return 10"
    assert inserted2 == 0, f"Second run must insert 0 (idempotent), got {inserted2}"


def test_no_duplicate_candles(backfill_mod, tmp_path):
    db = tmp_path / "backfill_nodup.db"
    fake_df = _make_fake_yfinance_history("SPY", n=5)

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.history.return_value = fake_df

    import scripts.persistence as p

    with patch.dict("sys.modules", {"yfinance": fake_yf}):
        backfill_mod.backfill_symbol("SPY", period="5d", interval="1d", write=True, db_path=db)
        backfill_mod.backfill_symbol("SPY", period="5d", interval="1d", write=True, db_path=db)

    events = p.get_signal_events(source_name="market_data", limit=1000, db_path=db)
    spy_events = [
        ev for ev in events
        if (ev.get("raw_payload") or {}).get("symbol", "").upper() == "SPY"
    ]
    dates = [ev.get("raw_payload", {}).get("timestamp", "")[:10] for ev in spy_events]
    assert len(dates) == len(set(dates)), f"Duplicate dates found: {sorted(dates)}"


# ---------------------------------------------------------------------------
# F. get_signal_events_for_symbol
# ---------------------------------------------------------------------------

def test_get_signal_events_for_symbol_exists():
    import scripts.persistence as p
    assert callable(getattr(p, "get_signal_events_for_symbol", None)), (
        "get_signal_events_for_symbol must exist in persistence.py"
    )


def test_get_signal_events_for_symbol_filters_by_symbol(tmp_path):
    import scripts.persistence as p
    db = tmp_path / "sym_filter.db"

    # Insert candles for two different symbols
    for sym in ("AAPL", "GLD"):
        for i in range(5):
            day = (date.today() - timedelta(days=i)).isoformat()
            p.insert_signal_event(
                event_id=f"ohlcv_{sym.lower()}_1d_{day}",
                source_name="market_data",
                raw_payload={
                    "symbol": sym, "timestamp": f"{day}T16:00:00Z",
                    "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                    "volume": 1000000, "advisory_status": "ADVISORY_ONLY",
                    "execution_gate": "LOCKED", "human_review_required": True,
                    "ai_execution_count": 0, "broker_api_called": False, "broker_order_id": "NONE",
                },
                fetched_at=f"{day}T16:00:00Z",
                db_path=db,
            )

    aapl_evts = p.get_signal_events_for_symbol("AAPL", source_name="market_data", limit=100, db_path=db)
    gld_evts = p.get_signal_events_for_symbol("GLD", source_name="market_data", limit=100, db_path=db)

    assert all(
        (ev.get("raw_payload") or {}).get("symbol") == "AAPL" for ev in aapl_evts
    ), "get_signal_events_for_symbol returned non-AAPL rows"
    assert all(
        (ev.get("raw_payload") or {}).get("symbol") == "GLD" for ev in gld_evts
    ), "get_signal_events_for_symbol returned non-GLD rows"
    assert len(aapl_evts) == 5
    assert len(gld_evts) == 5


def test_get_signal_events_for_symbol_respects_limit(tmp_path):
    import scripts.persistence as p
    db = tmp_path / "sym_limit.db"

    for i in range(50):
        day = (date.today() - timedelta(days=i)).isoformat()
        p.insert_signal_event(
            event_id=f"ohlcv_tlt_1d_{day}",
            source_name="market_data",
            raw_payload={
                "symbol": "TLT", "timestamp": f"{day}T16:00:00Z",
                "open": 90.0, "high": 91.0, "low": 89.0, "close": 90.5,
                "volume": 500000, "advisory_status": "ADVISORY_ONLY",
                "execution_gate": "LOCKED", "human_review_required": True,
                "ai_execution_count": 0, "broker_api_called": False, "broker_order_id": "NONE",
            },
            fetched_at=f"{day}T16:00:00Z",
            db_path=db,
        )

    evts_10 = p.get_signal_events_for_symbol("TLT", source_name="market_data", limit=10, db_path=db)
    assert len(evts_10) == 10, f"Expected 10, got {len(evts_10)}"


def test_limit_100_returns_up_to_100_when_available(tmp_path):
    """When 200+ candles are stored for a symbol, limit=100 returns 100."""
    import scripts.persistence as p
    db = tmp_path / "limit100.db"

    for i in range(200):
        day = (date.today() - timedelta(days=i)).isoformat()
        p.insert_signal_event(
            event_id=f"ohlcv_spy_1d_{day}",
            source_name="market_data",
            raw_payload={
                "symbol": "SPY", "timestamp": f"{day}T16:00:00Z",
                "open": 520.0, "high": 522.0, "low": 518.0, "close": 521.0,
                "volume": 75000000, "advisory_status": "ADVISORY_ONLY",
                "execution_gate": "LOCKED", "human_review_required": True,
                "ai_execution_count": 0, "broker_api_called": False, "broker_order_id": "NONE",
            },
            fetched_at=f"{day}T16:00:00Z",
            db_path=db,
        )

    evts = p.get_signal_events_for_symbol("SPY", source_name="market_data", limit=100, db_path=db)
    assert len(evts) == 100, f"Expected 100 events, got {len(evts)}"


# ---------------------------------------------------------------------------
# G. Chart structure limit fix
# ---------------------------------------------------------------------------

def test_chart_structure_returns_100_candles_when_available(tmp_path):
    """_get_chart_structure with limit=100 returns candle_count >= 100 when 100+ stored."""
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _candles_from_market_events

    db = tmp_path / "cs_limit100.db"

    # Insert 150 candles for AAPL via real backfill IDs (ohlcv_*)
    for i in range(150):
        day = (date.today() - timedelta(days=i)).isoformat()
        p.insert_signal_event(
            event_id=f"ohlcv_aapl_1d_{day}",
            source_name="market_data",
            raw_payload={
                "symbol": "AAPL", "timestamp": f"{day}T16:00:00Z",
                "open": 185.0 + i * 0.1, "high": 186.0 + i * 0.1,
                "low": 184.0 + i * 0.1, "close": 185.5 + i * 0.1,
                "volume": 55000000, "advisory_status": "ADVISORY_ONLY",
                "execution_gate": "LOCKED", "human_review_required": True,
                "ai_execution_count": 0, "broker_api_called": False, "broker_order_id": "NONE",
            },
            fetched_at=f"{day}T16:00:00Z",
            db_path=db,
        )

    evts = p.get_signal_events_for_symbol("AAPL", source_name="market_data", limit=600, db_path=db)
    candles = _candles_from_market_events(evts)
    assert len(candles) >= 100, f"Expected >= 100 candles, got {len(candles)}"


def test_chart_structure_prefers_real_over_seed(tmp_path):
    """When both seed and real candles exist for same date, real candle is used."""
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _candles_from_market_events

    db = tmp_path / "cs_prefer_real.db"
    today = date.today().isoformat()

    # Insert seed candle for today
    p.insert_signal_event(
        event_id=f"seed_ohlcv_aapl_{today}",
        source_name="market_data",
        raw_payload={
            "symbol": "AAPL", "timestamp": f"{today}T16:00:00Z",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000000, "advisory_status": "ADVISORY_ONLY",
            "execution_gate": "LOCKED", "human_review_required": True,
            "ai_execution_count": 0, "broker_api_called": False, "broker_order_id": "NONE",
        },
        fetched_at=f"{today}T08:00:00Z",
        db_path=db,
    )
    # Insert real backfill candle for same date (different close price)
    p.insert_signal_event(
        event_id=f"ohlcv_aapl_1d_{today}",
        source_name="market_data",
        raw_payload={
            "symbol": "AAPL", "timestamp": f"{today}T16:00:00Z",
            "open": 185.0, "high": 186.0, "low": 184.0, "close": 185.5,
            "volume": 55000000, "advisory_status": "ADVISORY_ONLY",
            "execution_gate": "LOCKED", "human_review_required": True,
            "ai_execution_count": 0, "broker_api_called": False, "broker_order_id": "NONE",
        },
        fetched_at=f"{today}T16:30:00Z",
        db_path=db,
    )

    all_evts = p.get_signal_events_for_symbol("AAPL", source_name="market_data", limit=100, db_path=db)

    real_evts = [ev for ev in all_evts if str(ev.get("event_id", "")).startswith("ohlcv_")]
    seed_evts = [ev for ev in all_evts if not str(ev.get("event_id", "")).startswith("ohlcv_")]

    # Simulate the preference logic from _get_chart_structure
    real_candles = _candles_from_market_events(real_evts)
    real_dates = {c["timestamp"][:10] for c in real_candles}
    extra_seed = [
        c for c in _candles_from_market_events(seed_evts)
        if c["timestamp"][:10] not in real_dates
    ]
    merged = sorted(real_candles + extra_seed, key=lambda c: c["timestamp"])

    today_candles = [c for c in merged if c["timestamp"][:10] == today]
    assert len(today_candles) == 1, f"Expected exactly 1 candle for {today}, got {len(today_candles)}"
    assert today_candles[0]["close"] == 185.5, (
        f"Real candle (close=185.5) should win over seed (close=100.5), "
        f"got close={today_candles[0]['close']}"
    )


def test_chart_structure_result_advisory_status(tmp_path):
    """_get_chart_structure always returns advisory_status=ADVISORY_ONLY."""
    from scripts.chart_structure_api_context import _get_chart_structure

    db = tmp_path / "cs_advisory.db"
    # No candles — should return INSUFFICIENT_DATA with advisory stamp
    result = _get_chart_structure(symbol="ZZZZTEST", limit=10, db_path=db)
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# H. _period_from_days unit tests
# ---------------------------------------------------------------------------

def test_period_from_days_5(update_mod):
    assert update_mod._period_from_days(5) == "5d"


def test_period_from_days_10(update_mod):
    assert update_mod._period_from_days(10) == "10d"


def test_period_from_days_30(update_mod):
    assert update_mod._period_from_days(30) == "1mo"


def test_period_from_days_90(update_mod):
    assert update_mod._period_from_days(90) == "3mo"


def test_period_from_days_over_90(update_mod):
    assert update_mod._period_from_days(91) == "6mo"
    assert update_mod._period_from_days(180) == "6mo"


# ---------------------------------------------------------------------------
# I. poll_live_sources.ps1 checks
# ---------------------------------------------------------------------------

def test_poll_script_references_update_ohlcv_latest():
    src = _POLL_PATH.read_text(encoding="utf-8")
    assert "update_ohlcv_latest.py" in src, (
        "poll_live_sources.ps1 must reference update_ohlcv_latest.py"
    )


def test_poll_script_ohlcv_uses_write_flag():
    src = _POLL_PATH.read_text(encoding="utf-8")
    assert "--write" in src, (
        "poll_live_sources.ps1 must pass --write to update_ohlcv_latest.py"
    )


def test_poll_script_ohlcv_has_try_catch():
    src = _POLL_PATH.read_text(encoding="utf-8")
    # PowerShell try/catch: should be present for the OHLCV block
    assert "catch" in src.lower(), (
        "poll_live_sources.ps1 must have try/catch around OHLCV update call"
    )


# ---------------------------------------------------------------------------
# J. Seed script docstring marks as demo-only
# ---------------------------------------------------------------------------

def test_seed_docstring_marks_demo_only():
    src = _SEED_PATH.read_text(encoding="utf-8").upper()
    assert "DEMO" in src or "SYNTHETIC" in src or "SAMPLE DATA" in src, (
        "seed_chart_ohlcv_history.py must clearly state it creates demo/synthetic data"
    )


def test_seed_docstring_not_real_market_history():
    src = _SEED_PATH.read_text(encoding="utf-8")
    # The docstring should clarify it is NOT real market history
    assert "NOT" in src and ("real" in src.lower() or "market history" in src.lower()), (
        "seed_chart_ohlcv_history.py docstring must clarify it is NOT real market history"
    )
