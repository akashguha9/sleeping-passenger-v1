"""
Moltbook API — self-correction and mistake-learning layer.

Logs the full lifecycle of a signal decision for human review and recalibration:
  1.  original_signal_thesis   — what the signal said initially
  2.  ai_interpretation        — AI advisory interpretation (never a directive)
  3.  user_reflection          — human's reflection before decision
  4.  final_human_decision     — what the human actually decided
  5.  manual_trade_log_id      — trade_id from log_manual_trade (if any)
  6.  outcome                  — what actually happened (filled in later)
  7.  mistake_type             — category of learning event
  8.  lesson_learned           — concise lesson text
  9.  bias_detected            — cognitive bias label if any
  10. recalibration_note       — how to adjust future behavior
  11. future_rule_update       — suggested rule change for human review

Mistake categories
------------------
  good_signal_bad_timing         bad_signal_lucky_profit
  good_signal_good_execution     bad_signal_correct_rejection
  missed_signal                  overtraded_signal
  chaos_ignored                  false_confirmation
  late_entry                     early_exit
  no_trade_correct               no_trade_missed_opportunity

All outputs carry advisory_status="ADVISORY_ONLY" and human_review_required=True.
ai_execution_count is always 0.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import LOG_DIR, append_jsonl, utc_timestamp
except ModuleNotFoundError:
    from runtime_common import LOG_DIR, append_jsonl, utc_timestamp  # type: ignore[no-redef]

_DB_AVAILABLE = False
_persistence = None
try:
    try:
        import scripts.persistence as _persistence
    except ModuleNotFoundError:
        import persistence as _persistence  # type: ignore[no-redef]
    _DB_AVAILABLE = True
except Exception:
    pass

# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------

MOLTBOOK_LOG: Path = LOG_DIR / "moltbook_entries.jsonl"
_MOLTBOOK_LOG_ORIG: Path = MOLTBOOK_LOG  # baseline for test-isolation detection

# ---------------------------------------------------------------------------
# Mistake categories
# ---------------------------------------------------------------------------

MISTAKE_CATEGORIES: frozenset[str] = frozenset(
    {
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
)

# Outcome-based learning categories used by the reconciliation→Moltbook
# bridge (scripts/moltbook_reconciliation_bridge.py).  These describe how a
# *closed* trade resolved, not the signal-decision quality the original 12
# MISTAKE_CATEGORIES describe.  Kept as a SEPARATE frozenset so the public
# MISTAKE_CATEGORIES contract (and the tests that assert len == 12) stays
# unchanged.  They never authorise execution.
LOSS_REVIEW_CATEGORIES: frozenset[str] = frozenset(
    {
        "trade_loss",        # generic closed-at-a-loss, no finer signal
        "manual_exit_loss",  # operator manually exited before stop breach
        "stop_loss_breach",  # exit driven by a stop-loss breach
    }
)

# The full set log_moltbook_entry will accept.  Validation widens to include
# the loss-review categories so honest closed-loss entries can be recorded
# without loosening the original signal-quality taxonomy.
ACCEPTED_MISTAKE_TYPES: frozenset[str] = MISTAKE_CATEGORIES | LOSS_REVIEW_CATEGORIES

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class MoltbookEntry:
    entry_id: str
    event_id: str
    ticker: str
    original_signal_thesis: str
    ai_interpretation: str
    user_reflection: str
    final_human_decision: str
    manual_trade_log_id: str
    outcome: str
    mistake_type: str
    lesson_learned: str
    bias_detected: str
    recalibration_note: str
    future_rule_update: str
    logged_at: str
    advisory_status: str = _ADVISORY_STATUS
    human_review_required: bool = True
    execution_mode: str = _EXECUTION_MODE
    ai_execution_count: int = _AI_EXECUTION_COUNT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except json.JSONDecodeError:
            continue
    return rows


def _error_response(operation: str, message: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "error": message,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_moltbook_entry(
    *,
    event_id: str,
    ticker: str,
    original_signal_thesis: str,
    ai_interpretation: str,
    user_reflection: str,
    final_human_decision: str,
    manual_trade_log_id: str = "",
    outcome: str = "",
    mistake_type: str,
    lesson_learned: str,
    bias_detected: str = "",
    recalibration_note: str = "",
    future_rule_update: str = "",
) -> dict[str, Any]:
    """Log a Moltbook self-correction entry.

    mistake_type must be one of MISTAKE_CATEGORIES.
    All other string fields are free-form human text.
    """
    if not event_id:
        return _error_response("log_moltbook_entry", "event_id required")
    if not ticker:
        return _error_response("log_moltbook_entry", "ticker required")
    if mistake_type not in ACCEPTED_MISTAKE_TYPES:
        return _error_response(
            "log_moltbook_entry",
            f"mistake_type must be one of {sorted(ACCEPTED_MISTAKE_TYPES)}, got {mistake_type!r}",
        )
    if not lesson_learned:
        return _error_response("log_moltbook_entry", "lesson_learned required")

    entry = MoltbookEntry(
        entry_id=f"MB_{uuid.uuid4().hex[:12]}",
        event_id=str(event_id),
        ticker=str(ticker).upper(),
        original_signal_thesis=str(original_signal_thesis),
        ai_interpretation=str(ai_interpretation),
        user_reflection=str(user_reflection),
        final_human_decision=str(final_human_decision),
        manual_trade_log_id=str(manual_trade_log_id),
        outcome=str(outcome),
        mistake_type=str(mistake_type),
        lesson_learned=str(lesson_learned),
        bias_detected=str(bias_detected),
        recalibration_note=str(recalibration_note),
        future_rule_update=str(future_rule_update),
        logged_at=utc_timestamp(),
    )
    append_jsonl(MOLTBOOK_LOG, entry.to_dict(), stamp=False)
    # SQLite is canonical, but ONLY for real runtime writes.  When a test
    # monkeypatches MOLTBOOK_LOG to a tmp path the JSONL write is isolated;
    # we must NOT then leak the row into the canonical runtime DB.  The
    # sentinel comparison mirrors the read-path guard in
    # list_moltbook_entries and is the fix for the historical pollution
    # where test/demo entries (FABRIC_SPY, "Persistence above 0.8",
    # Thesis A …) accumulated in runtime/mvp_local.db because only the
    # JSONL path was isolated.
    if (
        _DB_AVAILABLE
        and _persistence is not None
        and MOLTBOOK_LOG == _MOLTBOOK_LOG_ORIG
    ):
        try:
            _persistence.insert_moltbook_entry(
                entry.entry_id, entry.event_id, entry.ticker,
                entry.original_signal_thesis, entry.ai_interpretation,
                entry.user_reflection, entry.final_human_decision,
                entry.manual_trade_log_id, entry.outcome,
                entry.mistake_type, entry.lesson_learned,
                entry.bias_detected, entry.recalibration_note,
                entry.future_rule_update, entry.logged_at,
            )
        except Exception:
            pass

    return {
        "operation": "log_moltbook_entry",
        "entry_id": entry.entry_id,
        "event_id": event_id,
        "ticker": entry.ticker,
        "mistake_type": mistake_type,
        "status": "logged",
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def list_moltbook_entries(
    *,
    ticker: str | None = None,
    mistake_type: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """List Moltbook entries, optionally filtered by ticker or mistake_type.

    By default this returns ONLY canonical visible entries — eligible,
    non-duplicate, non-test/demo, non-hidden.  Pass ``include_raw=True``
    to surface every row including hidden/duplicate/ineligible ones for
    the debug toggle.

    Response metadata always reports:
      raw_total_entries, visible_entries, hidden_ineligible,
      hidden_duplicates, hidden_test_demo, allowed_event_types
    """
    raw_rows: list[dict[str, Any]] = []
    if _DB_AVAILABLE and _persistence is not None and MOLTBOOK_LOG == _MOLTBOOK_LOG_ORIG:
        try:
            raw_rows = _persistence.get_moltbook_entries(
                ticker=ticker, mistake_type=mistake_type, include_hidden=True,
            )
        except Exception:
            pass
    if not raw_rows:
        raw_rows = _load_jsonl(MOLTBOOK_LOG)
        if ticker:
            raw_rows = [r for r in raw_rows if r.get("ticker") == str(ticker).upper()]
        if mistake_type:
            raw_rows = [r for r in raw_rows if r.get("mistake_type") == mistake_type]

    # Lazy-import the bridge so this module stays import-cheap on cold
    # paths (e.g. CLI-only consumers).  The bridge owns the canonical
    # eligibility contract.
    allowed_event_types: list[str] = []
    eligibility_fn = None
    try:
        try:
            from scripts.moltbook_learning_bridge import (
                ALLOWED_MOLTBOOK_EVENT_TYPES,
                is_moltbook_eligible_reconciliation_event,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from moltbook_learning_bridge import (  # type: ignore[no-redef]
                ALLOWED_MOLTBOOK_EVENT_TYPES,
                is_moltbook_eligible_reconciliation_event,
            )
        allowed_event_types = sorted(ALLOWED_MOLTBOOK_EVENT_TYPES)
        eligibility_fn = is_moltbook_eligible_reconciliation_event
    except Exception:
        pass

    hidden_duplicates = 0
    hidden_test_demo = 0
    hidden_ineligible = 0
    visible_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if int(row.get("hidden_from_default_view") or 0):
            if int(row.get("is_duplicate") or 0):
                hidden_duplicates += 1
            reason = str(row.get("hidden_reason") or "")
            if reason.startswith("SKIP_TEST_DEMO") or reason == "SKIP_TEST_DEMO_FIXTURE":
                hidden_test_demo += 1
            else:
                hidden_ineligible += 1
            if include_raw:
                visible_rows.append(row)
            continue
        # Eligibility check is for reconciliation-derived entries (which
        # have an event_type populated).  Legacy manually-logged
        # signal-decision rows (event_type='', mistake_type in the
        # original 12 categories) are pre-existing Moltbook content and
        # should remain visible.
        raw_event_type = str(row.get("event_type") or "").strip()
        if eligibility_fn is not None and raw_event_type:
            verdict = eligibility_fn(
                {
                    "event_type": raw_event_type,
                    "symbol": row.get("ticker") or "",
                    "trade_id": row.get("trade_id") or row.get("manual_trade_log_id") or "",
                    "manual_trade_id": row.get("manual_trade_log_id") or "",
                    "exit_price": row.get("exit_price"),
                    "realized_pl": row.get("realized_pl"),
                    "thesis": row.get("original_signal_thesis") or "",
                }
            )
            if not verdict["eligible"]:
                if verdict["reason"] == "SKIP_TEST_DEMO_FIXTURE":
                    hidden_test_demo += 1
                else:
                    hidden_ineligible += 1
                if include_raw:
                    visible_rows.append(row)
                continue
        visible_rows.append(row)

    items = visible_rows if not include_raw else raw_rows
    return {
        "operation": "list_moltbook_entries",
        "entry_count": len(items),
        "entries": items,
        "items": items,
        "raw_total_entries": len(raw_rows),
        "visible_entries": len(visible_rows) if not include_raw else len(
            [r for r in raw_rows if not int(r.get("hidden_from_default_view") or 0)]
        ),
        "hidden_ineligible": hidden_ineligible,
        "hidden_duplicates": hidden_duplicates,
        "hidden_test_demo": hidden_test_demo,
        "allowed_event_types": allowed_event_types,
        "include_raw": bool(include_raw),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def get_moltbook_entry(entry_id: str) -> dict[str, Any]:
    """Get a single Moltbook entry by entry_id."""
    if not entry_id:
        return _error_response("get_moltbook_entry", "entry_id required")
    match = next(
        (r for r in _load_jsonl(MOLTBOOK_LOG) if r.get("entry_id") == entry_id),
        None,
    )
    if match is None:
        return _error_response("get_moltbook_entry", f"entry_id {entry_id!r} not found")
    return {
        "operation": "get_moltbook_entry",
        "entry": match,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def get_mistake_category_summary() -> dict[str, Any]:
    """Summarize mistake type distribution across all Moltbook entries."""
    rows = _load_jsonl(MOLTBOOK_LOG)
    counts: dict[str, int] = {cat: 0 for cat in sorted(MISTAKE_CATEGORIES)}
    for row in rows:
        mt = str(row.get("mistake_type", ""))
        if mt in counts:
            counts[mt] += 1
    return {
        "operation": "get_mistake_category_summary",
        "total_entries": len(rows),
        "mistake_type_counts": counts,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


__all__ = [
    "MOLTBOOK_LOG",
    "MISTAKE_CATEGORIES",
    "LOSS_REVIEW_CATEGORIES",
    "ACCEPTED_MISTAKE_TYPES",
    "MoltbookEntry",
    "log_moltbook_entry",
    "list_moltbook_entries",
    "get_moltbook_entry",
    "get_mistake_category_summary",
]
