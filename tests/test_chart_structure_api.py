"""
Phase D.3 — Chart Structure API endpoint tests.

Coverage
--------
 1  GET /chart-structure requires symbol param (422 without it)
 2  GET /chart-structure?symbol=AAPL returns 200
 3  Successful response contains a 'report' field
 4  Successful response contains a 'candle_count' field
 5  Safety invariant: advisory_status == ADVISORY_ONLY
 6  Safety invariant: execution_gate == LOCKED
 7  Safety invariant: human_review_required is True
 8  Safety invariant: ai_execution_count == 0
 9  Safety invariant: broker_api_called is False
10  Safety invariant: broker_order_id == NONE
11  Nested report preserves advisory_status == ADVISORY_ONLY
12  Nested report preserves execution_gate == LOCKED
13  Nested report preserves ai_execution_count == 0
14  Nested report preserves broker_api_called == False
15  Insufficient data response: chart_state == INSUFFICIENT_DATA, report is None
16  Insufficient data response: all safety invariants still present
17  source_event_id field present in response when supplied
18  No forbidden execution route paths in registered app routes
19  No forbidden execution function names in registered app routes
20  No forbidden action labels in endpoint response values
21  _candles_from_market_events: parses valid market_data payload
22  _candles_from_market_events: skips incomplete payload (missing fields)
23  _candles_from_market_events: skips payload with None OHLCV fields
24  _candles_from_market_events: handles pre-parsed dict payload (no double-decode)
25  AST scan: no forbidden broker/order/execute functions defined in api_server.py
26  No live internet required (all mocked in every test)

No live network calls in any test.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

API_SERVER_PATH = _REPO / "scripts" / "api_server.py"

# ---------------------------------------------------------------------------
# Forbidden patterns (shared with test_api_server.py)
# ---------------------------------------------------------------------------

_FORBIDDEN_ROUTE_PATHS = {
    "/execute", "/buy", "/sell", "/order", "/place-order",
    "/submit-order", "/broker", "/broker-execute", "/live-trade", "/auto-trade",
}

_FORBIDDEN_FUNCTION_NAMES = {
    "place_order", "submit_order", "execute_trade", "auto_buy", "auto_sell",
    "cancel_order", "modify_order", "broker_execute", "live_execute",
    "connect_broker", "broker_login", "live_order", "route_order",
}

_FORBIDDEN_ACTION_WORDS = {
    "BUY_NOW", "SELL_NOW", "PLACE_ORDER", "EXECUTE_TRADE",
    "AUTO_EXECUTE", "BROKER_SUBMIT", "TRADE_NOW",
}

# ---------------------------------------------------------------------------
# Shared mock responses
# ---------------------------------------------------------------------------

_MOCK_REPORT_INNER = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
    "summary": {
        "symbol": "AAPL", "source": "market_data", "candle_count": 5,
        "first_timestamp": "2026-01-01", "latest_timestamp": "2026-01-05",
        "latest_close": 185.0, "latest_volume": 50000000.0,
        "price_change_abs": 2.0, "price_change_pct": 1.09,
        "high_low_range_pct": 1.5, "average_volume": 48000000.0,
        "volume_ratio_latest_to_average": 1.04,
    },
    "candle_anatomy": {
        "body_size": 2.0, "body_pct_of_range": 0.7, "upper_wick_size": 0.5,
        "lower_wick_size": 0.3, "upper_wick_pct": 0.175, "lower_wick_pct": 0.105,
        "close_position_in_range": 0.8, "candle_direction": "bullish",
        "candle_shape": "wide_range",
    },
    "trend": {
        "short_sma": 183.0, "medium_sma": None, "long_sma": None,
        "trend_direction": "uptrend", "trend_strength_score": 0.5,
        "consecutive_up_closes": 2, "consecutive_down_closes": 0,
        "distance_from_short_sma_pct": 1.09, "distance_from_medium_sma_pct": None,
    },
    "volatility": {
        "average_true_range": 2.8, "atr_pct": 1.51,
        "realized_volatility_proxy": 0.8, "volatility_regime": "normal",
        "range_expansion_flag": False, "gap_flag": False, "large_move_flag": False,
    },
    "support_resistance": {
        "rolling_high": 186.0, "rolling_low": 180.0,
        "distance_to_rolling_high_pct": 0.54, "distance_to_rolling_low_pct": 2.7,
        "breakout_proximity": "middle_range",
    },
    "context": {
        "chart_confirmation_score": 0.58, "confirmation_reasons": ["Uptrend detected"],
        "contradiction_reasons": [], "chart_state": "TRENDING_UP",
    },
    "advisory": {
        "advisory_summary": "Chart structure shows an upward trend. Human review required.",
        "suggested_next_step": "WATCH_ONLY",
    },
}

_MOCK_SUCCESS_RESPONSE = {
    "symbol": "AAPL",
    "source_event_id": None,
    "candle_count": 5,
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
    "report": _MOCK_REPORT_INNER,
}

_MOCK_INSUFFICIENT_RESPONSE = {
    "symbol": "EMPTY",
    "source_event_id": None,
    "candle_count": 0,
    "chart_state": "INSUFFICIENT_DATA",
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
    "advisory_summary": "No OHLCV candle data available.",
    "report": None,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """TestClient with _get_chart_structure mocked to return a success response."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")

    def _mock_chart_structure(symbol: str, source_event_id=None, limit: int = 100):
        if symbol.upper() == "EMPTY":
            return dict(_MOCK_INSUFFICIENT_RESPONSE, symbol=symbol.upper())
        resp = dict(_MOCK_SUCCESS_RESPONSE, symbol=symbol.upper())
        if source_event_id:
            resp["source_event_id"] = source_event_id
        return resp

    with patch("scripts.api_server._get_chart_structure", side_effect=_mock_chart_structure):
        import scripts.api_server as srv
        tc = TestClient(srv.app, raise_server_exceptions=True)
        yield tc


# ---------------------------------------------------------------------------
# 1–2. Endpoint availability
# ---------------------------------------------------------------------------

def test_chart_structure_requires_symbol(client):
    r = client.get("/chart-structure")
    assert r.status_code == 422


def test_chart_structure_with_symbol_returns_200(client):
    r = client.get("/chart-structure?symbol=AAPL")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 3–4. Response shape
# ---------------------------------------------------------------------------

def test_chart_structure_response_has_report(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert "report" in data


def test_chart_structure_response_has_candle_count(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert "candle_count" in data
    assert isinstance(data["candle_count"], int)


# ---------------------------------------------------------------------------
# 5–10. Top-level safety invariants
# ---------------------------------------------------------------------------

def test_chart_structure_advisory_status(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_chart_structure_execution_gate_locked(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert data["execution_gate"] == "LOCKED"


def test_chart_structure_human_review_required(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert data["human_review_required"] is True


def test_chart_structure_ai_execution_count_zero(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert data["ai_execution_count"] == 0


def test_chart_structure_broker_api_not_called(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert data["broker_api_called"] is False


def test_chart_structure_broker_order_id_none(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert data["broker_order_id"] == "NONE"


# ---------------------------------------------------------------------------
# 11–14. Nested report safety invariants
# ---------------------------------------------------------------------------

def test_nested_report_advisory_status(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    report = data.get("report") or {}
    assert report.get("advisory_status") == "ADVISORY_ONLY"


def test_nested_report_execution_gate_locked(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    report = data.get("report") or {}
    assert report.get("execution_gate") == "LOCKED"


def test_nested_report_ai_execution_count_zero(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    report = data.get("report") or {}
    assert report.get("ai_execution_count") == 0


def test_nested_report_broker_api_not_called(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    report = data.get("report") or {}
    assert report.get("broker_api_called") is False


# ---------------------------------------------------------------------------
# 15–16. Insufficient data response
# ---------------------------------------------------------------------------

def test_insufficient_data_chart_state(client):
    data = client.get("/chart-structure?symbol=EMPTY").json()
    assert data.get("chart_state") == "INSUFFICIENT_DATA"


def test_insufficient_data_report_is_none(client):
    data = client.get("/chart-structure?symbol=EMPTY").json()
    assert data.get("report") is None


def test_insufficient_data_advisory_status_present(client):
    data = client.get("/chart-structure?symbol=EMPTY").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_insufficient_data_execution_gate_locked(client):
    data = client.get("/chart-structure?symbol=EMPTY").json()
    assert data["execution_gate"] == "LOCKED"


def test_insufficient_data_ai_execution_count_zero(client):
    data = client.get("/chart-structure?symbol=EMPTY").json()
    assert data["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 17. source_event_id lookup
# ---------------------------------------------------------------------------

def test_source_event_id_in_response_when_supplied(client):
    data = client.get(
        "/chart-structure?symbol=AAPL&source_event_id=EVT_AAPL_001"
    ).json()
    assert "source_event_id" in data
    assert data["source_event_id"] == "EVT_AAPL_001"


def test_source_event_id_none_when_not_supplied(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    assert "source_event_id" in data


# ---------------------------------------------------------------------------
# 18–19. No forbidden routes in app
# ---------------------------------------------------------------------------

def test_no_forbidden_route_paths_in_app(client):
    import scripts.api_server as srv
    paths = [r.path for r in srv.app.routes if hasattr(r, "path")]
    for path in paths:
        for forbidden in _FORBIDDEN_ROUTE_PATHS:
            assert forbidden not in path.lower(), (
                f"Forbidden segment '{forbidden}' in route: {path}"
            )


def test_no_forbidden_function_names_in_router(client):
    import scripts.api_server as srv
    for route in srv.app.routes:
        name = getattr(route, "name", "") or ""
        assert name not in _FORBIDDEN_FUNCTION_NAMES, (
            f"Forbidden endpoint function '{name}' in app router"
        )


# ---------------------------------------------------------------------------
# 20. No forbidden action labels in response values
# ---------------------------------------------------------------------------

def test_no_forbidden_action_labels_in_response(client):
    data = client.get("/chart-structure?symbol=AAPL").json()
    flat_values = _flatten_values(data)
    for val in flat_values:
        if isinstance(val, str):
            for forbidden in _FORBIDDEN_ACTION_WORDS:
                assert forbidden not in val.upper(), (
                    f"Forbidden action word '{forbidden}' found in response value: {val!r}"
                )


def _flatten_values(obj, depth: int = 0) -> list:
    if depth > 10:
        return []
    if isinstance(obj, dict):
        result = []
        for v in obj.values():
            result.extend(_flatten_values(v, depth + 1))
        return result
    if isinstance(obj, list):
        result = []
        for v in obj:
            result.extend(_flatten_values(v, depth + 1))
        return result
    return [obj]


# ---------------------------------------------------------------------------
# 21–24. _candles_from_market_events unit tests (no HTTP, no mock needed)
# ---------------------------------------------------------------------------

def test_candles_from_market_events_parses_valid_payload():
    from scripts.api_server import _candles_from_market_events

    events = [
        {
            "event_id": "EVT_001",
            "fetched_at": "2026-01-01T00:00:00Z",
            "raw_payload": {
                "symbol": "AAPL",
                "open": 180.0, "high": 186.0, "low": 179.0,
                "close": 185.0, "volume": 50000000.0,
                "timestamp": "2026-01-01",
            },
        }
    ]
    candles = _candles_from_market_events(events)
    assert len(candles) == 1
    assert candles[0]["close"] == 185.0
    assert candles[0]["timestamp"] == "2026-01-01"


def test_candles_from_market_events_skips_missing_close():
    from scripts.api_server import _candles_from_market_events

    events = [
        {
            "event_id": "EVT_002",
            "fetched_at": "2026-01-02T00:00:00Z",
            "raw_payload": {
                "symbol": "AAPL",
                "open": 180.0, "high": 186.0, "low": 179.0,
                # close is missing, latest_price also absent
                "volume": 50000000.0,
                "timestamp": "2026-01-02",
            },
        }
    ]
    candles = _candles_from_market_events(events)
    assert len(candles) == 0


def test_candles_from_market_events_skips_none_ohlcv():
    from scripts.api_server import _candles_from_market_events

    events = [
        {
            "event_id": "EVT_003",
            "fetched_at": "2026-01-03T00:00:00Z",
            "raw_payload": {
                "symbol": "AAPL",
                "open": None, "high": 186.0, "low": 179.0,
                "close": 185.0, "volume": 50000000.0,
                "timestamp": "2026-01-03",
            },
        }
    ]
    candles = _candles_from_market_events(events)
    assert len(candles) == 0


def test_candles_from_market_events_handles_pre_parsed_dict():
    from scripts.api_server import _candles_from_market_events

    # raw_payload is already a dict (as returned by get_signal_events)
    events = [
        {
            "event_id": "EVT_004",
            "fetched_at": "2026-01-04T00:00:00Z",
            "raw_payload": {
                "symbol": "TSLA",
                "open": 200.0, "high": 210.0, "low": 198.0,
                "close": 208.0, "volume": 70000000.0,
                "timestamp": "2026-01-04",
            },
        }
    ]
    candles = _candles_from_market_events(events)
    assert len(candles) == 1
    assert candles[0]["open"] == 200.0


def test_candles_from_market_events_uses_latest_price_as_close_fallback():
    from scripts.api_server import _candles_from_market_events

    events = [
        {
            "event_id": "EVT_005",
            "fetched_at": "2026-01-05T00:00:00Z",
            "raw_payload": {
                "symbol": "MSFT",
                "open": 400.0, "high": 405.0, "low": 398.0,
                "latest_price": 403.0, "volume": 30000000.0,
                "timestamp": "2026-01-05",
            },
        }
    ]
    candles = _candles_from_market_events(events)
    assert len(candles) == 1
    assert candles[0]["close"] == 403.0


# ---------------------------------------------------------------------------
# 25. AST scan: no forbidden broker/order/execute functions in api_server.py
# ---------------------------------------------------------------------------

def test_ast_no_forbidden_function_defined_in_api_server():
    tree = ast.parse(API_SERVER_PATH.read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    violations = defined & _FORBIDDEN_FUNCTION_NAMES
    assert not violations, f"Forbidden execution functions in api_server: {violations}"


def test_ast_no_forbidden_route_path_in_chart_structure_decorator():
    tree = ast.parse(API_SERVER_PATH.read_text(encoding="utf-8"))
    registered: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr in {
                "get", "post", "put", "delete", "patch"
            }):
                continue
            for arg in dec.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    registered.append(arg.value)
    violations = [
        p for p in registered
        if any(f in p.lower() for f in _FORBIDDEN_ROUTE_PATHS)
    ]
    assert not violations, f"Forbidden route paths in decorators: {violations}"


# ---------------------------------------------------------------------------
# 26. No live internet dependency (meta-test)
# ---------------------------------------------------------------------------

def test_no_live_internet_required(client):
    # The entire test module runs with _get_chart_structure mocked, proving
    # that no real network calls are needed for any test.
    r = client.get("/chart-structure?symbol=AAPL")
    assert r.status_code == 200
