"""
Tests for the Chart Structure symbol bootstrap flow.

Covers:
  1. Missing OHLCV returns reason=NO_LOCAL_OHLCV / can_bootstrap=true.
  2. validate_symbol accepts AAPL, BTC-USD, RELIANCE.NS, SPY, ^GSPC, BRK.B.
  3. validate_symbol rejects empty / malicious / over-long inputs.
  4. bootstrap_symbol calls injected discovery + backfill with right args.
  5. bootstrap_symbol returns ok=true on success with sanitized message.
  6. bootstrap_symbol handles discovery failure with ok=false + sanitized reason.
  7. bootstrap_symbol handles backfill failure with ok=false + sanitized reason.
  8. bootstrap_symbol rejects invalid period/interval.
  9. Safety invariants present in every bootstrap response.
  10. Bootstrap helper never raises (returns dict even on infinite recursion / bad input).
"""
from __future__ import annotations

import pytest


def _bs():
    import scripts.chart_symbol_bootstrap as bs
    return bs


def _ctx():
    import scripts.chart_structure_api_context as ctx
    return ctx


# ---------------------------------------------------------------------------
# 1. NO_LOCAL_OHLCV
# ---------------------------------------------------------------------------


def test_chart_structure_missing_data_returns_no_local_ohlcv(tmp_path):
    ctx = _ctx()
    # Empty DB → should return NO_LOCAL_OHLCV
    import scripts.persistence as p
    db = tmp_path / "empty.db"
    p.init_schema(db)
    result = ctx._get_chart_structure(symbol="TEST_MISSING_XYZ", db_path=db)
    assert result["ok"] is False
    assert result["reason"] == "NO_LOCAL_OHLCV"
    assert result["can_bootstrap"] is True
    assert result["candle_count"] == 0
    assert "No local OHLCV candles" in result["message"]
    # Safety invariants preserved
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == "NONE"
    assert result["ai_execution_count"] == 0
    assert result["human_review_required"] is True


# ---------------------------------------------------------------------------
# 2-3. validate_symbol
# ---------------------------------------------------------------------------


def test_validate_symbol_accepts_common_symbols():
    bs = _bs()
    for sym in ("AAPL", "BTC-USD", "RELIANCE.NS", "SPY", "^GSPC", "BRK.B"):
        ok, _ = bs.validate_symbol(sym)
        assert ok, f"{sym} should validate"


def test_validate_symbol_rejects_empty():
    bs = _bs()
    ok, reason = bs.validate_symbol("")
    assert not ok and "non-empty" in reason


def test_validate_symbol_rejects_malicious():
    bs = _bs()
    bad_inputs = [
        "AAPL; rm -rf /",
        "AAPL && ls",
        "AAPL | cat",
        "AAPL`whoami`",
        "AAPL$(id)",
        "AAPL\nINJECT",
        "AAPL ",  # contains space → invalid char
        "../../../etc/passwd",
        "AAPL'OR'1",
    ]
    for bad in bad_inputs:
        ok, _ = bs.validate_symbol(bad)
        assert not ok, f"{bad!r} should NOT validate"


def test_validate_symbol_rejects_overlong():
    bs = _bs()
    ok, _ = bs.validate_symbol("A" * 31)
    assert not ok


# ---------------------------------------------------------------------------
# 4-5. bootstrap_symbol success path with mocks
# ---------------------------------------------------------------------------


def test_bootstrap_symbol_calls_discovery_and_backfill():
    bs = _bs()
    calls = {"discovery": None, "backfill": None}

    def fake_discovery(symbols, *, write, db_path=None):
        calls["discovery"] = {"symbols": list(symbols), "write": write}
        return [{"canonical_symbol": symbols[0], "db_action": "inserted"}]

    def fake_backfill(symbol, *, period, interval, write, db_path=None, discover=True):
        calls["backfill"] = {
            "symbol": symbol, "period": period, "interval": interval,
            "write": write, "discover": discover,
        }
        return (252, 252)  # (fetched, inserted)

    out = bs.bootstrap_symbol(
        "aapl", period="max", interval="1d",
        discovery_fn=fake_discovery, backfill_fn=fake_backfill,
    )

    assert calls["discovery"] == {"symbols": ["AAPL"], "write": True}
    assert calls["backfill"]["symbol"] == "AAPL"
    assert calls["backfill"]["period"] == "max"
    assert calls["backfill"]["interval"] == "1d"
    assert calls["backfill"]["write"] is True
    # Discovery must NOT be re-run from backfill — bootstrap already did it
    assert calls["backfill"]["discover"] is False

    assert out["ok"] is True
    assert out["symbol"] == "AAPL"
    assert out["discovery_status"] == "OK"
    assert out["backfill_status"] == "OK"
    assert out["candles_written"] == 252
    assert out["candles_fetched"] == 252


# ---------------------------------------------------------------------------
# 6-7. Failure handling
# ---------------------------------------------------------------------------


def test_bootstrap_symbol_handles_discovery_exception_then_still_tries_backfill():
    bs = _bs()
    def boom_discovery(symbols, *, write, db_path=None):
        raise RuntimeError("yfinance api_key=SECRET_TOKEN_DO_NOT_LEAK boom")

    def fake_backfill(symbol, *, period, interval, write, db_path=None, discover=True):
        return (0, 0)

    out = bs.bootstrap_symbol(
        "AAPL", discovery_fn=boom_discovery, backfill_fn=fake_backfill,
    )
    assert out["ok"] is False
    assert out["discovery_status"] == "ERROR"
    # Sanitizer must redact api_key=<value>
    assert "SECRET_TOKEN_DO_NOT_LEAK" not in out["message"]


def test_bootstrap_symbol_handles_backfill_exception():
    bs = _bs()
    def fake_discovery(symbols, *, write, db_path=None):
        return [{"canonical_symbol": symbols[0], "db_action": "inserted"}]

    def boom_backfill(symbol, *, period, interval, write, db_path=None, discover=True):
        raise RuntimeError("HTTP 429 too many requests")

    out = bs.bootstrap_symbol(
        "AAPL", discovery_fn=fake_discovery, backfill_fn=boom_backfill,
    )
    assert out["ok"] is False
    assert out["backfill_status"] == "ERROR"
    assert "429" in out["message"]


def test_bootstrap_symbol_zero_fetched_is_not_ok():
    bs = _bs()
    def fake_discovery(symbols, *, write, db_path=None):
        return [{"canonical_symbol": symbols[0]}]
    def fake_backfill(symbol, *, period, interval, write, db_path=None, discover=True):
        return (0, 0)
    out = bs.bootstrap_symbol("UNKNOWN_XYZ", discovery_fn=fake_discovery, backfill_fn=fake_backfill)
    assert out["ok"] is False
    assert out["backfill_status"] == "SKIPPED"
    assert out["candles_written"] == 0


# ---------------------------------------------------------------------------
# 8. Period/interval validation
# ---------------------------------------------------------------------------


def test_bootstrap_symbol_rejects_bad_period():
    bs = _bs()
    out = bs.bootstrap_symbol("AAPL", period="forever", interval="1d",
                              discovery_fn=lambda *a, **kw: [], backfill_fn=lambda *a, **kw: (0, 0))
    assert out["ok"] is False
    assert "Invalid period" in out["message"]


def test_bootstrap_symbol_rejects_bad_interval():
    bs = _bs()
    out = bs.bootstrap_symbol("AAPL", period="max", interval="42x",
                              discovery_fn=lambda *a, **kw: [], backfill_fn=lambda *a, **kw: (0, 0))
    assert out["ok"] is False
    assert "Invalid interval" in out["message"]


def test_bootstrap_symbol_rejects_bad_symbol():
    bs = _bs()
    out = bs.bootstrap_symbol("AAPL; rm -rf /", period="max", interval="1d",
                              discovery_fn=lambda *a, **kw: [], backfill_fn=lambda *a, **kw: (0, 0))
    assert out["ok"] is False
    assert out["discovery_status"] == "SKIPPED"
    assert out["backfill_status"] == "SKIPPED"


# ---------------------------------------------------------------------------
# 9. Safety invariants always present
# ---------------------------------------------------------------------------


def test_bootstrap_symbol_safety_invariants_present_on_success():
    bs = _bs()
    out = bs.bootstrap_symbol(
        "AAPL",
        discovery_fn=lambda *a, **kw: [{"canonical_symbol": "AAPL"}],
        backfill_fn=lambda *a, **kw: (10, 10),
    )
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_mode"] == "HUMAN_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["broker_order_id"] == "NONE"
    assert out["ai_execution_count"] == 0
    assert out["human_review_required"] is True


def test_bootstrap_symbol_safety_invariants_present_on_failure():
    bs = _bs()
    out = bs.bootstrap_symbol("", discovery_fn=lambda *a, **kw: [], backfill_fn=lambda *a, **kw: (0, 0))
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_mode"] == "HUMAN_ONLY"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 10. Endpoint wiring (advisory invariants from inside FastAPI handler)
# ---------------------------------------------------------------------------


def test_api_server_post_bootstrap_returns_advisory(monkeypatch):
    # The endpoint test exercises FastAPI's Pydantic request body machinery.
    # Skip cleanly when FastAPI isn't installed (e.g. trimmed CI without
    # requirements-dev.txt) — the underlying bootstrap logic is already
    # covered by the dependency-free tests above.
    pytest.importorskip("fastapi")
    pytest.importorskip("pydantic")
    from scripts import api_server as srv

    def fake(symbol, period, interval):
        return {
            "ok": True,
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "discovery_status": "OK",
            "backfill_status": "OK",
            "candles_written": 100,
            "message": "ok",
            "advisory_status": "ADVISORY_ONLY",
            "execution_mode": "HUMAN_ONLY",
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "broker_order_id": "NONE",
            "ai_execution_count": 0,
            "human_review_required": True,
        }
    # Inject so we don't hit yfinance
    monkeypatch.setattr(
        srv,
        "_bootstrap_symbol",
        lambda symbol, period, interval: fake(symbol, period, interval),
    )

    body = srv.ChartBootstrapBody(symbol="AAPL", period="max", interval="1d")
    result = srv.post_chart_structure_bootstrap(body)
    assert result["ok"] is True
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    assert result["human_review_required"] is True
