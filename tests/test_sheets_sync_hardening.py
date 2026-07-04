"""Tests: Sheets sync hardening (Feed-the-Loop sprint, audit segment H).

Pins:
* schema drift (header row looks like data) aborts the run fail-closed;
* STOP_HIT/CLOSE_TRADE rows already marked _SYNCED in column Y re-fire no
  POST (idempotency beyond LOG_PARTIAL_TP);
* every outbound payload carries a deterministic client dedupe_key;
* _post_to_mvp sends Authorization when MVP_API_TOKEN is set (and no header
  when unset) — security and sync can finally be on at the same time.
"""
from __future__ import annotations

import scripts.sync_google_sheet_reconciliation as sync
from tests.test_sync_google_sheet_reconciliation import _FakeResp, _row


def _config():
    return sync.SyncConfig(
        sheet_id="SID", service_account_json="SA", worksheet_name=None,
        mvp_endpoint="http://example/reconciliation/auto-update",
        dry_run=False, loop=False, interval_minutes=30,
    )


HEADER = ["SL", "DATE"] + [""] * 24


def _stop_hit_row(**over):
    base = dict(
        ticker="SAP.DE", buy_price="141.22", live_price="120.00",
        sl_price="135", action_required="STOP HIT",
    )
    base.update(over)
    return _row(**base)


def test_schema_drift_aborts_run_fail_closed():
    posted: list[dict] = []
    data_looking_header = _stop_hit_row()  # row 1 IS a trade row: drift
    counts = sync._process_rows(
        [data_looking_header, _stop_hit_row()],
        config=_config(), worksheet=None,
        now_iso_fn=lambda: "2026-07-04T12:00:00Z",
        poster=lambda e, p: posted.append(p) or _FakeResp(200, "ok"),
        updater=lambda *a, **k: None,
    )
    assert counts.get("schema_drift") == 1
    assert posted == [], "no row may be posted after schema drift is detected"


def test_header_row_recognized_as_header_not_drift():
    counts = sync._process_rows(
        [HEADER],
        config=_config(), worksheet=None,
        now_iso_fn=lambda: "2026-07-04T12:00:00Z",
        poster=lambda e, p: _FakeResp(200, "ok"),
        updater=lambda *a, **k: None,
    )
    assert "schema_drift" not in counts
    assert counts["skipped"] == 1


def test_already_synced_stop_hit_refires_nothing():
    posted: list[dict] = []
    synced_row = _stop_hit_row(
        last_action="2026-07-03T10:00:00Z | STOP_HIT_SYNCED"
    )
    counts = sync._process_rows(
        [HEADER, synced_row],
        config=_config(), worksheet=None,
        now_iso_fn=lambda: "2026-07-04T12:00:00Z",
        poster=lambda e, p: posted.append(p) or _FakeResp(200, "ok"),
        updater=lambda *a, **k: None,
    )
    assert posted == [], "STOP_HIT re-fired despite Y=_SYNCED (idempotency)"
    assert counts["posted"] == 0


def test_payloads_carry_deterministic_dedupe_key():
    posted: list[dict] = []
    sync._process_rows(
        [HEADER, _stop_hit_row()],
        config=_config(), worksheet=None,
        now_iso_fn=lambda: "2026-07-04T12:00:00Z",
        poster=lambda e, p: posted.append(p) or _FakeResp(200, "ok"),
        updater=lambda *a, **k: None,
    )
    assert len(posted) == 1
    key = posted[0].get("dedupe_key")
    assert key and len(key) == 32
    # deterministic per (row, ticker, action, day)
    posted2: list[dict] = []
    sync._process_rows(
        [HEADER, _stop_hit_row()],
        config=_config(), worksheet=None,
        now_iso_fn=lambda: "2026-07-04T12:00:00Z",
        poster=lambda e, p: posted2.append(p) or _FakeResp(200, "ok"),
        updater=lambda *a, **k: None,
    )
    assert posted2[0]["dedupe_key"] == key


def test_post_sends_bearer_only_when_token_set(monkeypatch):
    captured: dict = {}

    class _FakeRequests:
        @staticmethod
        def post(endpoint, json=None, timeout=None, headers=None):
            captured.update({"headers": headers or {}})
            return _FakeResp(200, "ok")

    import sys as _sys

    monkeypatch.setitem(_sys.modules, "requests", _FakeRequests)
    monkeypatch.setenv("MVP_API_TOKEN", "test-token-value")
    sync._post_to_mvp("http://example/x", {"dedupe_key": "abc"})
    assert captured["headers"].get("Authorization") == "Bearer test-token-value"
    assert captured["headers"].get("Idempotency-Key") == "abc"

    monkeypatch.delenv("MVP_API_TOKEN")
    captured.clear()
    sync._post_to_mvp("http://example/x", {})
    assert "Authorization" not in captured["headers"]
