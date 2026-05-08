"""
Tests for Moltbook self-correction and mistake-learning layer.

Coverage
--------
1. All 12 mistake categories are defined and accepted.
2. log_moltbook_entry persists correct data.
3. Invalid mistake_type is rejected with an error response.
4. Missing required fields are rejected.
5. list_moltbook_entries filtering by ticker and mistake_type.
6. get_moltbook_entry returns the correct entry.
7. get_moltbook_entry with unknown entry_id returns error.
8. get_mistake_category_summary counts correctly.
9. All operations carry advisory_status=ADVISORY_ONLY and ai_execution_count=0.
10. AST proof: no forbidden execution callable in moltbook_api.py.
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
}

ALL_MISTAKE_CATEGORIES = {
    "good_signal_bad_timing",
    "bad_signal_lucky_profit",
    "good_signal_good_execution",
    "bad_signal_correct_rejection",
    "missed_signal",
    "overtraded_signal",
    "chaos_ignored",
    "false_confirmation",
    "late_entry",
    "early_exit",
    "no_trade_correct",
    "no_trade_missed_opportunity",
}


def _import_api():
    import scripts.moltbook_api as api
    return api


def _sample_entry_kwargs(mistake_type: str = "missed_signal") -> dict:
    return dict(
        event_id="FABRIC_SPY",
        ticker="SPY",
        original_signal_thesis="Persistence above 0.8 in 3 consecutive runs",
        ai_interpretation="Suggests elevated visibility; not a trade signal",
        user_reflection="Should have watched this more carefully",
        final_human_decision="No trade — watchlist only",
        outcome="Moved 2% higher without our participation",
        mistake_type=mistake_type,
        lesson_learned="Monitor high-persistence tickers with low kill rate more closely",
        bias_detected="anchoring",
        recalibration_note="Lower conviction threshold for watchlist promotion",
        future_rule_update="Add rule: if persistence>0.8 AND kill_rate<0.1, elevate to human_review",
    )


# ---------------------------------------------------------------------------
# 1. Mistake categories constant
# ---------------------------------------------------------------------------


def test_all_mistake_categories_defined():
    api = _import_api()
    assert api.MISTAKE_CATEGORIES == ALL_MISTAKE_CATEGORIES


def test_mistake_categories_count():
    api = _import_api()
    assert len(api.MISTAKE_CATEGORIES) == 12


# ---------------------------------------------------------------------------
# 2. log_moltbook_entry — each category accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(ALL_MISTAKE_CATEGORIES))
def test_log_entry_all_categories(tmp_path, monkeypatch, category):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    result = api.log_moltbook_entry(**_sample_entry_kwargs(category))
    assert result["status"] == "logged"
    assert result["mistake_type"] == category
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0


def test_log_entry_persists_all_11_fields(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    kwargs = _sample_entry_kwargs()
    result = api.log_moltbook_entry(**kwargs)
    entry_id = result["entry_id"]

    rows = [json.loads(l) for l in (tmp_path / "moltbook.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["original_signal_thesis"] == kwargs["original_signal_thesis"]
    assert row["ai_interpretation"] == kwargs["ai_interpretation"]
    assert row["user_reflection"] == kwargs["user_reflection"]
    assert row["final_human_decision"] == kwargs["final_human_decision"]
    assert row["outcome"] == kwargs["outcome"]
    assert row["mistake_type"] == kwargs["mistake_type"]
    assert row["lesson_learned"] == kwargs["lesson_learned"]
    assert row["bias_detected"] == kwargs["bias_detected"]
    assert row["recalibration_note"] == kwargs["recalibration_note"]
    assert row["future_rule_update"] == kwargs["future_rule_update"]
    assert row["entry_id"] == entry_id
    assert row["advisory_status"] == "ADVISORY_ONLY"
    assert row["ai_execution_count"] == 0
    assert row["execution_mode"] == "HUMAN_ONLY"


# ---------------------------------------------------------------------------
# 3. Invalid inputs
# ---------------------------------------------------------------------------


def test_invalid_mistake_type_returns_error():
    api = _import_api()
    result = api.log_moltbook_entry(
        **{**_sample_entry_kwargs(), "mistake_type": "auto_execute"}
    )
    assert "error" in result
    assert result["ai_execution_count"] == 0


def test_missing_event_id_returns_error():
    api = _import_api()
    result = api.log_moltbook_entry(
        **{**_sample_entry_kwargs(), "event_id": ""}
    )
    assert "error" in result


def test_missing_ticker_returns_error():
    api = _import_api()
    result = api.log_moltbook_entry(
        **{**_sample_entry_kwargs(), "ticker": ""}
    )
    assert "error" in result


def test_missing_lesson_learned_returns_error():
    api = _import_api()
    result = api.log_moltbook_entry(
        **{**_sample_entry_kwargs(), "lesson_learned": ""}
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# 4. list_moltbook_entries
# ---------------------------------------------------------------------------


def test_list_entries_empty(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    result = api.list_moltbook_entries()
    assert result["entry_count"] == 0
    assert result["entries"] == []
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0


def test_list_entries_filter_by_ticker(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    api.log_moltbook_entry(**_sample_entry_kwargs())
    api.log_moltbook_entry(**{**_sample_entry_kwargs(), "ticker": "QQQ", "event_id": "FABRIC_QQQ"})
    result = api.list_moltbook_entries(ticker="SPY")
    assert result["entry_count"] == 1
    assert result["entries"][0]["ticker"] == "SPY"


def test_list_entries_filter_by_mistake_type(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    api.log_moltbook_entry(**_sample_entry_kwargs("missed_signal"))
    api.log_moltbook_entry(**_sample_entry_kwargs("late_entry"))
    result = api.list_moltbook_entries(mistake_type="late_entry")
    assert result["entry_count"] == 1
    assert result["entries"][0]["mistake_type"] == "late_entry"


# ---------------------------------------------------------------------------
# 5. get_moltbook_entry
# ---------------------------------------------------------------------------


def test_get_entry_by_id(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    logged = api.log_moltbook_entry(**_sample_entry_kwargs())
    entry_id = logged["entry_id"]
    result = api.get_moltbook_entry(entry_id)
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0
    assert result["entry"]["entry_id"] == entry_id


def test_get_entry_not_found(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    result = api.get_moltbook_entry("MB_doesnotexist")
    assert "error" in result
    assert result["ai_execution_count"] == 0


def test_get_entry_empty_id():
    api = _import_api()
    result = api.get_moltbook_entry("")
    assert "error" in result


# ---------------------------------------------------------------------------
# 6. get_mistake_category_summary
# ---------------------------------------------------------------------------


def test_summary_all_categories_present(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    result = api.get_mistake_category_summary()
    assert result["total_entries"] == 0
    assert set(result["mistake_type_counts"].keys()) == ALL_MISTAKE_CATEGORIES
    assert all(v == 0 for v in result["mistake_type_counts"].values())


def test_summary_counts_correctly(tmp_path, monkeypatch):
    api = _import_api()
    monkeypatch.setattr(api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    api.log_moltbook_entry(**_sample_entry_kwargs("missed_signal"))
    api.log_moltbook_entry(**_sample_entry_kwargs("missed_signal"))
    api.log_moltbook_entry(**_sample_entry_kwargs("late_entry"))
    result = api.get_mistake_category_summary()
    assert result["total_entries"] == 3
    assert result["mistake_type_counts"]["missed_signal"] == 2
    assert result["mistake_type_counts"]["late_entry"] == 1
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 7. AST: no forbidden execution callable
# ---------------------------------------------------------------------------


def test_no_forbidden_function_in_moltbook_api():
    source_path = REPO_ROOT / "scripts" / "moltbook_api.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations = defined & FORBIDDEN_FUNCTIONS
    assert not violations, f"Forbidden functions in moltbook_api.py: {violations}"


def test_ai_execution_count_always_zero_in_source():
    source_path = REPO_ROOT / "scripts" / "moltbook_api.py"
    source = source_path.read_text(encoding="utf-8")
    assert "ai_execution_count = 1" not in source
    assert "ai_execution_count += 1" not in source
