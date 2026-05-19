"""Tests for the Google Sheet -> MVP reconciliation sync.

Covers pure-logic mapping (``decide_row`` / ``build_writeback_updates``)
and the HTTP endpoint contract (``POST /reconciliation/auto-update``).

SAFETY POSTURE assertions are first-class here:
    * advisory_only stays True
    * human_execution_required stays True
    * broker_api_called stays False
    * ai_execution_count stays 0
    * execution_gate stays LOCKED
on every endpoint response, including 400 rejections.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import sync_google_sheet_reconciliation as sync


# ---------------------------------------------------------------------------
# Pure mapping — decide_row
# ---------------------------------------------------------------------------


def _row(**overrides):
    """Build a 26-cell A:Z row populated with sensible defaults."""
    row = [""] * 26
    row[0] = overrides.get("sl_no", "1")              # A
    row[1] = overrides.get("date", "2026-05-19")      # B
    row[2] = overrides.get("ticker", "")              # C
    row[3] = overrides.get("buy_price", "")           # D
    row[4] = overrides.get("sell_price", "")          # E
    row[5] = overrides.get("leverage", "")            # F
    row[6] = overrides.get("country", "")             # G
    row[7] = overrides.get("currency", "")            # H
    row[8] = overrides.get("ai_model", "")            # I
    row[9] = overrides.get("money_allocated", "")     # J
    row[10] = overrides.get("capital_pre_trade", "")  # K
    row[11] = overrides.get("take_profit", "")        # L
    row[12] = overrides.get("stop_loss", "")          # M
    row[13] = overrides.get("ride", "")               # N
    row[14] = overrides.get("profit_loss", "")        # O
    row[15] = overrides.get("live_price", "")         # P
    row[16] = overrides.get("sl_price", "")           # Q
    row[17] = overrides.get("cumulative_pl", "")      # R
    row[18] = overrides.get("tp_price", "")           # S
    row[19] = overrides.get("trade_state", "")        # T
    row[20] = overrides.get("action_required", "")    # U
    row[21] = overrides.get("partial_tp_logged", "")  # V
    row[22] = overrides.get("booked_pct", "")         # W
    row[23] = overrides.get("ride_pct", "")           # X
    row[24] = overrides.get("last_action", "")        # Y
    row[25] = overrides.get("recon_status", "")       # Z
    return row


def test_sap_log_partial_tp_example_produces_log_partial_tp():
    """SAP example: buy 141.22, live 156.72, tp 155.34, U=LOG PARTIAL TP,
    V=NO → outbound action LOG_PARTIAL_TP with booked=70, ride=30."""
    row = _row(
        ticker="SAP.DE",
        buy_price="141.22",
        live_price="156.72",
        sl_price="135.00",
        tp_price="155.34",
        action_required="LOG PARTIAL TP",
        partial_tp_logged="NO",
    )
    decision = sync.decide_row(row, sheet_row_number=2)
    assert decision.action == sync.OUT_LOG_PARTIAL_TP
    assert decision.ticker == "SAP.DE"
    assert decision.booked_percent == 70.0
    assert decision.ride_percent == 30.0
    assert decision.live_price == pytest.approx(156.72)
    assert decision.tp_price == pytest.approx(155.34)
    assert decision.sl_price == pytest.approx(135.00)

    payload = decision.to_payload()
    # Safety stamps are baked into every outbound payload.
    assert payload["advisory_only"] is True
    assert payload["human_execution_required"] is True
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_gate"] == "LOCKED"
    assert payload["source"] == "google_sheet_sync"
    assert payload["sheet_row_number"] == 2


def test_partial_tp_already_logged_is_not_duplicated():
    """V == YES → LOG_PARTIAL_TP must not re-fire."""
    row = _row(
        ticker="SAP.DE",
        action_required="LOG PARTIAL TP",
        partial_tp_logged="YES",
    )
    decision = sync.decide_row(row, sheet_row_number=2)
    assert decision.action is None
    assert decision.skip_reason == "partial_tp_already_logged"


def test_stop_hit_maps_to_stop_hit():
    row = _row(ticker="AAPL", action_required="STOP HIT", sl_price="180.0")
    decision = sync.decide_row(row, sheet_row_number=3)
    assert decision.action == sync.OUT_STOP_HIT
    assert decision.sl_price == pytest.approx(180.0)


def test_close_trade_maps_to_close_trade():
    row = _row(ticker="TLT", action_required="CLOSE TRADE")
    decision = sync.decide_row(row, sheet_row_number=4)
    assert decision.action == sync.OUT_CLOSE_TRADE


def test_reconcile_update_outcome_maps_to_reconcile_update_outcome():
    row = _row(
        ticker="RELIANCE.NS",
        action_required="RECONCILE / UPDATE OUTCOME",
    )
    decision = sync.decide_row(row, sheet_row_number=5)
    assert decision.action == sync.OUT_RECONCILE_UPDATE


def test_blank_ticker_and_blank_action_are_skipped():
    assert sync.decide_row(_row(), sheet_row_number=6).action is None
    assert (
        sync.decide_row(_row(ticker="FOO"), sheet_row_number=7).skip_reason
        == "no_action_required"
    )


def test_unknown_action_is_skipped_not_sent():
    row = _row(ticker="FOO", action_required="HOLD AND PRAY")
    decision = sync.decide_row(row, sheet_row_number=8)
    assert decision.action is None
    assert decision.skip_reason.startswith("unknown_action:")


def test_currency_and_percent_strings_parse_cleanly():
    row = _row(
        ticker="SAP.DE",
        live_price="$156.72",
        tp_price="155.34",
        sl_price="135",
        action_required="LOG PARTIAL TP",
        partial_tp_logged="NO",
    )
    decision = sync.decide_row(row, sheet_row_number=2)
    assert decision.live_price == pytest.approx(156.72)
    assert decision.sl_price == pytest.approx(135.0)


# ---------------------------------------------------------------------------
# Writeback rules
# ---------------------------------------------------------------------------


def test_writeback_log_partial_tp_writes_v_w_x_y_z():
    decision = sync.SheetRowDecision(
        sheet_row_number=2,
        ticker="SAP.DE",
        action=sync.OUT_LOG_PARTIAL_TP,
        booked_percent=70,
        ride_percent=30,
    )
    updates = dict(
        sync.build_writeback_updates(
            decision, now_iso="2026-05-19T12:00:00+00:00"
        )
    )
    assert updates["V"] == "YES"
    assert updates["W"] == "70%"
    assert updates["X"] == "30%"
    assert "LOG_PARTIAL_TP_SYNCED" in updates["Y"]
    assert updates["Z"] == "PARTIAL_TP_LOGGED"


def test_writeback_stop_hit_marks_pending_close():
    decision = sync.SheetRowDecision(
        sheet_row_number=3, ticker="AAPL", action=sync.OUT_STOP_HIT
    )
    updates = dict(
        sync.build_writeback_updates(
            decision, now_iso="2026-05-19T12:00:00+00:00"
        )
    )
    assert "STOP_HIT_SYNCED" in updates["Y"]
    assert updates["Z"] == "STOP_HIT_PENDING_CLOSE"


def test_writeback_close_trade_marks_closed():
    decision = sync.SheetRowDecision(
        sheet_row_number=4, ticker="TLT", action=sync.OUT_CLOSE_TRADE
    )
    updates = dict(
        sync.build_writeback_updates(
            decision, now_iso="2026-05-19T12:00:00+00:00"
        )
    )
    assert updates["Z"] == "CLOSED"


def test_writeback_reconcile_preserves_terminal_status():
    """RECONCILE_UPDATE_OUTCOME on a PARTIAL_TP_LOGGED or CLOSED row must
    NOT downgrade column Z back to OPEN_RECONCILED."""
    decision = sync.SheetRowDecision(
        sheet_row_number=5, ticker="X", action=sync.OUT_RECONCILE_UPDATE
    )
    for terminal in ("PARTIAL_TP_LOGGED", "CLOSED"):
        updates = dict(
            sync.build_writeback_updates(
                decision,
                now_iso="2026-05-19T12:00:00+00:00",
                existing_recon_status=terminal,
            )
        )
        assert "Z" not in updates, terminal
        assert "RECONCILED" in updates["Y"]


def test_writeback_reconcile_sets_open_reconciled_when_empty():
    decision = sync.SheetRowDecision(
        sheet_row_number=5, ticker="X", action=sync.OUT_RECONCILE_UPDATE
    )
    updates = dict(
        sync.build_writeback_updates(
            decision, now_iso="2026-05-19T12:00:00+00:00",
            existing_recon_status="",
        )
    )
    assert updates["Z"] == "OPEN_RECONCILED"


# ---------------------------------------------------------------------------
# _process_rows — orchestration with a fake poster & updater
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_process_rows_skips_header_posts_actionable_and_writes_back():
    config = sync.SyncConfig(
        sheet_id="SID", service_account_json="SA", worksheet_name=None,
        mvp_endpoint="http://example/reconciliation/auto-update",
        dry_run=False, loop=False, interval_minutes=30,
    )
    posted: list[dict] = []
    written: list[tuple[int, list]] = []

    def fake_poster(endpoint: str, payload: dict):
        posted.append(payload)
        return _FakeResp(200, "ok")

    def fake_updater(_ws, row_no: int, updates):
        written.append((row_no, list(updates)))

    header = ["SL", "DATE"] + [""] * 24
    rows = [
        header,
        _row(
            ticker="SAP.DE",
            buy_price="141.22",
            live_price="156.72",
            tp_price="155.34",
            sl_price="135",
            action_required="LOG PARTIAL TP",
            partial_tp_logged="NO",
        ),
        _row(
            ticker="SAP.DE",
            action_required="LOG PARTIAL TP",
            partial_tp_logged="YES",
        ),
        _row(ticker="", action_required=""),
        _row(ticker="AAPL", action_required="STOP HIT"),
    ]

    counts = sync._process_rows(
        rows, config=config, worksheet=object(),
        now_iso_fn=lambda: "2026-05-19T12:00:00+00:00",
        poster=fake_poster, updater=fake_updater,
    )
    assert counts["scanned"] == 5
    assert counts["posted"] == 2          # SAP partial TP + AAPL stop hit
    assert counts["writeback_applied"] == 2
    assert {p["action"] for p in posted} == {"LOG_PARTIAL_TP", "STOP_HIT"}
    # Every outbound payload preserves the LOCKED safety stamps.
    for p in posted:
        assert p["broker_api_called"] is False
        assert p["ai_execution_count"] == 0
        assert p["execution_gate"] == "LOCKED"
        assert p["advisory_only"] is True
        assert p["human_execution_required"] is True


def test_process_rows_dry_run_does_not_post_or_write():
    config = sync.SyncConfig(
        sheet_id="SID", service_account_json="SA", worksheet_name=None,
        mvp_endpoint="http://example/x",
        dry_run=True, loop=False, interval_minutes=30,
    )

    def boom(*_a, **_k):
        raise AssertionError("must not be called in dry-run")

    rows = [
        ["HEADER"] + [""] * 25,
        _row(ticker="SAP.DE", action_required="LOG PARTIAL TP",
             partial_tp_logged="NO"),
    ]
    counts = sync._process_rows(
        rows, config=config, worksheet=object(),
        now_iso_fn=lambda: "2026-05-19T12:00:00+00:00",
        poster=boom, updater=boom,
    )
    assert counts["posted"] == 1
    assert counts["writeback_applied"] == 0


def test_process_rows_skips_writeback_when_post_fails():
    config = sync.SyncConfig(
        sheet_id="SID", service_account_json="SA", worksheet_name=None,
        mvp_endpoint="http://example/x",
        dry_run=False, loop=False, interval_minutes=30,
    )
    written: list = []

    def fake_poster(_e, _p):
        return _FakeResp(500, "boom")

    def fake_updater(*_a, **_k):
        written.append(_a)

    rows = [
        ["HEADER"] + [""] * 25,
        _row(ticker="AAPL", action_required="STOP HIT"),
    ]
    counts = sync._process_rows(
        rows, config=config, worksheet=object(),
        now_iso_fn=lambda: "2026-05-19T12:00:00+00:00",
        poster=fake_poster, updater=fake_updater,
    )
    assert counts["failed"] == 1
    assert counts["writeback_applied"] == 0
    assert written == []


# ---------------------------------------------------------------------------
# HTTP endpoint contract — /reconciliation/auto-update
# ---------------------------------------------------------------------------


fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    import scripts.api_server as srv
    importlib.reload(srv)
    return TestClient(srv.app)


_BASE_PAYLOAD = {
    "ticker": "SAP.DE",
    "action": "LOG_PARTIAL_TP",
    "live_price": 156.72,
    "tp_price": 155.34,
    "sl_price": 135.0,
    "booked_percent": 70,
    "ride_percent": 30,
    "sheet_row_number": 2,
    "source": "google_sheet_sync",
    "advisory_only": True,
    "human_execution_required": True,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_gate": "LOCKED",
}


def _safety_stamps_locked(body: dict) -> None:
    assert body["advisory_only"] is True
    assert body["human_execution_required"] is True
    assert body["broker_api_called"] is False
    assert body["ai_execution_count"] == 0
    assert body["execution_gate"] == "LOCKED"
    assert body["broker_order_id"] == "NONE"
    assert body["execution_permission"] is False
    assert body["can_execute"] is False
    assert body["human_review_required"] is True
    assert body["record_keeping_only"] is True


@pytest.mark.parametrize(
    "action",
    ["LOG_PARTIAL_TP", "STOP_HIT", "CLOSE_TRADE", "RECONCILE_UPDATE_OUTCOME"],
)
def test_endpoint_accepts_each_known_action(client, action, tmp_path,
                                            monkeypatch):
    """Each of the four bookkeeping actions yields 200 + locked stamps."""
    # Redirect the audit log to a tmp dir so the test never pollutes
    # logs/sheet_sync_reconciliation_audit.jsonl in the repo.
    import scripts.runtime_common as rc
    monkeypatch.setattr(rc, "LOG_DIR", tmp_path, raising=True)

    payload = dict(_BASE_PAYLOAD)
    payload["action"] = action
    resp = client.post("/reconciliation/auto-update", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "recorded"
    assert body["action"] == action
    _safety_stamps_locked(body)


def test_endpoint_rejects_unknown_action(client):
    payload = dict(_BASE_PAYLOAD)
    payload["action"] = "PLACE_BROKER_ORDER"   # hostile-sounding on purpose
    resp = client.post("/reconciliation/auto-update", json=payload)
    assert resp.status_code == 400
    body = resp.json()
    detail = body["detail"]
    assert detail["reason"] == "unknown_action"
    assert "PLACE_BROKER_ORDER" in detail["message"]
    # Even the rejection echoes the LOCKED safety stamps.
    assert detail["broker_api_called"] is False
    assert detail["ai_execution_count"] == 0
    assert detail["execution_gate"] == "LOCKED"
    assert detail["execution_mode"] == "HUMAN_ONLY"
    assert detail["advisory_status"] == "ADVISORY_ONLY"
    assert detail["human_review_required"] is True
    assert detail["record_keeping_only"] is True


def test_endpoint_ignores_attempt_to_flip_safety_stamps(
    client, tmp_path, monkeypatch
):
    """Even if a malicious caller flips the safety flags on the wire,
    the server response MUST reassert LOCKED / 0 / False."""
    import scripts.runtime_common as rc
    monkeypatch.setattr(rc, "LOG_DIR", tmp_path, raising=True)

    payload = dict(_BASE_PAYLOAD)
    payload["broker_api_called"] = True       # hostile
    payload["ai_execution_count"] = 9         # hostile
    payload["execution_gate"] = "UNLOCKED"    # hostile
    payload["advisory_only"] = False          # hostile
    payload["human_execution_required"] = False  # hostile
    resp = client.post("/reconciliation/auto-update", json=payload)
    assert resp.status_code == 200, resp.text
    _safety_stamps_locked(resp.json())


def test_endpoint_writes_audit_jsonl(client, tmp_path, monkeypatch):
    """A successful POST must leave a record in the JSONL audit log."""
    import scripts.runtime_common as rc
    monkeypatch.setattr(rc, "LOG_DIR", tmp_path, raising=True)

    payload = dict(_BASE_PAYLOAD)
    payload["action"] = "STOP_HIT"
    payload["ticker"] = "AAPL"
    resp = client.post("/reconciliation/auto-update", json=payload)
    assert resp.status_code == 200, resp.text

    audit_path = tmp_path / "sheet_sync_reconciliation_audit.jsonl"
    assert audit_path.is_file()
    import json
    rows = [
        json.loads(line) for line in audit_path.read_text(
            encoding="utf-8"
        ).splitlines() if line.strip()
    ]
    assert rows
    last = rows[-1]
    assert last["action"] == "STOP_HIT"
    assert last["ticker"] == "AAPL"
    assert last["broker_api_called"] is False
    assert last["ai_execution_count"] == 0
    assert last["execution_gate"] == "LOCKED"
    assert last["record_keeping_only"] is True


# ---------------------------------------------------------------------------
# Defence in depth — there is no broker execution path in this script.
# ---------------------------------------------------------------------------


def test_script_has_no_broker_execution_path():
    """Static guard: the module must NOT reference any broker SDK or
    order-placement verb.  The string ``broker_api_called`` is allowed
    (it is the safety stamp itself) but anything resembling a real
    broker integration (alpaca, kiteconnect, ibapi, ...) must not appear.
    """
    src = (
        _REPO / "scripts" / "sync_google_sheet_reconciliation.py"
    ).read_text(encoding="utf-8")
    forbidden = [
        "place_order",
        "submit_order",
        "place_broker_order",
        "broker_client",
        "alpaca",
        "interactive_brokers",
        "ibapi",
        "ib_insync",
        "zerodha",
        "kiteconnect",
        "robinhood",
        "etrade",
        "tradier",
    ]
    src_lc = src.lower()
    for token in forbidden:
        assert token not in src_lc, f"forbidden token in sync script: {token}"
