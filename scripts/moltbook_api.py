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

# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------

MOLTBOOK_LOG: Path = LOG_DIR / "moltbook_entries.jsonl"

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
    if mistake_type not in MISTAKE_CATEGORIES:
        return _error_response(
            "log_moltbook_entry",
            f"mistake_type must be one of {sorted(MISTAKE_CATEGORIES)}, got {mistake_type!r}",
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
) -> dict[str, Any]:
    """List Moltbook entries, optionally filtered by ticker or mistake_type."""
    rows = _load_jsonl(MOLTBOOK_LOG)
    if ticker:
        rows = [r for r in rows if r.get("ticker") == str(ticker).upper()]
    if mistake_type:
        rows = [r for r in rows if r.get("mistake_type") == mistake_type]
    return {
        "operation": "list_moltbook_entries",
        "entry_count": len(rows),
        "entries": rows,
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
    "MoltbookEntry",
    "log_moltbook_entry",
    "list_moltbook_entries",
    "get_moltbook_entry",
    "get_mistake_category_summary",
]
