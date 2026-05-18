"""
Tests for Signal Advisory API Server (scripts/api_server.py).

Coverage
--------
1.  GET  /health                      — advisory fields, ai_execution_count=0
2.  GET  /signals                     — delegates to list_inbox_items, advisory stamp
3.  GET  /signals/{event_id}          — delegates to get_signal_detail
4.  POST /signals/{event_id}/validate — delegates to run_validation
5.  POST /signals/{event_id}/reflection
6.  POST /signals/{event_id}/ai-summary
7.  POST /signals/{event_id}/decision
8.  POST /manual-trades               — HUMAN_ONLY, broker_api_called False
9.  POST /manual-trades/{id}/reconcile
10. GET  /moltbook
11. POST /moltbook
12. GET  /exports/signal-inbox.csv    — content-type text/csv
13. GET  /exports/reflections.csv
14. GET  /exports/manual-trades.csv
15. GET  /exports/reconciliation.csv
16. GET  /exports/moltbook.csv
17. GET  /exports/source-health.csv
18. AST proof: no forbidden execution endpoint defined in api_server.py
19. No buy/sell/execute/broker route exists in the router table
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
API_SERVER_PATH = REPO_ROOT / "scripts" / "api_server.py"

# ---------------------------------------------------------------------------
# Forbidden execution patterns (route paths and function names)
# ---------------------------------------------------------------------------

FORBIDDEN_ROUTE_PATHS = {
    "/execute",
    "/buy",
    "/sell",
    "/order",
    "/place-order",
    "/submit-order",
    "/broker",
    "/broker-execute",
    "/live-trade",
    "/auto-trade",
}

FORBIDDEN_FUNCTION_NAMES = {
    "place_order",
    "submit_order",
    "execute_trade",
    "auto_buy",
    "auto_sell",
    "cancel_order",
    "modify_order",
    "broker_execute",
    "live_execute",
    "connect_broker",
    "broker_login",
    "live_order",
    "route_order",
}


# ---------------------------------------------------------------------------
# FastAPI test client fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] not installed")

    # Patch all backend functions so tests are isolated from disk/fabric
    _advisory = {
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_mode": "HUMAN_ONLY",
        "ai_execution_count": 0,
    }

    _inbox_resp = {
        **_advisory,
        "operation": "list_inbox_items",
        "item_count": 0,
        "items": [],
        "fabric_bull_state": "UNKNOWN",
        "fabric_stats": {},
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _detail_resp = {
        **_advisory,
        "operation": "get_signal_detail",
        "event_id": "TEST_001",
        "signal": {},
        "ticker_summary": {},
        "reflections": [],
        "ai_summaries": [],
        "manual_trades": [],
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _validate_resp = {
        **_advisory,
        "operation": "run_validation",
        "validation": {
            "event_id": "TEST_001",
            "validated_at": "2026-01-01T00:00:00Z",
            "validation_checks": {},
            "validation_passed": True,
            "validation_notes": [],
            "advisory_status": "ADVISORY_ONLY",
            "human_review_required": True,
            "execution_gate": "LOCKED",
        },
        "advisory_note": "advisory only",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _reflection_resp = {
        **_advisory,
        "operation": "add_user_reflection",
        "reflection_id": "REF_aabbccddee",
        "event_id": "TEST_001",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _ai_summary_resp = {
        **_advisory,
        "operation": "add_ai_discussion_summary",
        "summary_id": "AISUM_aabbccddee",
        "event_id": "TEST_001",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _decision_resp = {
        **_advisory,
        "operation": "mark_signal",
        "event_id": "TEST_001",
        "user_status": "watchlist",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _trade_resp = {
        **_advisory,
        "operation": "log_manual_trade",
        "trade_id": "TRADE_aabbccddee",
        "event_id": "TEST_001",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 10.0,
        "price": 150.0,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _reconcile_resp = {
        **_advisory,
        "operation": "reconcile_trade",
        "reconciliation_id": "REC_aabbccddee",
        "trade_id": "TRADE_001",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _cancel_log_resp = {
        **_advisory,
        "operation": "cancel_manual_trade_log",
        "trade_id": "TRADE_001",
        "reconciliation_status": "CANCELLED_DUPLICATE",
        "cancel_reason": "duplicate manual log",
        "cancelled_at": "2026-01-01T00:00:00Z",
        "sqlite_updated": True,
        "status": "cancelled",
        "execution_gate": "LOCKED",
        "execution_permission": False,
        "can_execute": False,
        "broker_api_called": False,
        "record_keeping_only": True,
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _moltbook_list_resp = {
        **_advisory,
        "operation": "list_moltbook_entries",
        "entry_count": 0,
        "entries": [],
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _moltbook_log_resp = {
        **_advisory,
        "operation": "log_moltbook_entry",
        "entry_id": "MOLT_aabbccddee",
        "event_id": "TEST_001",
        "generated_at": "2026-01-01T00:00:00Z",
    }

    _csv = "col1,col2\nval1,val2\n"

    patches = [
        patch("scripts.api_server.list_inbox_items", return_value=_inbox_resp),
        patch("scripts.api_server.get_signal_detail", return_value=_detail_resp),
        patch("scripts.api_server.run_validation", return_value=_validate_resp),
        patch("scripts.api_server.add_user_reflection", return_value=_reflection_resp),
        patch("scripts.api_server.add_ai_discussion_summary", return_value=_ai_summary_resp),
        patch("scripts.api_server.mark_signal", return_value=_decision_resp),
        patch("scripts.api_server.log_manual_trade", return_value=_trade_resp),
        patch("scripts.api_server.reconcile_trade", return_value=_reconcile_resp),
        patch(
            "scripts.api_server.cancel_manual_trade_log",
            return_value=_cancel_log_resp,
        ),
        patch("scripts.api_server.list_moltbook_entries", return_value=_moltbook_list_resp),
        patch("scripts.api_server.log_moltbook_entry", return_value=_moltbook_log_resp),
        patch("scripts.api_server.export_signal_inbox_log", return_value=_csv),
        patch("scripts.api_server.export_reflection_log", return_value=_csv),
        patch("scripts.api_server.export_manual_trade_log", return_value=_csv),
        patch("scripts.api_server.export_reconciliation_log", return_value=_csv),
        patch("scripts.api_server.export_moltbook_mistake_log", return_value=_csv),
        patch("scripts.api_server.export_source_health_log", return_value=_csv),
    ]

    for p in patches:
        p.start()

    import scripts.api_server as srv
    tc = TestClient(srv.app, raise_server_exceptions=True)
    yield tc

    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# 1. GET /health
# ---------------------------------------------------------------------------


def test_health_status_ok(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_health_advisory_status(client):
    data = client.get("/health").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_health_execution_mode(client):
    data = client.get("/health").json()
    assert data["execution_mode"] == "HUMAN_ONLY"


def test_health_ai_execution_count_zero(client):
    data = client.get("/health").json()
    assert data["ai_execution_count"] == 0


def test_health_human_review_required(client):
    data = client.get("/health").json()
    assert data["human_review_required"] is True


def test_health_has_version(client):
    data = client.get("/health").json()
    assert "version" in data


# ---------------------------------------------------------------------------
# 2. GET /signals
# ---------------------------------------------------------------------------


def test_get_signals_status_ok(client):
    r = client.get("/signals")
    assert r.status_code == 200


def test_get_signals_advisory_status(client):
    data = client.get("/signals").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_get_signals_ai_execution_count_zero(client):
    data = client.get("/signals").json()
    assert data["ai_execution_count"] == 0


def test_get_signals_has_items_list(client):
    data = client.get("/signals").json()
    assert "items" in data
    assert isinstance(data["items"], list)


# ---------------------------------------------------------------------------
# 3. GET /signals/{event_id}
# ---------------------------------------------------------------------------


def test_get_signal_detail_status_ok(client):
    r = client.get("/signals/TEST_001")
    assert r.status_code == 200


def test_get_signal_detail_advisory_status(client):
    data = client.get("/signals/TEST_001").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_get_signal_detail_ai_execution_count_zero(client):
    data = client.get("/signals/TEST_001").json()
    assert data["ai_execution_count"] == 0


def test_get_signal_detail_execution_mode(client):
    data = client.get("/signals/TEST_001").json()
    assert data["execution_mode"] == "HUMAN_ONLY"


# ---------------------------------------------------------------------------
# 4. POST /signals/{event_id}/validate
# ---------------------------------------------------------------------------


def test_validate_signal_status_ok(client):
    r = client.post("/signals/TEST_001/validate")
    assert r.status_code == 200


def test_validate_signal_advisory_status(client):
    data = client.post("/signals/TEST_001/validate").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_validate_signal_ai_execution_count_zero(client):
    data = client.post("/signals/TEST_001/validate").json()
    assert data["ai_execution_count"] == 0


def test_validate_signal_execution_gate_locked(client):
    data = client.post("/signals/TEST_001/validate").json()
    validation = data.get("validation", {})
    assert validation.get("execution_gate") == "LOCKED"


# ---------------------------------------------------------------------------
# 5. POST /signals/{event_id}/reflection
# ---------------------------------------------------------------------------


def test_post_reflection_status_ok(client):
    payload = {"reflection_text": "This looks interesting.", "author": "human"}
    r = client.post("/signals/TEST_001/reflection", json=payload)
    assert r.status_code == 200


def test_post_reflection_advisory_status(client):
    payload = {"reflection_text": "Noted.", "author": "human"}
    data = client.post("/signals/TEST_001/reflection", json=payload).json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_post_reflection_ai_execution_count_zero(client):
    payload = {"reflection_text": "Careful.", "author": "human"}
    data = client.post("/signals/TEST_001/reflection", json=payload).json()
    assert data["ai_execution_count"] == 0


def test_post_reflection_requires_reflection_text(client):
    r = client.post("/signals/TEST_001/reflection", json={"author": "human"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 6. POST /signals/{event_id}/ai-summary
# ---------------------------------------------------------------------------


def test_post_ai_summary_status_ok(client):
    payload = {"summary_text": "The signal looks bullish.", "model_label": "AI_ADVISORY"}
    r = client.post("/signals/TEST_001/ai-summary", json=payload)
    assert r.status_code == 200


def test_post_ai_summary_advisory_status(client):
    payload = {"summary_text": "Advisory text.", "model_label": "AI_ADVISORY"}
    data = client.post("/signals/TEST_001/ai-summary", json=payload).json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_post_ai_summary_ai_execution_count_zero(client):
    payload = {"summary_text": "Advisory text.", "model_label": "AI_ADVISORY"}
    data = client.post("/signals/TEST_001/ai-summary", json=payload).json()
    assert data["ai_execution_count"] == 0


def test_post_ai_summary_requires_summary_text(client):
    r = client.post("/signals/TEST_001/ai-summary", json={"model_label": "AI_ADVISORY"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 7. POST /signals/{event_id}/decision
# ---------------------------------------------------------------------------


def test_post_decision_status_ok(client):
    r = client.post("/signals/TEST_001/decision", json={"status": "watchlist"})
    assert r.status_code == 200


def test_post_decision_advisory_status(client):
    data = client.post("/signals/TEST_001/decision", json={"status": "watchlist"}).json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_post_decision_ai_execution_count_zero(client):
    data = client.post("/signals/TEST_001/decision", json={"status": "rejected"}).json()
    assert data["ai_execution_count"] == 0


def test_post_decision_requires_status_field(client):
    r = client.post("/signals/TEST_001/decision", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 8. POST /manual-trades
# ---------------------------------------------------------------------------

_TRADE_PAYLOAD = {
    # Use a neutral event_id prefix (not TEST_/SEED_/DEMO_/etc.) so the
    # post route's seed/probe guard does not refuse this synthetic-but-
    # legitimate happy-path payload.  The guard is exercised explicitly
    # by tests/test_manual_trade_seed_rejection.py.
    "event_id": "EV_TRADE_001",
    "ticker": "AAPL",
    "side": "BUY",
    "quantity": 10.0,
    "price": 150.0,
    "thesis": "Price breakout observed.",
    "notes": "Test trade",
    "logged_by": "human",
}


def test_post_manual_trade_status_ok(client):
    r = client.post("/manual-trades", json=_TRADE_PAYLOAD)
    assert r.status_code == 200


def test_post_manual_trade_advisory_status(client):
    data = client.post("/manual-trades", json=_TRADE_PAYLOAD).json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_post_manual_trade_execution_mode_human_only(client):
    data = client.post("/manual-trades", json=_TRADE_PAYLOAD).json()
    assert data["execution_mode"] == "HUMAN_ONLY"


def test_post_manual_trade_ai_execution_count_zero(client):
    data = client.post("/manual-trades", json=_TRADE_PAYLOAD).json()
    assert data["ai_execution_count"] == 0


def test_post_manual_trade_broker_api_not_called(client):
    data = client.post("/manual-trades", json=_TRADE_PAYLOAD).json()
    assert data["broker_api_called"] is False


def test_post_manual_trade_broker_order_id_none(client):
    data = client.post("/manual-trades", json=_TRADE_PAYLOAD).json()
    assert data["broker_order_id"] == "NONE"


def test_post_manual_trade_requires_ticker(client):
    payload = {k: v for k, v in _TRADE_PAYLOAD.items() if k != "ticker"}
    r = client.post("/manual-trades", json=payload)
    assert r.status_code == 422


def test_post_manual_trade_requires_price(client):
    payload = {k: v for k, v in _TRADE_PAYLOAD.items() if k != "price"}
    r = client.post("/manual-trades", json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 9. POST /manual-trades/{trade_id}/reconcile
# ---------------------------------------------------------------------------

_RECONCILE_PAYLOAD = {
    "actual_fill_price": 151.5,
    "actual_quantity": 10.0,
    "outcome_notes": "Filled at market open",
    "pnl_estimate": 15.0,
    "outcome_status": "WIN",
}


def test_post_reconcile_status_ok(client):
    r = client.post("/manual-trades/TRADE_001/reconcile", json=_RECONCILE_PAYLOAD)
    assert r.status_code == 200


def test_post_reconcile_advisory_status(client):
    data = client.post("/manual-trades/TRADE_001/reconcile", json=_RECONCILE_PAYLOAD).json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_post_reconcile_ai_execution_count_zero(client):
    data = client.post("/manual-trades/TRADE_001/reconcile", json=_RECONCILE_PAYLOAD).json()
    assert data["ai_execution_count"] == 0


def test_post_reconcile_requires_actual_fill_price(client):
    payload = {k: v for k, v in _RECONCILE_PAYLOAD.items() if k != "actual_fill_price"}
    r = client.post("/manual-trades/TRADE_001/reconcile", json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 9b. POST /manual-trades/{trade_id}/cancel — soft-cancel for duplicate logs
# ---------------------------------------------------------------------------

_CANCEL_LOG_PAYLOAD = {
    "reason": "duplicate manual log",
    "status": "CANCELLED_DUPLICATE",
}


def test_post_cancel_log_status_ok(client):
    r = client.post(
        "/manual-trades/TRADE_001/cancel", json=_CANCEL_LOG_PAYLOAD
    )
    assert r.status_code == 200


def test_post_cancel_log_advisory_status(client):
    data = client.post(
        "/manual-trades/TRADE_001/cancel", json=_CANCEL_LOG_PAYLOAD
    ).json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_post_cancel_log_ai_execution_count_zero(client):
    data = client.post(
        "/manual-trades/TRADE_001/cancel", json=_CANCEL_LOG_PAYLOAD
    ).json()
    assert data["ai_execution_count"] == 0


def test_post_cancel_log_broker_api_not_called(client):
    data = client.post(
        "/manual-trades/TRADE_001/cancel", json=_CANCEL_LOG_PAYLOAD
    ).json()
    assert data["broker_api_called"] is False
    assert data["execution_gate"] == "LOCKED"
    assert data["can_execute"] is False


def test_post_cancel_log_returns_cancelled_status_field(client):
    data = client.post(
        "/manual-trades/TRADE_001/cancel", json=_CANCEL_LOG_PAYLOAD
    ).json()
    assert data["status"] == "cancelled"
    assert data["reconciliation_status"] == "CANCELLED_DUPLICATE"
    assert data["record_keeping_only"] is True


def test_post_cancel_log_accepts_empty_body(client):
    # Body is optional — backend fills defaults.
    r = client.post("/manual-trades/TRADE_001/cancel", json={})
    assert r.status_code == 200


def test_post_cancel_log_returns_404_when_not_found(client):
    not_found_resp = {
        "operation": "cancel_manual_trade_log",
        "error": "manual trade log 'NOPE' not found",
        "status": "not_found",
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_mode": "HUMAN_ONLY",
        "ai_execution_count": 0,
        "generated_at": "2026-01-01T00:00:00Z",
    }
    with patch(
        "scripts.api_server.cancel_manual_trade_log",
        return_value=not_found_resp,
    ):
        r = client.post("/manual-trades/NOPE/cancel", json={})
    assert r.status_code == 404


def test_post_cancel_log_returns_400_when_refused(client):
    refused_resp = {
        "operation": "cancel_manual_trade_log",
        "error": "trade has been reconciled; cancel the reconciliation row first",
        "status": "refused",
        "reconciled": True,
        "broker_api_called": False,
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_mode": "HUMAN_ONLY",
        "ai_execution_count": 0,
        "generated_at": "2026-01-01T00:00:00Z",
    }
    with patch(
        "scripts.api_server.cancel_manual_trade_log",
        return_value=refused_resp,
    ):
        r = client.post("/manual-trades/TRADE_001/cancel", json={})
    assert r.status_code == 400


# Sprint I — the refused 400 response must carry a structured ``detail``
# object with ``reason`` and ``message`` fields so the frontend can show
# "This trade has been reconciled" instead of the user-visible
# "Could not cancel log (HTTP 400)" the screenshot complained about.
def test_post_cancel_log_400_detail_carries_structured_reason(client):
    refused_resp = {
        "operation": "cancel_manual_trade_log",
        "error": "This trade has been reconciled.",
        "status": "refused",
        "reason": "already_reconciled",
        "reconciled": True,
        "broker_api_called": False,
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_mode": "HUMAN_ONLY",
        "ai_execution_count": 0,
        "generated_at": "2026-01-01T00:00:00Z",
    }
    with patch(
        "scripts.api_server.cancel_manual_trade_log",
        return_value=refused_resp,
    ):
        r = client.post("/manual-trades/TRADE_001/cancel", json={})
    assert r.status_code == 400
    body = r.json()
    assert isinstance(body.get("detail"), dict)
    assert body["detail"].get("reason") == "already_reconciled"
    assert body["detail"].get("reconciled") is True
    assert body["detail"].get("broker_api_called") is False
    assert "reconcile" in body["detail"].get("message", "").lower()


def test_post_cancel_log_404_detail_carries_structured_reason(client):
    not_found_resp = {
        "operation": "cancel_manual_trade_log",
        "error": "manual trade log 'NOPE' not found",
        "status": "not_found",
        "reason": "not_found",
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_mode": "HUMAN_ONLY",
        "ai_execution_count": 0,
        "generated_at": "2026-01-01T00:00:00Z",
    }
    with patch(
        "scripts.api_server.cancel_manual_trade_log",
        return_value=not_found_resp,
    ):
        r = client.post("/manual-trades/NOPE/cancel", json={})
    assert r.status_code == 404
    body = r.json()
    assert isinstance(body.get("detail"), dict)
    assert body["detail"].get("reason") == "not_found"
    assert body["detail"].get("trade_id") == "NOPE"


# ---------------------------------------------------------------------------
# 10. GET /moltbook
# ---------------------------------------------------------------------------


def test_get_moltbook_status_ok(client):
    r = client.get("/moltbook")
    assert r.status_code == 200


def test_get_moltbook_advisory_status(client):
    data = client.get("/moltbook").json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_get_moltbook_ai_execution_count_zero(client):
    data = client.get("/moltbook").json()
    assert data["ai_execution_count"] == 0


def test_get_moltbook_has_entries_list(client):
    data = client.get("/moltbook").json()
    assert "entries" in data
    assert isinstance(data["entries"], list)


# ---------------------------------------------------------------------------
# 11. POST /moltbook
# ---------------------------------------------------------------------------

_MOLTBOOK_PAYLOAD = {
    "event_id": "TEST_001",
    "ticker": "AAPL",
    "original_signal_thesis": "Breakout confirmed.",
    "ai_interpretation": "Momentum signal observed.",
    "user_reflection": "Agreed with signal direction.",
    "final_human_decision": "Logged manual trade.",
    "mistake_type": "good_signal_good_execution",
    "lesson_learned": "Trust the momentum signal when volume confirms.",
}


def test_post_moltbook_status_ok(client):
    r = client.post("/moltbook", json=_MOLTBOOK_PAYLOAD)
    assert r.status_code == 200


def test_post_moltbook_advisory_status(client):
    data = client.post("/moltbook", json=_MOLTBOOK_PAYLOAD).json()
    assert data["advisory_status"] == "ADVISORY_ONLY"


def test_post_moltbook_ai_execution_count_zero(client):
    data = client.post("/moltbook", json=_MOLTBOOK_PAYLOAD).json()
    assert data["ai_execution_count"] == 0


def test_post_moltbook_requires_mistake_type(client):
    payload = {k: v for k, v in _MOLTBOOK_PAYLOAD.items() if k != "mistake_type"}
    r = client.post("/moltbook", json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 12–17. CSV export endpoints
# ---------------------------------------------------------------------------

_CSV_ROUTES = [
    "/exports/signal-inbox.csv",
    "/exports/reflections.csv",
    "/exports/manual-trades.csv",
    "/exports/reconciliation.csv",
    "/exports/moltbook.csv",
    "/exports/source-health.csv",
]


@pytest.mark.parametrize("route", _CSV_ROUTES)
def test_csv_export_status_ok(client, route):
    r = client.get(route)
    assert r.status_code == 200


@pytest.mark.parametrize("route", _CSV_ROUTES)
def test_csv_export_content_type(client, route):
    r = client.get(route)
    assert "text/csv" in r.headers["content-type"]


@pytest.mark.parametrize("route", _CSV_ROUTES)
def test_csv_export_has_content(client, route):
    r = client.get(route)
    assert len(r.content) > 0


# ---------------------------------------------------------------------------
# 18. AST proof: no forbidden execution endpoint in api_server.py
# ---------------------------------------------------------------------------


def _parse_api_server() -> ast.Module:
    return ast.parse(API_SERVER_PATH.read_text(encoding="utf-8"))


def test_no_forbidden_function_defined_in_api_server():
    tree = _parse_api_server()
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    violations = defined & FORBIDDEN_FUNCTION_NAMES
    assert not violations, f"Forbidden execution functions defined: {violations}"


def test_no_forbidden_route_path_in_decorators():
    """Check only route decorator string arguments, not comments/docstrings."""
    tree = _parse_api_server()
    registered_paths: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            # Match app.get / app.post / app.put / app.delete / app.patch
            if not (isinstance(func, ast.Attribute) and func.attr in {
                "get", "post", "put", "delete", "patch"
            }):
                continue
            for arg in decorator.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    registered_paths.append(arg.value)
    violations = [
        p for p in registered_paths
        if any(forbidden in p.lower() for forbidden in FORBIDDEN_ROUTE_PATHS)
    ]
    assert not violations, f"Forbidden route paths in decorators: {violations}"


# ---------------------------------------------------------------------------
# 19. No buy/sell/execute/broker route in FastAPI router table
# ---------------------------------------------------------------------------


def test_no_execution_route_in_router(client):
    import scripts.api_server as srv

    routes = [r.path for r in srv.app.routes if hasattr(r, "path")]
    for path in routes:
        path_lower = path.lower()
        for forbidden in FORBIDDEN_ROUTE_PATHS:
            assert forbidden not in path_lower, (
                f"Forbidden route segment '{forbidden}' found in registered route: {path}"
            )


def test_no_execute_method_in_router(client):
    import scripts.api_server as srv

    for route in srv.app.routes:
        name = getattr(route, "name", "") or ""
        assert name not in FORBIDDEN_FUNCTION_NAMES, (
            f"Forbidden endpoint function '{name}' registered in app router"
        )


def test_health_confirms_ai_execution_count_field_is_integer(client):
    data = client.get("/health").json()
    assert isinstance(data["ai_execution_count"], int)
    assert data["ai_execution_count"] == 0


def test_manual_trade_response_confirms_no_broker_call(client):
    data = client.post("/manual-trades", json=_TRADE_PAYLOAD).json()
    assert data.get("broker_api_called") is False
    assert data.get("broker_order_id") == "NONE"
    assert data.get("execution_mode") == "HUMAN_ONLY"
    assert data.get("ai_execution_count") == 0
