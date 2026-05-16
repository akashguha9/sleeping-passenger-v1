"""Auto-attach reactor snapshot at manual/paper write time.

Defensive-engineering fix for ``reactor_snapshot_count = 0`` in the
Outcome Calibration Gate.  When the operator does not hand-fill the
nine reactor-at-decision fields, the system reaches into the live
Signal Reactor for the same event and attaches a snapshot.

These tests verify (in order):

* Explicit reactor fields are NEVER overwritten by auto-attach.
* When the inbox lookup produces a usable reactor verdict, the snapshot
  is attached and the response reports ``reactor_snapshot_source ==
  "attached_from_signal"``.
* When no usable verdict exists, the row is still written, the snapshot
  fields stay empty, and the response reports
  ``reactor_snapshot_source == "unavailable"``.
* Paper-ledger import benefits from the same auto-attach via
  ``source_signal_id``.
* Paper imports with explicit reactor fields preserve those values.
* Safety stamps remain locked on every response.
* No broker / execution language is introduced.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from scripts import persistence
from scripts import paper_trade_ledger
from scripts import reactor_snapshot_attach
from scripts import signal_inbox_api


def _rebind_defaults(fn, new_db: Path) -> None:
    if fn.__defaults__:
        fn.__defaults__ = tuple(
            new_db if isinstance(d, Path) else d for d in fn.__defaults__
        )
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "auto_attach.db"
    persistence.init_schema(db)
    for name in (
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_trades_for_event",
        "get_all_manual_trades",
        "insert_reconciliation",
        "get_reconciliations_for_trade",
        "get_all_reconciliations",
    ):
        fn = getattr(persistence, name, None)
        if fn is not None:
            _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(signal_inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(signal_inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(signal_inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    return db


def _fake_signal(state: str = "WARM_WATCH") -> dict[str, Any]:
    """Minimal decorated-inbox-item dict shape consumed by the helper."""
    return {
        "reactor_available": True,
        "reactor_state": state,
        "decision_grade_energy": 0.31,
        "echo_risk_score": 0.12,
        "meltdown_risk_score": 0.08,
        "fusion_validity": "weak_fusion",
        "fission_branch_clarity": 0.55,
        "operator_heat_score": 0.05,
        "gallardo_block": False,
    }


def _install_fake_get_signal_detail(
    monkeypatch: pytest.MonkeyPatch, signal: dict[str, Any] | None
) -> None:
    """Patch the helper's lookup so the inbox/fabric/DB stack is not exercised."""
    def _fake(event_id: str) -> dict[str, Any]:
        return {"operation": "get_signal_detail", "signal": signal or {}}

    monkeypatch.setattr(
        "scripts.signal_inbox_api.get_signal_detail", _fake, raising=True
    )


def _safety_stamps_ok(payload: dict[str, Any]) -> None:
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False
    assert payload["broker_api_called"] is False
    assert payload["broker_order_id"] == "NONE"
    assert payload["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_helper_returns_provided_when_caller_set_state() -> None:
    explicit = {"reactor_state_at_decision": "WARM_WATCH"}
    src, snap = reactor_snapshot_attach.maybe_attach_reactor_snapshot(
        explicit, event_id="EV_X"
    )
    assert src == reactor_snapshot_attach.ATTACH_PROVIDED
    assert snap == {}


def test_helper_returns_provided_when_caller_set_explicit_false_gallardo() -> None:
    # A deliberate False for gallardo_block_at_decision is a real choice
    # and must NOT trigger an overwrite by auto-attach.
    explicit = {"gallardo_block_at_decision": False}
    src, _ = reactor_snapshot_attach.maybe_attach_reactor_snapshot(
        explicit, event_id="EV_X"
    )
    assert src == reactor_snapshot_attach.ATTACH_PROVIDED


def test_helper_returns_unavailable_when_no_event_and_no_lookup() -> None:
    src, snap = reactor_snapshot_attach.maybe_attach_reactor_snapshot(
        {}, event_id="", source_signal_id=""
    )
    assert src == reactor_snapshot_attach.ATTACH_UNAVAILABLE
    assert snap == {}


def test_helper_attaches_from_signal_when_inbox_has_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_get_signal_detail(monkeypatch, _fake_signal("FUSION_REVIEW_CANDIDATE"))
    src, snap = reactor_snapshot_attach.maybe_attach_reactor_snapshot(
        {}, event_id="EV_LIVE"
    )
    assert src == reactor_snapshot_attach.ATTACH_FROM_SIGNAL
    assert snap["reactor_state_at_decision"] == "FUSION_REVIEW_CANDIDATE"
    assert snap["decision_grade_energy_at_decision"] == pytest.approx(0.31)
    assert snap["echo_risk_score_at_decision"] == pytest.approx(0.12)
    assert snap["meltdown_risk_at_decision"] == pytest.approx(0.08)
    assert snap["fusion_validity_at_decision"] == "weak_fusion"
    assert snap["fission_branch_clarity_at_decision"] == pytest.approx(0.55)
    assert snap["operator_heat_at_decision"] == pytest.approx(0.05)
    assert snap["gallardo_block_at_decision"] is False
    # preflight is intentionally not derived from inbox decoration.
    assert "preflight_state_at_decision" not in snap


def test_helper_refuses_insufficient_data_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insufficient = _fake_signal("INSUFFICIENT_DATA")
    insufficient["reactor_available"] = True
    _install_fake_get_signal_detail(monkeypatch, insufficient)
    src, snap = reactor_snapshot_attach.maybe_attach_reactor_snapshot(
        {}, event_id="EV_INSUFFICIENT"
    )
    assert src == reactor_snapshot_attach.ATTACH_UNAVAILABLE
    assert snap == {}


def test_helper_returns_unavailable_when_reactor_unavailable_flag_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = _fake_signal()
    bad["reactor_available"] = False
    _install_fake_get_signal_detail(monkeypatch, bad)
    src, _ = reactor_snapshot_attach.maybe_attach_reactor_snapshot(
        {}, event_id="EV_DEAD"
    )
    assert src == reactor_snapshot_attach.ATTACH_UNAVAILABLE


# ---------------------------------------------------------------------------
# log_manual_trade end-to-end
# ---------------------------------------------------------------------------


def test_log_manual_trade_auto_attaches_when_inbox_has_verdict(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_get_signal_detail(monkeypatch, _fake_signal("WARM_WATCH"))
    result = signal_inbox_api.log_manual_trade(
        event_id="EV_AUTO_ATTACH",
        ticker="BTC",
        side="BUY",
        quantity=0.1,
        price=50000.0,
        thesis="auto-attach exercise",
    )
    _safety_stamps_ok(result)
    assert result["reactor_snapshot_source"] == "attached_from_signal"
    assert result["reactor_state_at_decision"] == "WARM_WATCH"
    assert result["decision_grade_energy_at_decision"] == pytest.approx(0.31)
    # The row landed in the DB with the snapshot, which is what the
    # calibration gate counts.
    rows = persistence.get_all_manual_trades(tmp_db)
    matches = [r for r in rows if r["event_id"] == "EV_AUTO_ATTACH"]
    assert len(matches) == 1
    assert matches[0]["reactor_state_at_decision"] == "WARM_WATCH"


def test_log_manual_trade_preserves_explicit_reactor_fields(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even if the inbox has a different verdict, explicit caller values win.
    _install_fake_get_signal_detail(monkeypatch, _fake_signal("FISSION_MAP_ONLY"))
    result = signal_inbox_api.log_manual_trade(
        event_id="EV_EXPLICIT_WINS",
        ticker="BTC",
        side="BUY",
        quantity=0.1,
        price=50000.0,
        thesis="explicit wins",
        reactor_state_at_decision="COLD_OBSERVE",
        decision_grade_energy_at_decision=0.9,
    )
    _safety_stamps_ok(result)
    assert result["reactor_snapshot_source"] == "provided_explicitly"
    assert result["reactor_state_at_decision"] == "COLD_OBSERVE"
    assert result["decision_grade_energy_at_decision"] == pytest.approx(0.9)


def test_log_manual_trade_unavailable_when_no_inbox_signal(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_get_signal_detail(monkeypatch, None)
    result = signal_inbox_api.log_manual_trade(
        event_id="EV_NO_INBOX",
        ticker="BTC",
        side="BUY",
        quantity=0.1,
        price=50000.0,
        thesis="no inbox signal",
    )
    _safety_stamps_ok(result)
    assert result["reactor_snapshot_source"] == "unavailable"
    assert result["reactor_state_at_decision"] == ""
    assert result["decision_grade_energy_at_decision"] is None


def test_calibration_gate_observes_auto_attached_snapshot(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: write a manual trade with auto-attach, then read the gate.

    The gate's reactor-snapshot count must reflect the auto-attached row;
    that is the entire point of this fix.
    """
    _install_fake_get_signal_detail(monkeypatch, _fake_signal("WARM_WATCH"))
    signal_inbox_api.log_manual_trade(
        event_id="EV_GATE",
        ticker="BTC",
        side="BUY",
        quantity=0.1,
        price=50000.0,
        thesis="gate exercise",
    )
    from scripts.calibration_gate import build_report

    report = build_report(tmp_db)
    assert report["db_available"] is True
    # The row is REAL_MANUAL by default; the gate counts it under "real".
    real_rows = report["real"]["rows"]
    assert real_rows["with_reactor_snapshot"] >= 1


def test_log_manual_trade_helper_failure_is_silent(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the helper blows up, log_manual_trade still succeeds and marks
    the row's snapshot as ``unavailable``.  We must never crash the write
    path because a diagnostic helper had a bad day."""
    def _explode(event_id: str) -> dict[str, Any]:
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(
        "scripts.signal_inbox_api.get_signal_detail", _explode, raising=True
    )
    result = signal_inbox_api.log_manual_trade(
        event_id="EV_HELPER_DOWN",
        ticker="BTC",
        side="BUY",
        quantity=0.1,
        price=50000.0,
        thesis="helper down",
    )
    _safety_stamps_ok(result)
    assert result["status"] == "logged"
    assert result["reactor_snapshot_source"] == "unavailable"


# ---------------------------------------------------------------------------
# Paper-ledger import auto-attach
# ---------------------------------------------------------------------------


def _write_paper_csv(path: Path, *, with_reactor_fields: bool) -> None:
    cols = list(paper_trade_ledger.TEMPLATE_COLUMNS)
    row = {c: "" for c in cols}
    row["paper_trade_id"] = "PAPER_AUTO_1"
    row["symbol"] = "BTC"
    row["side"] = "BUY"
    row["thesis"] = "auto-attach paper test"
    row["source_signal_id"] = "SIG_PAPER_X"
    if with_reactor_fields:
        row["reactor_state_at_decision"] = "COLD_OBSERVE"
        row["decision_grade_energy_at_decision"] = "0.9"
    import csv as _csv

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerow(row)


def test_paper_import_auto_attaches_via_source_signal_id(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_get_signal_detail(monkeypatch, _fake_signal("WARM_WATCH"))
    csv_path = tmp_path / "paper_auto.csv"
    _write_paper_csv(csv_path, with_reactor_fields=False)

    report = paper_trade_ledger.import_paper_trades(csv_path, write=True)
    assert report["rows_imported"] == 1
    items = report["items"]
    assert items and items[0]["imported"] is True
    # The row warning surfaces the attach outcome so the operator can audit.
    assert "reactor_snapshot_attached_from_signal" in items[0]["warnings"]
    # And the row lands in the DB with the snapshot populated.
    rows = persistence.get_all_manual_trades(tmp_db)
    paper_rows = [r for r in rows if str(r.get("trade_mode") or "").upper() == "PAPER"]
    assert paper_rows
    assert paper_rows[0]["reactor_state_at_decision"] == "WARM_WATCH"


def test_paper_import_preserves_explicit_reactor_fields(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Inbox would return WARM_WATCH; the CSV explicitly says COLD_OBSERVE,
    # which must win because the operator made a deliberate choice.
    _install_fake_get_signal_detail(monkeypatch, _fake_signal("WARM_WATCH"))
    csv_path = tmp_path / "paper_explicit.csv"
    _write_paper_csv(csv_path, with_reactor_fields=True)

    report = paper_trade_ledger.import_paper_trades(csv_path, write=True)
    assert report["rows_imported"] == 1
    rows = persistence.get_all_manual_trades(tmp_db)
    paper_rows = [r for r in rows if str(r.get("trade_mode") or "").upper() == "PAPER"]
    assert paper_rows
    assert paper_rows[0]["reactor_state_at_decision"] == "COLD_OBSERVE"
    assert paper_rows[0]["decision_grade_energy_at_decision"] == pytest.approx(0.9)


def test_paper_import_unavailable_warning_when_no_source_signal(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_get_signal_detail(monkeypatch, None)
    csv_path = tmp_path / "paper_unavailable.csv"
    cols = list(paper_trade_ledger.TEMPLATE_COLUMNS)
    row = {c: "" for c in cols}
    row["paper_trade_id"] = "PAPER_NO_SOURCE_1"
    row["symbol"] = "BTC"
    row["side"] = "BUY"
    row["thesis"] = "no source signal id"
    # source_signal_id intentionally left blank.
    import csv as _csv

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerow(row)

    report = paper_trade_ledger.import_paper_trades(csv_path, write=True)
    assert report["rows_imported"] == 1
    warnings = report["items"][0]["warnings"]
    assert "reactor_snapshot_unavailable_no_source_signal_id" in warnings


# ---------------------------------------------------------------------------
# Safety: no broker / execution language sneaks in
# ---------------------------------------------------------------------------


def test_auto_attach_module_has_no_broker_execution_language() -> None:
    text = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "reactor_snapshot_attach.py"
    ).read_text(encoding="utf-8")
    lowered = text.lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "trade now",
        "ai-approved",
        "permission to trade",
        "auto-trading",
        "real capital deployment",
    ):
        assert forbidden not in lowered, f"forbidden phrase {forbidden!r} present"
