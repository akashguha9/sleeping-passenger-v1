"""SEC-S7: hard budgets for paid LLM calls (denial-of-wallet guard).

Every Grok/xAI call costs real money.  Before this module there was no
per-run budget and no daily ceiling — a runaway loop or an
injection-amplified ingestion pass could burn API quota unbounded.

Two stacked limits, both fail-CLOSED with stamped errors:

* **Per-run budget** (``MVP_LLM_RUN_BUDGET``, default 50): module-level
  counter, resets per process.
* **Daily ceiling** (``MVP_LLM_DAILY_CALL_CEILING``, default 200):
  persisted to ``runtime/llm_call_budget.json`` keyed by UTC date, so it
  survives across runs within the same day.

Usage at every paid call site::

    from scripts.llm_call_budget import LLMBudgetExceeded, acquire_llm_call
    acquire_llm_call("grok_xai")   # raises LLMBudgetExceeded when over

Advisory invariants: counting only — no broker, no execution; the
exceeded error carries the locked stamps.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import RUNTIME_DIR, restrict_file_permissions
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import RUNTIME_DIR, restrict_file_permissions  # type: ignore[no-redef]

_logger = logging.getLogger("scripts.llm_call_budget")

DEFAULT_RUN_BUDGET = 50
DEFAULT_DAILY_CEILING = 200

_STATE_FILENAME = "llm_call_budget.json"

# Per-process counters: {source: count}
_RUN_COUNTS: dict[str, int] = {}


class LLMBudgetExceeded(RuntimeError):
    """A paid-LLM call was refused because a budget is exhausted."""

    def __init__(self, message: str, detail: dict[str, Any]):
        super().__init__(message)
        self.detail = detail


def _state_path() -> Path:
    override = os.environ.get("MVP_LLM_BUDGET_STATE_PATH", "").strip()
    if override:
        return Path(override)
    # Lives under diagnostics_cache/ (operational state), NOT the runtime
    # root — artifact-coherence scans runtime/*.json for pipeline
    # provenance and would flag a bare counter file as legacy-unmanaged.
    return RUNTIME_DIR / "diagnostics_cache" / _STATE_FILENAME


def run_budget() -> int:
    raw = os.environ.get("MVP_LLM_RUN_BUDGET", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_RUN_BUDGET
    except ValueError:
        return DEFAULT_RUN_BUDGET


def daily_ceiling() -> int:
    raw = os.environ.get("MVP_LLM_DAILY_CALL_CEILING", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_DAILY_CEILING
    except ValueError:
        return DEFAULT_DAILY_CEILING


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_daily_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"date": _today(), "calls": 0}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        # A corrupt counter file must not unlock unlimited spending:
        # fail CLOSED by assuming the ceiling is already reached today.
        _logger.error(
            "llm budget state unreadable at %s — failing closed (ceiling)", path
        )
        return {"date": _today(), "calls": daily_ceiling(), "corrupt": True}
    if not isinstance(state, dict) or state.get("date") != _today():
        return {"date": _today(), "calls": 0}
    try:
        state["calls"] = max(0, int(state.get("calls", 0)))
    except (TypeError, ValueError):
        state["calls"] = daily_ceiling()
    return state


def _save_daily_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if is_new:
        restrict_file_permissions(path)


def _stamped_detail(source: str, scope: str, used: int, limit: int) -> dict[str, Any]:
    return {
        "error": "llm_budget_exceeded",
        "scope": scope,
        "source": source,
        "calls_used": used,
        "limit": limit,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def acquire_llm_call(source: str) -> dict[str, Any]:
    """Reserve one paid LLM call for *source* or raise LLMBudgetExceeded.

    Checks the per-run budget first, then the persisted daily ceiling.
    Both are fail-closed: when a limit is reached the call MUST NOT be
    made.  Returns the post-acquire usage snapshot (stamped).
    """
    run_used = _RUN_COUNTS.get(source, 0)
    limit = run_budget()
    if run_used >= limit:
        detail = _stamped_detail(source, "per_run", run_used, limit)
        _logger.error(
            "SEC-S7: per-run LLM budget exhausted for %s (%d/%d) — refusing call",
            source, run_used, limit,
        )
        raise LLMBudgetExceeded(
            f"per-run LLM budget exhausted for {source} ({run_used}/{limit})",
            detail,
        )

    state = _load_daily_state()
    ceiling = daily_ceiling()
    if int(state.get("calls", 0)) >= ceiling:
        detail = _stamped_detail(source, "daily", int(state["calls"]), ceiling)
        _logger.error(
            "SEC-S7: DAILY LLM ceiling reached (%d/%d) — refusing %s call",
            state["calls"], ceiling, source,
        )
        raise LLMBudgetExceeded(
            f"daily LLM call ceiling reached ({state['calls']}/{ceiling})",
            detail,
        )

    _RUN_COUNTS[source] = run_used + 1
    state["calls"] = int(state.get("calls", 0)) + 1
    _save_daily_state(state)
    return {
        "source": source,
        "run_calls_used": _RUN_COUNTS[source],
        "run_budget": limit,
        "daily_calls_used": state["calls"],
        "daily_ceiling": ceiling,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def _reset_run_counters_for_tests() -> None:
    _RUN_COUNTS.clear()
