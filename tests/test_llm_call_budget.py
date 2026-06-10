"""SEC-S7 regression: paid LLM calls are budgeted — denial-of-wallet guard.

Contract:
* per-run budget (MVP_LLM_RUN_BUDGET) and persistent daily ceiling
  (MVP_LLM_DAILY_CALL_CEILING) both fail CLOSED with stamped errors;
* the daily counter survives across "runs" (process counter resets,
  state file does not);
* a corrupt state file fails closed (assumes ceiling reached), never open;
* the Grok adapter refuses the call BEFORE any network transport when
  the budget is exhausted, returning a stamped failure artifact.
"""
from __future__ import annotations

import json

import pytest

from scripts import llm_call_budget as budget
from scripts.llm_call_budget import LLMBudgetExceeded, acquire_llm_call


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_LLM_BUDGET_STATE_PATH", str(tmp_path / "budget.json"))
    monkeypatch.delenv("MVP_LLM_RUN_BUDGET", raising=False)
    monkeypatch.delenv("MVP_LLM_DAILY_CALL_CEILING", raising=False)
    budget._reset_run_counters_for_tests()
    yield
    budget._reset_run_counters_for_tests()


def test_per_run_budget_fails_closed(monkeypatch):
    monkeypatch.setenv("MVP_LLM_RUN_BUDGET", "2")
    acquire_llm_call("grok_xai")
    acquire_llm_call("grok_xai")
    with pytest.raises(LLMBudgetExceeded) as exc:
        acquire_llm_call("grok_xai")
    detail = exc.value.detail
    assert detail["scope"] == "per_run"
    assert detail["execution_gate"] == "LOCKED"
    assert detail["broker_api_called"] is False


def test_daily_ceiling_persists_across_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_LLM_DAILY_CALL_CEILING", "3")
    monkeypatch.setenv("MVP_LLM_RUN_BUDGET", "100")
    acquire_llm_call("grok_xai")
    acquire_llm_call("grok_xai")
    # "New run": process counters reset, the state file remains.
    budget._reset_run_counters_for_tests()
    acquire_llm_call("grok_xai")
    with pytest.raises(LLMBudgetExceeded) as exc:
        acquire_llm_call("grok_xai")
    assert exc.value.detail["scope"] == "daily"
    assert exc.value.detail["calls_used"] == 3


def test_corrupt_state_file_fails_closed(tmp_path, monkeypatch):
    state = tmp_path / "budget.json"
    state.write_text("{not json")
    with pytest.raises(LLMBudgetExceeded) as exc:
        acquire_llm_call("grok_xai")
    assert exc.value.detail["scope"] == "daily"


def test_budgets_are_per_source_for_run_scope(monkeypatch):
    monkeypatch.setenv("MVP_LLM_RUN_BUDGET", "1")
    monkeypatch.setenv("MVP_LLM_DAILY_CALL_CEILING", "100")
    acquire_llm_call("grok_xai")
    # A different source still has its own run budget...
    acquire_llm_call("grok_interpreter")
    # ...but the first source is now exhausted.
    with pytest.raises(LLMBudgetExceeded):
        acquire_llm_call("grok_xai")


def test_grok_adapter_refuses_before_transport(monkeypatch):
    monkeypatch.setenv("MVP_LLM_RUN_BUDGET", "0")  # nothing allowed
    monkeypatch.setenv("XAI_API_BASE_URL", "https://api.x.ai")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    from scripts.grok_xai_adapter import build_grok_xai_report

    transport_called = {"n": 0}

    def transport(url, headers, payload, timeout):
        transport_called["n"] += 1
        return (200, "{}")

    report = build_grok_xai_report(
        use_case="signal_ranking_interpreter",
        runtime_state={"generated_at": "2026-06-10T00:00:00+00:00"},
        input_json=json.dumps({"candidate_signals": [{"ticker": "X"}]}),
        transport=transport,
    )
    assert transport_called["n"] == 0, "transport must never fire over budget"
    assert report["request_attempted"] is False
    assert report["error_kind"] == "llm_budget_exceeded"
    assert report["budget_detail"]["execution_gate"] == "LOCKED"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False


def test_grok_interpreter_refuses_before_post(monkeypatch):
    monkeypatch.setenv("MVP_LLM_RUN_BUDGET", "0")
    from scripts.ingestion.grok_interpreter import GrokInterpreter

    gi = GrokInterpreter.__new__(GrokInterpreter)
    gi._prompt = "observe"
    gi._timeout = 5
    gi._base_url = "https://api.x.ai/v1/chat/completions"

    class _RequestsNeverCalled:
        def post(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("network reached despite exhausted budget")

    result, tag, detail = gi._try_model(
        _RequestsNeverCalled(), "grok-test", {}, "key"
    )
    assert result is None
    assert tag == "budget_exceeded"
    assert "budget" in detail.lower()
