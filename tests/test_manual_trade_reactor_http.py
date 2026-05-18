"""Sprint 7B.1 — close the reactor-snapshot HTTP path.

Verify that ``POST /manual-trades`` accepts the 9 reactor-at-decision
fields, passes them through to ``log_manual_trade`` / ``insert_manual_trade``,
that they end up persisted in ``manual_trades`` and visible to the reactor
calibration report, and that legacy payloads without these fields keep
working.  Also verify that hostile / out-of-band values normalise safely
(scores clamp / NULL, booleans coerce, no crash) and that the safety
stamps are preserved on every response.

No broker / execution language is ever introduced by this path; that is
asserted by ``test_frontend_no_execution_language`` and the token-gate
contract tests, so here we focus on plumbing + normalisation.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from scripts import persistence
from scripts import signal_inbox_api


def _rebind_defaults(fn, new_db: Path) -> None:
    if fn.__defaults__:
        new_defs = tuple(new_db if isinstance(d, Path) else d for d in fn.__defaults__)
        fn.__defaults__ = new_defs
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "reactor_http.db"
    persistence.init_schema(db)
    helper_names = [
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_trades_for_event",
        "get_event_id_for_trade",
        "get_all_manual_trades",
        "insert_reconciliation",
        "get_reconciliations_for_trade",
        "get_all_reconciliations",
    ]
    originals: dict = {}
    for name in helper_names:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(signal_inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(signal_inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(signal_inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    try:
        yield db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


@pytest.fixture()
def client(monkeypatch, tmp_db):
    monkeypatch.delenv("MVP_API_TOKEN", raising=False)
    import scripts.api_server as srv
    importlib.reload(srv)
    return TestClient(srv.app)


def _safety_stamps_ok(resp: dict) -> None:
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["ai_execution_count"] == 0
    assert resp["broker_api_called"] is False
    assert resp["broker_order_id"] == "NONE"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["execution_permission"] is False
    assert resp["can_execute"] is False
    assert resp["human_review_required"] is True


_REACTOR_PAYLOAD_FULL = {
    "event_id": "EV_REACTOR_FULL",
    "ticker": "ETH",
    "side": "BUY",
    "quantity": 2.0,
    "price": 1500.0,
    "thesis": "reactor http snapshot coverage sentence",
    "reactor_state_at_decision": "WARM_WATCH",
    "decision_grade_energy_at_decision": 0.42,
    "echo_risk_score_at_decision": 0.18,
    "meltdown_risk_at_decision": 0.21,
    "fusion_validity_at_decision": "weak_fusion",
    "fission_branch_clarity_at_decision": 0.6,
    "operator_heat_at_decision": 0.15,
    "gallardo_block_at_decision": False,
    "preflight_state_at_decision": "OK",
}


def test_post_manual_trades_with_full_reactor_payload(client) -> None:
    r = client.post("/manual-trades", json=_REACTOR_PAYLOAD_FULL)
    assert r.status_code == 200, r.text
    body = r.json()
    _safety_stamps_ok(body)
    assert body["status"] == "logged"
    # Reactor fields round-trip through the response.
    assert body["reactor_state_at_decision"] == "WARM_WATCH"
    assert body["decision_grade_energy_at_decision"] == pytest.approx(0.42)
    assert body["echo_risk_score_at_decision"] == pytest.approx(0.18)
    assert body["meltdown_risk_at_decision"] == pytest.approx(0.21)
    assert body["fusion_validity_at_decision"] == "weak_fusion"
    assert body["fission_branch_clarity_at_decision"] == pytest.approx(0.6)
    assert body["operator_heat_at_decision"] == pytest.approx(0.15)
    assert body["gallardo_block_at_decision"] is False
    assert body["preflight_state_at_decision"] == "OK"


def test_post_manual_trades_legacy_payload_still_works(client, monkeypatch) -> None:
    """Legacy frontend that omits reactor fields entirely must keep working.

    After the auto-attach helper was added, a legacy payload may now have
    reactor fields populated automatically from the live inbox.  The
    legacy contract is preserved when no inbox verdict is available:
    fields stay empty and the response reports
    ``reactor_snapshot_source == "unavailable"``.
    """
    # Force the auto-attach lookup to return nothing so we test the
    # legacy-empty branch explicitly.
    monkeypatch.setattr(
        "scripts.signal_inbox_api.get_signal_detail",
        lambda event_id: {"operation": "get_signal_detail", "signal": {}},
        raising=True,
    )
    legacy = {
        "event_id": "EV_LEGACY",
        "ticker": "BTC",
        "side": "BUY",
        "quantity": 0.1,
        "price": 50000.0,
        "thesis": "legacy client thesis",
    }
    r = client.post("/manual-trades", json=legacy)
    assert r.status_code == 200, r.text
    body = r.json()
    _safety_stamps_ok(body)
    assert body["status"] == "logged"
    assert body["reactor_snapshot_source"] == "unavailable"
    # Reactor fields default to empty / None.  The gallardo boolean
    # defaults to False (no block recorded) so legacy rows are safe to
    # render in the UI without optional-chaining everywhere.
    assert body["reactor_state_at_decision"] == ""
    assert body["decision_grade_energy_at_decision"] is None
    assert body["echo_risk_score_at_decision"] is None
    assert body["meltdown_risk_at_decision"] is None
    assert body["fusion_validity_at_decision"] == ""
    assert body["fission_branch_clarity_at_decision"] is None
    assert body["operator_heat_at_decision"] is None
    assert body["gallardo_block_at_decision"] is False
    assert body["preflight_state_at_decision"] == ""


def test_post_manual_trades_clamps_hostile_scores(client) -> None:
    """Out-of-band scores must normalise to None (not crash, not persist garbage)."""
    hostile = dict(_REACTOR_PAYLOAD_FULL)
    hostile["event_id"] = "EV_HOSTILE_SCORES"
    hostile["decision_grade_energy_at_decision"] = 9999.0  # > 1.0
    hostile["echo_risk_score_at_decision"] = -42.0  # < 0.0
    hostile["meltdown_risk_at_decision"] = 1.0001  # just past upper bound
    hostile["fission_branch_clarity_at_decision"] = 1.5  # > 1.0
    hostile["operator_heat_at_decision"] = -0.0001  # < 0.0
    r = client.post("/manual-trades", json=hostile)
    assert r.status_code == 200, r.text
    body = r.json()
    _safety_stamps_ok(body)
    # Each out-of-band score should normalise to None.
    assert body["decision_grade_energy_at_decision"] is None
    assert body["echo_risk_score_at_decision"] is None
    assert body["meltdown_risk_at_decision"] is None
    assert body["fission_branch_clarity_at_decision"] is None
    assert body["operator_heat_at_decision"] is None


def test_post_manual_trades_coerces_gallardo_block(client) -> None:
    """`gallardo_block_at_decision=true` (bool) must persist as truthy."""
    payload = dict(_REACTOR_PAYLOAD_FULL)
    payload["event_id"] = "EV_GALLARDO"
    payload["gallardo_block_at_decision"] = True
    r = client.post("/manual-trades", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    _safety_stamps_ok(body)
    assert body["gallardo_block_at_decision"] is True


def test_reactor_snapshot_persisted_in_manual_trades_table(client, tmp_db: Path) -> None:
    """Calibration depends on the row landing in the manual_trades table
    with the reactor columns populated.  Read it back via the persistence
    layer to prove the HTTP path closed."""
    r = client.post("/manual-trades", json=_REACTOR_PAYLOAD_FULL)
    assert r.status_code == 200, r.text
    rows = persistence.get_all_manual_trades(tmp_db)
    matches = [row for row in rows if row["event_id"] == "EV_REACTOR_FULL"]
    assert len(matches) == 1
    row = matches[0]
    assert row["reactor_state_at_decision"] == "WARM_WATCH"
    assert row["decision_grade_energy_at_decision"] == pytest.approx(0.42)
    assert row["echo_risk_score_at_decision"] == pytest.approx(0.18)
    assert row["meltdown_risk_at_decision"] == pytest.approx(0.21)
    assert row["fusion_validity_at_decision"] == "weak_fusion"
    assert row["fission_branch_clarity_at_decision"] == pytest.approx(0.6)
    assert row["operator_heat_at_decision"] == pytest.approx(0.15)
    assert int(row["gallardo_block_at_decision"]) == 0
    assert row["preflight_state_at_decision"] == "OK"
    # Safety columns intact.
    assert row["broker_api_called"] is False or int(row["broker_api_called"]) == 0
    assert row["broker_order_id"] == "NONE"


def test_reactor_calibration_sees_http_created_snapshot(client, tmp_db: Path) -> None:
    """End-to-end: POST a reactor snapshot via HTTP, then run the reactor
    calibration report against the same DB — it must observe the snapshot
    we just inserted."""
    r = client.post("/manual-trades", json=_REACTOR_PAYLOAD_FULL)
    assert r.status_code == 200, r.text

    try:
        from scripts.reactor_calibration_report import build_report
    except Exception:
        pytest.skip("reactor_calibration_report not importable")

    payload = build_report(tmp_db)
    # Safety stamps preserved by the report itself.
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["broker_api_called"] is False
    assert payload["execution_gate"] == "LOCKED"
    # The report must report at least one snapshot present.
    calibration = payload.get("calibration") or {}
    snap_count = int(calibration.get("reactor_snapshot_count", 0))
    assert snap_count >= 1
    # And no missing_decision_fields, since the row went through with all
    # 9 reactor columns populated.
    assert "reactor_at_decision_fields_not_persisted" not in (
        payload.get("limitations") or []
    )


def test_post_manual_trades_response_preserves_advisory_stamps(client) -> None:
    r = client.post("/manual-trades", json=_REACTOR_PAYLOAD_FULL)
    assert r.status_code == 200, r.text
    body = r.json()
    # Verbose safety contract — every stamp must survive the reactor path.
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert body["execution_mode"] == "HUMAN_ONLY"
    assert body["execution_gate"] == "LOCKED"
    assert body["execution_permission"] is False
    assert body["can_execute"] is False
    assert body["broker_api_called"] is False
    assert body["broker_order_id"] == "NONE"
    assert body["ai_execution_count"] == 0
    assert body["human_review_required"] is True
