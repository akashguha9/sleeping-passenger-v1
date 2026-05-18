"""
Tests for Signal Inbox and Reflection Desk API contract.

Coverage
--------
1. All 8 operations return advisory_status=ADVISORY_ONLY.
2. ai_execution_count == 0 on every response.
3. execution_mode == "HUMAN_ONLY" on every trade-related response.
4. broker_api_called == False on manual trade responses.
5. broker_order_id == "NONE" on manual trade responses.
6. Validation of inputs (bad event_id, bad side, bad status, etc.).
7. mark_signal rejects invalid statuses.
8. AST proof: no forbidden execution method defined in signal_inbox_api.py.
9. No broker-connect or order-placement callable defined anywhere in the module.
"""
from __future__ import annotations

import ast
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
    "broker_login",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_api():
    import scripts.signal_inbox_api as api
    return api


# ---------------------------------------------------------------------------
# Advisory field constants
# ---------------------------------------------------------------------------


def test_advisory_constants():
    api = _import_api()
    assert api._ADVISORY_STATUS == "ADVISORY_ONLY"
    assert api._EXECUTION_MODE == "HUMAN_ONLY"
    assert api._AI_EXECUTION_COUNT == 0
    assert api._EXECUTION_GATE == "LOCKED"


# ---------------------------------------------------------------------------
# 1. list_inbox_items
# ---------------------------------------------------------------------------


def test_list_inbox_items_advisory_fields():
    api = _import_api()
    result = api.list_inbox_items()
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["human_review_required"] is True
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert "items" in result
    assert "item_count" in result
    assert isinstance(result["items"], list)


def test_list_inbox_items_each_item_advisory(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "INBOX_STATES_LOG", tmp_path / "inbox_states.jsonl")
    monkeypatch.setattr(api, "REFLECTIONS_LOG", tmp_path / "reflections.jsonl")
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    result = api.list_inbox_items()
    for item in result["items"]:
        assert item["advisory_status"] == "ADVISORY_ONLY"
        assert item["human_review_required"] is True
        assert item["execution_mode"] == "HUMAN_ONLY"
        assert item["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 2. get_signal_detail
# ---------------------------------------------------------------------------


def test_get_signal_detail_empty_event_id():
    api = _import_api()
    result = api.get_signal_detail("")
    assert "error" in result
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0


def test_get_signal_detail_advisory_fields(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "INBOX_STATES_LOG", tmp_path / "inbox_states.jsonl")
    monkeypatch.setattr(api, "REFLECTIONS_LOG", tmp_path / "reflections.jsonl")
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "manual_trade.jsonl")
    result = api.get_signal_detail("EVT_LOG_SPY")
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["human_review_required"] is True
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["operation"] == "get_signal_detail"
    assert isinstance(result["reflections"], list)
    assert isinstance(result["ai_summaries"], list)
    assert isinstance(result["manual_trades"], list)


# ---------------------------------------------------------------------------
# 3. run_validation
# ---------------------------------------------------------------------------


def test_run_validation_empty_event_id():
    api = _import_api()
    result = api.run_validation("")
    assert "error" in result
    assert result["ai_execution_count"] == 0


def test_run_validation_advisory_fields():
    api = _import_api()
    result = api.run_validation("EVT_LOG_SPY")
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["human_review_required"] is True
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["operation"] == "run_validation"
    validation = result["validation"]
    assert "validation_checks" in validation
    assert "validation_passed" in validation
    assert "validation_notes" in validation
    assert validation["execution_gate"] == "LOCKED"


def test_run_validation_checks_are_booleans():
    api = _import_api()
    result = api.run_validation("EVT_LOG_SPY")
    for key, val in result["validation"]["validation_checks"].items():
        assert isinstance(val, bool), f"check {key!r} should be bool, got {type(val)}"


def test_run_validation_notes_not_empty():
    api = _import_api()
    result = api.run_validation("EVT_LOG_NONEXISTENT")
    assert len(result["validation"]["validation_notes"]) > 0


# ---------------------------------------------------------------------------
# 4. add_user_reflection
# ---------------------------------------------------------------------------


def test_add_user_reflection_writes_log(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "REFLECTIONS_LOG", tmp_path / "reflections.jsonl")
    result = api.add_user_reflection("EVT_LOG_SPY", "Looks good to me")
    assert result["status"] == "logged"
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0
    assert (tmp_path / "reflections.jsonl").exists()
    rows = [json.loads(l) for l in (tmp_path / "reflections.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["event_id"] == "EVT_LOG_SPY"
    assert rows[0]["reflection_text"] == "Looks good to me"
    assert rows[0]["advisory_status"] == "ADVISORY_ONLY"
    assert rows[0]["ai_execution_count"] == 0


def test_add_user_reflection_empty_event_id():
    api = _import_api()
    result = api.add_user_reflection("", "some text")
    assert "error" in result


def test_add_user_reflection_empty_text():
    api = _import_api()
    result = api.add_user_reflection("EVT_LOG_SPY", "")
    assert "error" in result


# ---------------------------------------------------------------------------
# 5. add_ai_discussion_summary
# ---------------------------------------------------------------------------


def test_add_ai_summary_writes_log(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    result = api.add_ai_discussion_summary("EVT_LOG_QQQ", "Price persistence is elevated.")
    assert result["status"] == "logged"
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0
    rows = [json.loads(l) for l in (tmp_path / "ai_summaries.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["ai_execution_count"] == 0
    assert rows[0]["advisory_status"] == "ADVISORY_ONLY"
    assert "advisory_note" in rows[0]


def test_add_ai_summary_empty_inputs():
    api = _import_api()
    assert "error" in api.add_ai_discussion_summary("", "text")
    assert "error" in api.add_ai_discussion_summary("EVT_LOG_SPY", "")


# ---------------------------------------------------------------------------
# 6. mark_signal
# ---------------------------------------------------------------------------


def test_mark_signal_valid_statuses(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "INBOX_STATES_LOG", tmp_path / "inbox_states.jsonl")
    for status in ("pending", "watchlist", "human_review", "rejected"):
        result = api.mark_signal("EVT_LOG_SPY", status)
        assert result["user_status"] == status
        assert result["advisory_status"] == "ADVISORY_ONLY"
        assert result["ai_execution_count"] == 0


def test_mark_signal_invalid_status():
    api = _import_api()
    result = api.mark_signal("EVT_LOG_SPY", "BUY_NOW")
    assert "error" in result
    assert result["ai_execution_count"] == 0


def test_mark_signal_empty_event_id():
    api = _import_api()
    result = api.mark_signal("", "watchlist")
    assert "error" in result


# ---------------------------------------------------------------------------
# 7. log_manual_trade
# ---------------------------------------------------------------------------


def test_log_manual_trade_human_only(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    # Disable SQLite writes for this test — without this monkey-patch
    # log_manual_trade writes into the operator's real runtime DB and
    # pollutes the Reconciliation queue with synthetic SPY/QQQ rows.
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY",
        ticker="SPY",
        side="BUY",
        quantity=10.0,
        price=450.0,
        thesis="Strong persistence in recent window",
    )
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == "NONE"
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["status"] == "logged"
    assert result["operation"] == "log_manual_trade"


def test_log_manual_trade_persisted_correctly(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    result = api.log_manual_trade(
        event_id="EVT_LOG_QQQ",
        ticker="QQQ",
        side="SELL",
        quantity=5.0,
        price=380.0,
        thesis="Exit on kill rate spike",
    )
    trade_id = result["trade_id"]
    rows = [json.loads(l) for l in (tmp_path / "trades.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["trade_id"] == trade_id
    assert rows[0]["execution_mode"] == "HUMAN_ONLY"
    assert rows[0]["ai_execution_count"] == 0
    assert rows[0]["broker_api_called"] is False
    assert rows[0]["broker_order_id"] == "NONE"


def test_log_manual_trade_invalid_side():
    api = _import_api()
    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY", ticker="SPY", side="AUTO", quantity=1, price=1, thesis="x"
    )
    assert "error" in result


def test_log_manual_trade_invalid_quantity():
    api = _import_api()
    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY", ticker="SPY", side="BUY", quantity=-5, price=100, thesis="x"
    )
    assert "error" in result


def test_log_manual_trade_invalid_price():
    api = _import_api()
    result = api.log_manual_trade(
        event_id="EVT_LOG_SPY", ticker="SPY", side="BUY", quantity=1, price=0, thesis="x"
    )
    assert "error" in result


def test_log_manual_trade_missing_event_id():
    api = _import_api()
    result = api.log_manual_trade(
        event_id="", ticker="SPY", side="BUY", quantity=1, price=100, thesis="x"
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# 8. reconcile_trade
# ---------------------------------------------------------------------------


def test_reconcile_trade_advisory_fields(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "RECONCILIATIONS_LOG", tmp_path / "recs.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    api.log_manual_trade(
        event_id="EVT_LOG_SPY", ticker="SPY", side="BUY",
        quantity=1, price=450,
        # Avoid exact-match probe theses ("test", "probe", "seed", …)
        # — the canonical guard rejects them at the log entry point.
        thesis="reconcile-path coverage"
    )
    trade_id = json.loads((tmp_path / "trades.jsonl").read_text().splitlines()[0])["trade_id"]
    result = api.reconcile_trade(
        trade_id,
        actual_fill_price=452.0,
        actual_quantity=1.0,
        outcome_notes="Small gain",
        pnl_estimate=2.0,
        outcome_status="WIN",
    )
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["outcome_status"] == "WIN"
    assert result["status"] == "logged"


def test_reconcile_trade_invalid_status_defaults_unknown(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "trades.jsonl")
    monkeypatch.setattr(api, "RECONCILIATIONS_LOG", tmp_path / "recs.jsonl")
    monkeypatch.setattr(api, "_DB_AVAILABLE", False)
    result = api.reconcile_trade(
        "MT_fake",
        actual_fill_price=100.0,
        actual_quantity=1.0,
        outcome_status="MOON",
    )
    assert result["outcome_status"] == "UNKNOWN"
    assert result["ai_execution_count"] == 0


def test_reconcile_trade_empty_trade_id():
    api = _import_api()
    result = api.reconcile_trade(
        "", actual_fill_price=100, actual_quantity=1
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# AST proof: no broker execution endpoint in signal_inbox_api.py
# ---------------------------------------------------------------------------


def test_no_forbidden_function_defined_in_module():
    source_path = REPO_ROOT / "scripts" / "signal_inbox_api.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    defined_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations = defined_names & FORBIDDEN_FUNCTIONS
    assert not violations, (
        f"Forbidden execution functions found in signal_inbox_api.py: {violations}"
    )


def test_no_broker_keyword_in_source():
    source_path = REPO_ROOT / "scripts" / "signal_inbox_api.py"
    source = source_path.read_text(encoding="utf-8")
    forbidden_strings = [
        "place_order(",
        "submit_order(",
        "connect_broker(",
        "auto_buy(",
        "auto_sell(",
        "execute_trade(",
    ]
    for token in forbidden_strings:
        assert token not in source, (
            f"Forbidden token {token!r} found in signal_inbox_api.py"
        )


def test_ai_execution_count_never_nonzero_in_source():
    source_path = REPO_ROOT / "scripts" / "signal_inbox_api.py"
    source = source_path.read_text(encoding="utf-8")
    assert "ai_execution_count = 1" not in source
    assert "ai_execution_count += 1" not in source
    assert "ai_execution_count=1" not in source


def test_module_exports_correct_public_api():
    api = _import_api()
    expected = {
        "list_inbox_items",
        "get_signal_detail",
        "run_validation",
        "add_user_reflection",
        "add_ai_discussion_summary",
        "mark_signal",
        "log_manual_trade",
        "reconcile_trade",
    }
    for name in expected:
        assert hasattr(api, name), f"Missing public function: {name}"
