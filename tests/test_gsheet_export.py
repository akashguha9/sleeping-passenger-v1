"""
Tests for Google Sheet-compatible CSV/JSON export layer.

Coverage
--------
1. Each export function returns a valid CSV string.
2. Every CSV has the expected stable headers.
3. Every data row in every export carries advisory_status=ADVISORY_ONLY.
4. Every data row carries ai_execution_count=0.
5. Every row with an execution_mode column carries HUMAN_ONLY.
6. export_all_logs creates all 6 files in the output directory.
7. Exports are non-destructive: they only read from JSONL logs.
8. AST proof: no forbidden execution callable in gsheet_export.py.
9. No Google API import or credential usage anywhere in gsheet_export.py.
"""
from __future__ import annotations

import ast
import csv
import io
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_FUNCTIONS = {
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
}

EXPECTED_CSV_FILES = {
    "signal_inbox_log.csv",
    "reflection_log.csv",
    "manual_trade_log.csv",
    "reconciliation_log.csv",
    "moltbook_mistake_log.csv",
    "source_health_log.csv",
}


def _parse_csv(content: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    rows = list(reader)
    return list(headers), rows


def _import_gsheet():
    import scripts.gsheet_export as gs
    return gs


def _import_inbox():
    import scripts.signal_inbox_api as api
    return api


def _import_moltbook():
    import scripts.moltbook_api as api
    return api


# ---------------------------------------------------------------------------
# Header stability
# ---------------------------------------------------------------------------


def test_signal_inbox_headers_stable():
    gs = _import_gsheet()
    assert "event_id" in gs.SIGNAL_INBOX_HEADERS
    assert "advisory_status" in gs.SIGNAL_INBOX_HEADERS
    assert "ai_execution_count" in gs.SIGNAL_INBOX_HEADERS
    assert "execution_mode" in gs.SIGNAL_INBOX_HEADERS
    assert "human_review_required" in gs.SIGNAL_INBOX_HEADERS


def test_reflection_headers_stable():
    gs = _import_gsheet()
    assert "reflection_id" in gs.REFLECTION_HEADERS
    assert "advisory_status" in gs.REFLECTION_HEADERS
    assert "ai_execution_count" in gs.REFLECTION_HEADERS


def test_manual_trade_headers_stable():
    gs = _import_gsheet()
    required = {
        "trade_id", "event_id", "ticker", "side", "quantity", "price",
        "execution_mode", "ai_execution_count", "broker_api_called",
        "broker_order_id", "advisory_status", "human_review_required",
    }
    for col in required:
        assert col in gs.MANUAL_TRADE_HEADERS, f"Missing column: {col}"


def test_reconciliation_headers_stable():
    gs = _import_gsheet()
    required = {
        "reconciliation_id", "trade_id", "outcome_status", "pnl_estimate",
        "execution_mode", "ai_execution_count", "advisory_status",
    }
    for col in required:
        assert col in gs.RECONCILIATION_HEADERS, f"Missing column: {col}"


def test_moltbook_headers_stable():
    gs = _import_gsheet()
    required = {
        "entry_id", "mistake_type", "lesson_learned", "bias_detected",
        "recalibration_note", "future_rule_update", "original_signal_thesis",
        "ai_interpretation", "user_reflection", "final_human_decision",
        "manual_trade_log_id", "outcome", "advisory_status", "ai_execution_count",
    }
    for col in required:
        assert col in gs.MOLTBOOK_HEADERS, f"Missing column: {col}"


def test_source_health_headers_stable():
    gs = _import_gsheet()
    required = {
        "export_timestamp", "snapshot_count", "fabric_bull_state",
        "advisory_status", "execution_mode", "ai_execution_count",
    }
    for col in required:
        assert col in gs.SOURCE_HEALTH_HEADERS, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# CSV format validity
# ---------------------------------------------------------------------------


def test_export_signal_inbox_log_returns_csv():
    gs = _import_gsheet()
    content = gs.export_signal_inbox_log()
    assert isinstance(content, str)
    headers, _ = _parse_csv(content)
    assert headers == gs.SIGNAL_INBOX_HEADERS


def test_export_reflection_log_returns_csv(tmp_path, monkeypatch):
    inbox = _import_inbox()
    gs = _import_gsheet()
    monkeypatch.setattr(inbox, "REFLECTIONS_LOG", tmp_path / "reflections.jsonl")
    monkeypatch.setattr(gs, "REFLECTIONS_LOG", tmp_path / "reflections.jsonl")
    inbox.add_user_reflection("FABRIC_SPY", "Test reflection")
    content = gs.export_reflection_log()
    headers, rows = _parse_csv(content)
    assert headers == gs.REFLECTION_HEADERS
    assert len(rows) == 1
    assert rows[0]["event_id"] == "FABRIC_SPY"
    assert rows[0]["advisory_status"] == "ADVISORY_ONLY"
    assert rows[0]["ai_execution_count"] == "0"


def test_export_manual_trade_log_returns_csv(tmp_path, monkeypatch):
    inbox = _import_inbox()
    gs = _import_gsheet()
    monkeypatch.setattr(inbox, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(gs, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    inbox.log_manual_trade(
        event_id="FABRIC_SPY", ticker="SPY", side="BUY",
        quantity=5, price=450, thesis="test thesis"
    )
    content = gs.export_manual_trade_log()
    headers, rows = _parse_csv(content)
    assert headers == gs.MANUAL_TRADE_HEADERS
    assert len(rows) == 1
    assert rows[0]["execution_mode"] == "HUMAN_ONLY"
    assert rows[0]["ai_execution_count"] == "0"
    assert rows[0]["broker_api_called"] == "False"
    assert rows[0]["advisory_status"] == "ADVISORY_ONLY"


def test_export_reconciliation_log_returns_csv(tmp_path, monkeypatch):
    inbox = _import_inbox()
    gs = _import_gsheet()
    monkeypatch.setattr(inbox, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(inbox, "RECONCILIATIONS_LOG", tmp_path / "recs.jsonl")
    monkeypatch.setattr(gs, "RECONCILIATIONS_LOG", tmp_path / "recs.jsonl")
    inbox.log_manual_trade(
        event_id="FABRIC_SPY", ticker="SPY", side="BUY", quantity=1, price=450, thesis="t"
    )
    trade_id = json.loads((tmp_path / "trades.jsonl").read_text().splitlines()[0])["trade_id"]
    inbox.reconcile_trade(
        trade_id, actual_fill_price=452, actual_quantity=1, outcome_status="WIN"
    )
    content = gs.export_reconciliation_log()
    headers, rows = _parse_csv(content)
    assert headers == gs.RECONCILIATION_HEADERS
    assert len(rows) == 1
    assert rows[0]["outcome_status"] == "WIN"
    assert rows[0]["execution_mode"] == "HUMAN_ONLY"
    assert rows[0]["ai_execution_count"] == "0"


def test_export_moltbook_mistake_log_returns_csv(tmp_path, monkeypatch):
    mb = _import_moltbook()
    gs = _import_gsheet()
    monkeypatch.setattr(mb, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    monkeypatch.setattr(gs, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    mb.log_moltbook_entry(
        event_id="FABRIC_SPY",
        ticker="SPY",
        original_signal_thesis="Thesis A",
        ai_interpretation="Advisory context",
        user_reflection="I paused",
        final_human_decision="No trade",
        mistake_type="no_trade_correct",
        lesson_learned="Correct choice under uncertainty",
    )
    content = gs.export_moltbook_mistake_log()
    headers, rows = _parse_csv(content)
    assert headers == gs.MOLTBOOK_HEADERS
    assert len(rows) == 1
    assert rows[0]["mistake_type"] == "no_trade_correct"
    assert rows[0]["advisory_status"] == "ADVISORY_ONLY"
    assert rows[0]["ai_execution_count"] == "0"


def test_export_source_health_log_returns_csv():
    gs = _import_gsheet()
    content = gs.export_source_health_log()
    headers, rows = _parse_csv(content)
    assert headers == gs.SOURCE_HEALTH_HEADERS
    assert len(rows) == 1
    assert rows[0]["advisory_status"] == "ADVISORY_ONLY"
    assert rows[0]["execution_mode"] == "HUMAN_ONLY"
    assert rows[0]["ai_execution_count"] == "0"


# ---------------------------------------------------------------------------
# Advisory enforcement on every row
# ---------------------------------------------------------------------------


def test_advisory_fields_enforced_on_empty_reflection_log(tmp_path, monkeypatch):
    gs = _import_gsheet()
    monkeypatch.setattr(gs, "REFLECTIONS_LOG", tmp_path / "empty.jsonl")
    content = gs.export_reflection_log()
    headers, rows = _parse_csv(content)
    assert headers == gs.REFLECTION_HEADERS
    assert rows == []


def test_advisory_enforced_on_manual_trade_with_no_trades(tmp_path, monkeypatch):
    gs = _import_gsheet()
    monkeypatch.setattr(gs, "MANUAL_TRADE_LOG", tmp_path / "empty.jsonl")
    content = gs.export_manual_trade_log()
    headers, _ = _parse_csv(content)
    assert "execution_mode" in headers
    assert "ai_execution_count" in headers


# ---------------------------------------------------------------------------
# export_all_logs creates 6 files
# ---------------------------------------------------------------------------


def test_export_all_logs_creates_all_files(tmp_path):
    gs = _import_gsheet()
    result = gs.export_all_logs(tmp_path)
    assert set(result.keys()) == EXPECTED_CSV_FILES
    for fname in EXPECTED_CSV_FILES:
        path = tmp_path / fname
        assert path.exists(), f"Missing export file: {fname}"
        assert path.stat().st_size > 0, f"Empty export file: {fname}"


def test_export_all_logs_files_have_correct_headers(tmp_path):
    gs = _import_gsheet()
    gs.export_all_logs(tmp_path)
    header_map = {
        "signal_inbox_log.csv": gs.SIGNAL_INBOX_HEADERS,
        "reflection_log.csv": gs.REFLECTION_HEADERS,
        "manual_trade_log.csv": gs.MANUAL_TRADE_HEADERS,
        "reconciliation_log.csv": gs.RECONCILIATION_HEADERS,
        "moltbook_mistake_log.csv": gs.MOLTBOOK_HEADERS,
        "source_health_log.csv": gs.SOURCE_HEALTH_HEADERS,
    }
    for fname, expected_headers in header_map.items():
        content = (tmp_path / fname).read_text(encoding="utf-8")
        actual_headers, _ = _parse_csv(content)
        assert actual_headers == expected_headers, (
            f"{fname}: expected {expected_headers}, got {actual_headers}"
        )


def test_export_all_logs_writes_to_path(tmp_path):
    gs = _import_gsheet()
    written = gs.export_all_logs(tmp_path)
    for fname, path_str in written.items():
        assert Path(path_str).exists(), f"Path not written: {path_str}"


# ---------------------------------------------------------------------------
# AST: no forbidden execution callable, no Google API import
# ---------------------------------------------------------------------------


def test_no_forbidden_function_in_gsheet_export():
    source_path = REPO_ROOT / "scripts" / "gsheet_export.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations = defined & FORBIDDEN_FUNCTIONS
    assert not violations, f"Forbidden functions in gsheet_export.py: {violations}"


def test_no_google_api_import_in_gsheet_export():
    source_path = REPO_ROOT / "scripts" / "gsheet_export.py"
    source = source_path.read_text(encoding="utf-8")
    forbidden_imports = [
        "google.oauth2",
        "googleapiclient",
        "gspread",
        "google.auth",
        "oauth2client",
    ]
    for token in forbidden_imports:
        assert token not in source, (
            f"Google API import {token!r} found in gsheet_export.py"
        )


def test_no_ai_execution_count_nonzero_in_gsheet_export():
    source_path = REPO_ROOT / "scripts" / "gsheet_export.py"
    source = source_path.read_text(encoding="utf-8")
    assert "ai_execution_count = 1" not in source
    assert "ai_execution_count += 1" not in source
