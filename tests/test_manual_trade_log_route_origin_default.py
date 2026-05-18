"""HTTP-layer tests for the Manual Trade Log route contract.

The leaked-AAPL incident traced back to ``GET /manual-trades`` returning
every row in the table (822 of them), including 799 with empty
``created_via``.  The fix:

* ``GET /manual-trades`` defaults to ``origin=manual_trade_log`` — the
  same predicate the Reconciliation queue uses.
* ``POST /manual-trades`` returns 400 when the row looks like a
  seed/probe/automation submission (placeholder thesis, seed event_id
  prefix, automation logged_by).

These tests pin both contracts so a regression here would re-introduce
the leaked-row bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


@pytest.fixture()
def http_client(monkeypatch):
    """TestClient with log_manual_trade and list_manual_trades inspectable."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    captured: dict[str, object] = {}

    def fake_list(origin=None, **_kwargs):
        captured["list_origin"] = origin
        return {
            "operation": "list_manual_trades",
            "trade_count": 0,
            "trades": [],
            "truth_source": "sqlite",
            "fallback_used": False,
            "canonical": True,
            "journal_quality_aggregate": None,
            "advisory_status": "ADVISORY_ONLY",
            "execution_mode": "HUMAN_ONLY",
            "execution_gate": "LOCKED",
            "execution_permission": False,
            "can_execute": False,
            "ai_execution_count": 0,
            "human_review_required": True,
            "broker_api_called": False,
            "generated_at": "2026-05-18T00:00:00Z",
        }

    monkeypatch.setattr(srv, "list_manual_trades", fake_list)
    client = TestClient(srv.app, raise_server_exceptions=True)
    return client, captured, srv


def test_get_manual_trades_defaults_to_manual_trade_log_scope(http_client):
    """No query param → backend filters to user-manual rows only."""
    client, captured, _ = http_client
    resp = client.get("/manual-trades")
    assert resp.status_code == 200
    # The route forwarded origin='manual_trade_log' even though the
    # caller sent nothing.  This is the active fence behind the
    # "seed rows never leak" contract.
    assert captured["list_origin"] == "manual_trade_log"


def test_get_manual_trades_origin_all_opts_into_audit_scope(http_client):
    """Explicit ?origin=all returns every row (kept as audit escape hatch)."""
    client, captured, _ = http_client
    resp = client.get("/manual-trades?origin=all")
    assert resp.status_code == 200
    assert captured["list_origin"] is None  # all → unfiltered


def test_get_manual_trades_explicit_origin_passes_through(http_client):
    client, captured, _ = http_client
    resp = client.get("/manual-trades?origin=manual_trade_log")
    assert resp.status_code == 200
    assert captured["list_origin"] == "manual_trade_log"


def test_post_manual_trade_rejects_probe_thesis():
    """Body whose thesis is an exact placeholder string is refused."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    body = {
        "event_id": "EV_OK",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 10.0,
        "price": 180.0,
        "thesis": "probe",  # the exact leaked-row marker
    }
    resp = client.post("/manual-trades", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    # Structured 400: message + reason + safety stamps preserved.
    assert "thesis" in str(detail.get("message", "")).lower()
    assert detail.get("broker_api_called") is False
    assert detail.get("ai_execution_count") == 0
    assert detail.get("execution_gate") == "LOCKED"
    assert detail.get("execution_permission") is False


def test_post_manual_trade_rejects_seed_event_id_prefix():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    body = {
        "event_id": "SEED_AAPL",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 10.0,
        "price": 180.0,
        "thesis": "genuine reasoning sentence",
    }
    resp = client.post("/manual-trades", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert "event_id" in str(detail.get("message", "")).lower()
    assert detail.get("execution_gate") == "LOCKED"


def test_post_manual_trade_rejects_synthetic_logged_by():
    """Test/fixture markers (smoke_test, seed, demo, fixture, mock,
    sample, calibration_seed) have no legitimate workflow at this
    endpoint and are refused.  ``paper_ledger_import`` is intentionally
    NOT in this list — paper imports are a legitimate non-UI workflow."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    body = {
        "event_id": "EV_OK",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 10.0,
        "price": 180.0,
        "thesis": "genuine reasoning sentence",
        "logged_by": "smoke_test",
    }
    resp = client.post("/manual-trades", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert "logged_by" in str(detail.get("message", "")).lower()


def test_post_manual_trade_rejects_no_currency_given_thesis():
    """The exact thesis from the leaked visible row is refused with the
    structured reason ``rejected_non_user_manual_trade_marker``."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    body = {
        "event_id": "EVT_NO_CUR",
        "ticker": "MSFT",
        "side": "BUY",
        "quantity": 1.0,
        "price": 421.0,
        "thesis": "no currency given",
    }
    resp = client.post("/manual-trades", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("reason") == "rejected_non_user_manual_trade_marker"
    assert detail.get("execution_gate") == "LOCKED"
    assert detail.get("broker_api_called") is False


def test_post_manual_trade_rejects_ev_aapl_prefix():
    """EV_AAPL event_id prefix is refused with the new structured reason."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    body = {
        "event_id": "EV_AAPL_FOLLOWUP",
        "ticker": "MSFT",
        "side": "BUY",
        "quantity": 1.0,
        "price": 421.0,
        "thesis": "reasonable reasoning sentence about the setup",
    }
    resp = client.post("/manual-trades", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json().get("detail") or {}
    assert detail.get("reason") == "rejected_non_user_manual_trade_marker"


def test_post_manual_trade_accepts_ai_model_used():
    """Happy path: forwards ai_model_used to log_manual_trade."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        pytest.skip("fastapi[testclient] not installed")
    import scripts.api_server as srv

    captured: dict[str, object] = {}

    def fake_log(**kwargs):
        captured.update(kwargs)
        return {
            "operation": "log_manual_trade",
            "trade_id": "MT_FAKE",
            "status": "logged",
            "ai_model_used": kwargs.get("ai_model_used", ""),
            "advisory_status": "ADVISORY_ONLY",
            "execution_mode": "HUMAN_ONLY",
            "execution_gate": "LOCKED",
            "execution_permission": False,
            "can_execute": False,
            "broker_api_called": False,
            "broker_order_id": "NONE",
            "ai_execution_count": 0,
            "human_review_required": True,
        }

    # Use a brand-new client so the monkeypatch is scoped.
    import unittest.mock as _mock

    with _mock.patch.object(srv, "log_manual_trade", side_effect=fake_log):
        client = TestClient(srv.app, raise_server_exceptions=True)
        body = {
            "event_id": "EV_AI_MODEL",
            "ticker": "ANET",
            "side": "BUY",
            "quantity": 1.0,
            "price": 141.97,
            "thesis": "break of structure on volume",
            "ai_model_used": "Claude Code",
        }
        resp = client.post("/manual-trades", json=body)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["ai_model_used"] == "Claude Code"
        assert captured["ai_model_used"] == "Claude Code"
        # Safety stamps preserved on the happy-path response.
        assert payload["broker_api_called"] is False
        assert payload["broker_order_id"] == "NONE"
        assert payload["ai_execution_count"] == 0
        assert payload["execution_gate"] == "LOCKED"
        assert payload["execution_mode"] == "HUMAN_ONLY"
