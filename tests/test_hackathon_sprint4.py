"""Sprint 4 proofs — L2, L3, L4."""
from __future__ import annotations

import importlib
import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.runtime_config as rc


@pytest.fixture
def _safe_env(monkeypatch):
    for v in ("MVP_API_TOKEN", "API_HOST", "MVP_ALLOW_UNAUTH"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("MVP_API_TOKEN", "tok")
    importlib.reload(rc)


# ---------------------------------------------------------------------------
# L4 — clamp helper
# ---------------------------------------------------------------------------


def test_l4_clamp_none_returns_default():
    assert rc.clamp_limit(None, default=50, ceiling=500) == 50


def test_l4_clamp_negative_floored():
    assert rc.clamp_limit(-5, default=50, ceiling=500) == 1
    assert rc.clamp_limit(-5, default=50, ceiling=500, floor=10) == 10


def test_l4_clamp_above_ceiling_capped():
    assert rc.clamp_limit(999_999, default=50, ceiling=500) == 500


def test_l4_clamp_non_numeric_falls_to_default():
    assert rc.clamp_limit("abc", default=50, ceiling=500) == 50  # type: ignore[arg-type]


def test_l4_clamp_in_range_passthrough():
    assert rc.clamp_limit(123, default=50, ceiling=500) == 123


# ---------------------------------------------------------------------------
# L2 — pydantic length caps
# ---------------------------------------------------------------------------


def test_l2_reflection_caps(_safe_env):
    from scripts.api_server import ReflectionBody

    ReflectionBody(reflection_text="ok")
    with pytest.raises(Exception):
        ReflectionBody(reflection_text="")  # empty rejected
    with pytest.raises(Exception):
        ReflectionBody(reflection_text="x" * 4001)


def test_l2_manual_trade_caps(_safe_env):
    from scripts.api_server import ManualTradeBody

    with pytest.raises(Exception):
        ManualTradeBody(
            event_id="E1",
            ticker="AAPL",
            side="LONG",
            quantity="1",
            price="1",
            thesis="x" * 4001,
        )


def test_l2_moltbook_caps(_safe_env):
    from scripts.api_server import MoltbookEntryBody

    with pytest.raises(Exception):
        MoltbookEntryBody(
            event_id="E1",
            ticker="A",
            original_signal_thesis="x" * 4001,
            ai_interpretation="x",
            user_reflection="x",
            final_human_decision="x",
            mistake_type="m",
            lesson_learned="x",
        )


# ---------------------------------------------------------------------------
# L2 — CSV injection escape
# ---------------------------------------------------------------------------


def test_l2_csv_neutralizes_formula_prefixes():
    from scripts.gsheet_export import _neutralize_csv_cell

    for hostile in ("=HYPERLINK(\"x\")", "+CMD", "-2+3", "@SUM(A1)", "\tTAB", "\rCR"):
        out = _neutralize_csv_cell(hostile)
        assert isinstance(out, str)
        assert out.startswith("'"), f"L2 regression: cell {hostile!r} not neutralised"


def test_l2_csv_preserves_safe_text():
    from scripts.gsheet_export import _neutralize_csv_cell

    assert _neutralize_csv_cell("hello") == "hello"
    assert _neutralize_csv_cell("1.5") == "1.5"
    assert _neutralize_csv_cell(None) is None
    assert _neutralize_csv_cell(42) == 42


def test_l2_csv_export_actually_escapes_in_payload(tmp_path, monkeypatch):
    from scripts.gsheet_export import _enforce_advisory, _to_csv

    headers = ["thesis", "ticker", "advisory_status", "execution_mode", "ai_execution_count"]
    rows = [
        {"thesis": "=HYPERLINK(\"https://evil\")", "ticker": "AAPL"},
        {"thesis": "normal text", "ticker": "MSFT"},
    ]
    csv_out = _to_csv(headers, rows)
    # Hostile thesis must be prefixed with apostrophe
    assert "'=HYPERLINK" in csv_out
    # Normal one unchanged
    assert "normal text" in csv_out
    # Advisory invariants stamped
    assert "ADVISORY_ONLY" in csv_out


# ---------------------------------------------------------------------------
# L3 — idempotency replay
# ---------------------------------------------------------------------------


def test_l3_idempotency_lookup_returns_cached(tmp_path):
    import scripts.idempotency as idem

    db = tmp_path / "test_idem.db"
    payload = {"trade_id": "MT_1", "status": "logged"}
    idem.store("POST /manual-trades", "key-abc", payload, db_path=db)
    out = idem.lookup("POST /manual-trades", "key-abc", db_path=db)
    assert out == payload


def test_l3_idempotency_store_is_idempotent(tmp_path):
    import scripts.idempotency as idem

    db = tmp_path / "test_idem.db"
    first = {"trade_id": "MT_1"}
    second = {"trade_id": "MT_2"}
    idem.store("POST /manual-trades", "k", first, db_path=db)
    # Second store with same key MUST NOT overwrite the first
    idem.store("POST /manual-trades", "k", second, db_path=db)
    out = idem.lookup("POST /manual-trades", "k", db_path=db)
    assert out == first


def test_l3_validate_key_caps_oversize():
    import scripts.idempotency as idem

    assert idem.validate_key(None) == ""
    assert idem.validate_key("") == ""
    assert idem.validate_key("ok-key") == "ok-key"
    assert idem.validate_key("x" * 500) == ""  # too long → reject


def test_l3_route_replays_on_repeat_key(tmp_path, monkeypatch, _safe_env):
    """End-to-end: two identical POSTs with same Idempotency-Key MUST
    return the cached body and not produce two persistence calls."""
    import scripts.idempotency as idem

    # Point idempotency cache at a temp DB so we don't touch runtime/
    db = tmp_path / "idem.db"
    monkeypatch.setattr(idem, "_DEFAULT_DB_PATH", db)

    # Stub log_manual_trade so we don't depend on the real DB
    call_count = {"n": 0}

    def _fake_log(**kwargs):
        call_count["n"] += 1
        return {
            "trade_id": f"MT_{call_count['n']}",
            "status": "logged",
            "advisory_status": "ADVISORY_ONLY",
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": 0,
        }

    import scripts.api_server as srv

    importlib.reload(srv)
    monkeypatch.setattr(srv, "log_manual_trade", _fake_log)
    # Also point the api_server's idempotency import at the same temp DB
    monkeypatch.setattr(srv, "_logger", srv._logger)

    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    payload = {
        "event_id": "E1",
        "ticker": "AAPL",
        "side": "LONG",
        "quantity": "10",
        "price": "100",
        "thesis": "test",
    }
    headers = {
        "Authorization": "Bearer tok",
        "Idempotency-Key": "abc-123",
    }

    # Patch the idempotency-store DB path used inside the handler.  We do
    # this by monkeypatching the module-level constant in the freshly
    # reloaded scripts.idempotency module.
    monkeypatch.setattr("scripts.idempotency._DEFAULT_DB_PATH", db)

    r1 = client.post("/manual-trades", json=payload, headers=headers)
    r2 = client.post("/manual-trades", json=payload, headers=headers)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["trade_id"] == "MT_1"
    # Same trade_id on replay -> cache hit
    assert r2.json()["trade_id"] == "MT_1"
    assert r2.json().get("idempotent_replay") is True
    assert call_count["n"] == 1, "L3 regression: handler ran twice"
    # Advisory invariants intact on replay
    assert r2.json()["execution_gate"] == "LOCKED"
    assert r2.json()["broker_api_called"] is False
    assert r2.json()["ai_execution_count"] == 0
