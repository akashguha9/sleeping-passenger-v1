"""Sprint 7B.2 — paper-trade ledger Excel/CSV workflow tests.

Exercise the core module plus the round-trip via SQLite.  Verify:

  * the template's column ORDER is stable (Excel friendliness)
  * dry-run validates rows without mutating the DB
  * --write imports valid paper rows with trade_mode='PAPER'
  * rows that smell like broker / real-money artifacts are REJECTED
  * reactor-at-decision fields round-trip through the ledger into the
    calibration report
  * paper rows carry paper_trade_only / real_capital_at_risk=False
  * dedupe-in-file rejects the second occurrence of a paper_trade_id
  * export round-trips current paper rows back to CSV
  * advisory / execution safety stamps are preserved everywhere
"""
from __future__ import annotations

import csv
import importlib
from pathlib import Path

import pytest

from scripts import paper_trade_ledger
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
    db = tmp_path / "paper_ledger.db"
    persistence.init_schema(db)
    helper_names = [
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_trades_for_event",
        "get_event_id_for_trade",
        "get_all_manual_trades",
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


def _safety_stamps_ok(resp: dict) -> None:
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["broker_api_called"] is False
    assert resp["broker_order_id"] == "NONE"
    assert resp["execution_permission"] is False
    assert resp["can_execute"] is False
    assert resp["ai_execution_count"] == 0
    assert resp["paper_trade_only"] is True
    assert resp["real_capital_at_risk"] is False


def test_template_columns_stable_and_ordered() -> None:
    expected_head = (
        "paper_trade_id",
        "created_at",
        "symbol",
        "side",
        "thesis",
    )
    assert paper_trade_ledger.TEMPLATE_COLUMNS[: len(expected_head)] == expected_head
    # Reactor snapshot block must be in canonical order.
    cols = paper_trade_ledger.TEMPLATE_COLUMNS
    reactor_idx = cols.index("reactor_state_at_decision")
    assert cols[reactor_idx + 1] == "decision_grade_energy_at_decision"
    assert cols[reactor_idx + 7] == "gallardo_block_at_decision"
    # Outcome / reconciliation fields must appear AFTER reactor snapshot.
    assert cols.index("outcome_status") > cols.index("preflight_state_at_decision")
    # No broker / execution columns in the template.
    for forbidden in ("broker_order_id", "execution_permission", "can_execute"):
        assert forbidden not in cols


def test_write_template_creates_file_with_headers(tmp_path: Path) -> None:
    out = tmp_path / "template.csv"
    payload = paper_trade_ledger.write_template(out)
    _safety_stamps_ok(payload)
    assert payload["example_rows_written"] == 0
    with out.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        headers = next(reader)
        assert headers == list(paper_trade_ledger.TEMPLATE_COLUMNS)
        with pytest.raises(StopIteration):
            next(reader)


def test_write_template_include_example(tmp_path: Path) -> None:
    out = tmp_path / "template_example.csv"
    payload = paper_trade_ledger.write_template(out, include_example=True)
    _safety_stamps_ok(payload)
    assert payload["example_rows_written"] == 1
    with out.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "EXAMPLE_TICKER"
    # Example row must never carry broker / execution language.
    blob = " ".join(rows[0].values()).lower()
    for bad in ("broker", "place order", "execute trade", "real money"):
        assert bad not in blob


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(paper_trade_ledger.TEMPLATE_COLUMNS))
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in paper_trade_ledger.TEMPLATE_COLUMNS})


def test_import_dry_run_validates_but_does_not_persist(tmp_db: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "valid.csv"
    _write_csv(csv_path, [
        {
            "paper_trade_id": "PAPER_001",
            "symbol": "AAPL",
            "side": "BUY",
            "thesis": "rehearsal idea",
            "reactor_state_at_decision": "WARM_WATCH",
            "decision_grade_energy_at_decision": "0.5",
            "gallardo_block_at_decision": "false",
        },
    ])
    payload = paper_trade_ledger.import_paper_trades(csv_path, write=False)
    _safety_stamps_ok(payload)
    assert payload["rows_seen"] == 1
    assert payload["rows_valid"] == 1
    assert payload["rows_imported"] == 0
    assert payload["rows_rejected"] == 0
    # DB stays empty.
    assert len(persistence.get_all_manual_trades(tmp_db)) == 0


def test_import_write_persists_paper_row_with_trade_mode(tmp_db: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "to_write.csv"
    _write_csv(csv_path, [
        {
            "paper_trade_id": "PAPER_002",
            "symbol": "TSLA",
            "side": "SELL",
            "thesis": "fade pop",
            "invalidation_level": "300",
            "time_horizon": "1d",
            "risk_notes": "<=1R",
            "reactor_state_at_decision": "HOT_CONTAINMENT_REQUIRED",
            "decision_grade_energy_at_decision": "0.81",
            "echo_risk_score_at_decision": "0.42",
            "meltdown_risk_at_decision": "0.55",
            "fission_branch_clarity_at_decision": "0.7",
            "operator_heat_at_decision": "0.6",
            "gallardo_block_at_decision": "false",
            "fusion_validity_at_decision": "weak_fusion",
            "preflight_state_at_decision": "OK",
            "lesson": "watch volatility",
            "planned_entry": "310.0",
        },
    ])
    payload = paper_trade_ledger.import_paper_trades(csv_path, write=True)
    _safety_stamps_ok(payload)
    assert payload["rows_imported"] == 1
    assert payload["rows_rejected"] == 0
    rows = persistence.get_all_manual_trades(tmp_db)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "TSLA"
    assert row["side"] == "SELL"
    assert row.get("trade_mode") == "PAPER"
    assert row["reactor_state_at_decision"] == "HOT_CONTAINMENT_REQUIRED"
    assert row["decision_grade_energy_at_decision"] == pytest.approx(0.81)
    # Safety: broker / execution stamps untouched.
    assert row["broker_order_id"] == "NONE"
    assert int(row["broker_api_called"]) == 0
    assert int(row["ai_execution_count"]) == 0


def test_import_rejects_broker_like_columns(tmp_db: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "hostile.csv"
    fieldnames = list(paper_trade_ledger.TEMPLATE_COLUMNS) + ["broker_order_id"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "paper_trade_id": "PAPER_BROKER",
            "symbol": "MSFT",
            "side": "BUY",
            "thesis": "should be rejected",
            "broker_order_id": "BR12345",  # forbidden column with data
        })
    payload = paper_trade_ledger.import_paper_trades(csv_path, write=True)
    _safety_stamps_ok(payload)
    assert payload["rows_rejected"] == 1
    assert payload["rows_imported"] == 0
    reasons = payload["items"][0]["rejection_reasons"]
    assert any("forbidden_column" in r for r in reasons)
    # Nothing persisted.
    assert len(persistence.get_all_manual_trades(tmp_db)) == 0


def test_import_rejects_forbidden_cell_values(tmp_db: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "phrases.csv"
    _write_csv(csv_path, [
        {
            "paper_trade_id": "PAPER_BAD_PHRASE",
            "symbol": "NVDA",
            "side": "BUY",
            "thesis": "go ahead and place order at market",
        },
    ])
    payload = paper_trade_ledger.import_paper_trades(csv_path, write=True)
    assert payload["rows_rejected"] == 1
    assert payload["rows_imported"] == 0
    reasons = payload["items"][0]["rejection_reasons"]
    assert any("forbidden_value" in r for r in reasons)


def test_import_rejects_missing_required_fields(tmp_db: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "missing.csv"
    _write_csv(csv_path, [
        # paper_trade_id missing
        {"symbol": "AMZN", "side": "BUY", "thesis": "x"},
        # symbol missing
        {"paper_trade_id": "PAPER_X", "side": "BUY", "thesis": "x"},
        # side missing -> normalised to BUY (allowed); thesis empty -> rejected
        {"paper_trade_id": "PAPER_Y", "symbol": "GOOG"},
    ])
    payload = paper_trade_ledger.import_paper_trades(csv_path, write=False)
    assert payload["rows_rejected"] == 3


def test_import_dedupes_paper_trade_id_within_file(tmp_db: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "dup.csv"
    _write_csv(csv_path, [
        {"paper_trade_id": "PAPER_SAME", "symbol": "A", "side": "BUY", "thesis": "1st"},
        {"paper_trade_id": "PAPER_SAME", "symbol": "A", "side": "BUY", "thesis": "2nd"},
    ])
    payload = paper_trade_ledger.import_paper_trades(csv_path, write=False)
    assert payload["rows_seen"] == 2
    assert payload["rows_duplicate"] == 1
    assert payload["rows_rejected"] == 1
    assert payload["rows_valid"] == 1


def test_paper_row_visible_to_calibration_report(tmp_db: Path, tmp_path: Path) -> None:
    csv_path = tmp_path / "paper_for_cal.csv"
    _write_csv(csv_path, [
        {
            "paper_trade_id": "PAPER_CAL",
            "symbol": "META",
            "side": "BUY",
            "thesis": "paper calibration",
            "reactor_state_at_decision": "WARM_WATCH",
            "decision_grade_energy_at_decision": "0.4",
            "echo_risk_score_at_decision": "0.2",
            "meltdown_risk_at_decision": "0.2",
            "fission_branch_clarity_at_decision": "0.5",
            "operator_heat_at_decision": "0.1",
            "gallardo_block_at_decision": "false",
            "fusion_validity_at_decision": "weak_fusion",
            "preflight_state_at_decision": "OK",
            "planned_entry": "100.0",
        },
    ])
    payload = paper_trade_ledger.import_paper_trades(csv_path, write=True)
    assert payload["rows_imported"] == 1

    from scripts.reactor_calibration_report import build_report
    rep = build_report(tmp_db)
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    calibration = rep.get("calibration") or {}
    assert int(calibration.get("reactor_snapshot_count", 0)) >= 1


def test_export_round_trips_paper_rows(tmp_db: Path, tmp_path: Path) -> None:
    # Persist one paper row via the import path...
    csv_in = tmp_path / "in.csv"
    _write_csv(csv_in, [
        {"paper_trade_id": "PAPER_RT", "symbol": "RT", "side": "BUY", "thesis": "rt"},
    ])
    paper_trade_ledger.import_paper_trades(csv_in, write=True)

    # ...and another non-paper row to prove the filter holds.
    signal_inbox_api.log_manual_trade(
        event_id="REAL_EV",
        ticker="REAL",
        side="BUY",
        quantity=1.0,
        price=100.0,
        thesis="real manual record",
        trade_mode="REAL_MANUAL",
    )

    csv_out = tmp_path / "out.csv"
    payload = paper_trade_ledger.export_paper_trades(csv_out)
    _safety_stamps_ok(payload)
    assert payload["rows_exported"] == 1
    with csv_out.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "RT"


def test_log_manual_trade_paper_mode_response_stamps(
    tmp_path, monkeypatch
) -> None:
    """log_manual_trade(trade_mode='PAPER') response carries paper stamps."""
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", tmp_path / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "_DB_AVAILABLE", False)
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_PAPER_RESPONSE",
        ticker="ZZZ",
        side="BUY",
        quantity=1.0,
        price=1.0,
        thesis="response stamp test",
        trade_mode="PAPER",
    )
    assert resp["trade_mode"] == "PAPER"
    assert resp["paper_trade_only"] is True
    assert resp["real_capital_at_risk"] is False
    assert resp["broker_api_called"] is False
    assert resp["execution_gate"] == "LOCKED"


def test_log_manual_trade_hostile_trade_mode_falls_through_to_real_manual(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", tmp_path / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "_DB_AVAILABLE", False)
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_HOSTILE_MODE",
        ticker="ZZZ",
        side="BUY",
        quantity=1.0,
        price=1.0,
        thesis="hostile mode test",
        trade_mode="PLACE_ORDER",  # not in the allowlist
    )
    assert resp["trade_mode"] == "REAL_MANUAL"
    assert resp["paper_trade_only"] is False
