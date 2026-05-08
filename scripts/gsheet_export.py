"""
Google Sheet-compatible CSV/JSON export layer.

Exports (6 logs)
----------------
  1. signal_inbox_log
  2. reflection_log
  3. manual_trade_log
  4. reconciliation_log
  5. moltbook_mistake_log
  6. source_health_log

Rules
-----
- No Google API credentials. No .env edits. No network calls.
- No external write unless explicitly called with an output_path argument.
- CSV headers are stable, frontend-friendly snake_case (no spaces).
- Every exported row carries advisory_status=ADVISORY_ONLY and
  execution_mode=HUMAN_ONLY.  ai_execution_count is always 0.
- This module only READS from JSONL logs; it never writes to them.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

try:
    from scripts.signal_inbox_api import (
        AI_SUMMARIES_LOG,
        INBOX_STATES_LOG,
        MANUAL_TRADE_LOG,
        RECONCILIATIONS_LOG,
        REFLECTIONS_LOG,
        list_inbox_items,
    )
    from scripts.moltbook_api import MOLTBOOK_LOG
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:
    from signal_inbox_api import (  # type: ignore[no-redef]
        AI_SUMMARIES_LOG,
        INBOX_STATES_LOG,
        MANUAL_TRADE_LOG,
        RECONCILIATIONS_LOG,
        REFLECTIONS_LOG,
        list_inbox_items,
    )
    from moltbook_api import MOLTBOOK_LOG  # type: ignore[no-redef]
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0

# ---------------------------------------------------------------------------
# CSV headers — stable, frontend-friendly
# ---------------------------------------------------------------------------

SIGNAL_INBOX_HEADERS: list[str] = [
    "event_id",
    "ticker",
    "signal_state",
    "entry_type",
    "priority_score",
    "observed_at",
    "source_file",
    "persistence_score",
    "blocker_pressure_score",
    "kill_rate_score",
    "blocker_attribution",
    "user_status",
    "has_reflection",
    "has_ai_summary",
    "advisory_status",
    "human_review_required",
    "execution_mode",
    "ai_execution_count",
]

REFLECTION_HEADERS: list[str] = [
    "reflection_id",
    "event_id",
    "author",
    "conviction_level",
    "reflection_text",
    "reflected_at",
    "advisory_status",
    "human_review_required",
    "execution_mode",
    "ai_execution_count",
]

MANUAL_TRADE_HEADERS: list[str] = [
    "trade_id",
    "event_id",
    "ticker",
    "side",
    "quantity",
    "price",
    "executed_at",
    "thesis",
    "notes",
    "logged_by",
    "execution_mode",
    "ai_execution_count",
    "broker_api_called",
    "broker_order_id",
    "advisory_status",
    "human_review_required",
]

RECONCILIATION_HEADERS: list[str] = [
    "reconciliation_id",
    "trade_id",
    "event_id",
    "reconciled_at",
    "actual_fill_price",
    "actual_quantity",
    "outcome_notes",
    "pnl_estimate",
    "outcome_status",
    "execution_mode",
    "ai_execution_count",
    "advisory_status",
    "human_review_required",
]

MOLTBOOK_HEADERS: list[str] = [
    "entry_id",
    "event_id",
    "ticker",
    "original_signal_thesis",
    "ai_interpretation",
    "user_reflection",
    "final_human_decision",
    "manual_trade_log_id",
    "outcome",
    "mistake_type",
    "lesson_learned",
    "bias_detected",
    "recalibration_note",
    "future_rule_update",
    "logged_at",
    "advisory_status",
    "human_review_required",
    "execution_mode",
    "ai_execution_count",
]

SOURCE_HEALTH_HEADERS: list[str] = [
    "export_timestamp",
    "snapshot_count",
    "signal_event_count",
    "ticker_count",
    "killed_count",
    "blocked_count",
    "attribution_event_count",
    "kill_log_event_count",
    "snapshot_event_count",
    "fabric_bull_state",
    "advisory_status",
    "human_review_required",
    "execution_mode",
    "ai_execution_count",
]

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


def _enforce_advisory(row: dict[str, Any], headers: list[str]) -> dict[str, Any]:
    """Return a copy of row with advisory fields enforced, projected to headers."""
    projected = {h: row.get(h, "") for h in headers}
    projected["advisory_status"] = _ADVISORY_STATUS
    if "execution_mode" in headers:
        projected["execution_mode"] = _EXECUTION_MODE
    if "ai_execution_count" in headers:
        projected["ai_execution_count"] = _AI_EXECUTION_COUNT
    return projected


def _to_csv(headers: list[str], rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=headers,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(_enforce_advisory(row, headers))
    return buf.getvalue()


def _save(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Signal Inbox Log
# ---------------------------------------------------------------------------


def export_signal_inbox_log(output_path: Path | None = None) -> str:
    """Export signal inbox items as a Google-Sheets-compatible CSV string."""
    result = list_inbox_items(write_runtime=False)
    content = _to_csv(SIGNAL_INBOX_HEADERS, result.get("items", []))
    if output_path:
        _save(content, output_path)
    return content


# ---------------------------------------------------------------------------
# 2. Reflection Log
# ---------------------------------------------------------------------------


def export_reflection_log(output_path: Path | None = None) -> str:
    """Export user reflections as a Google-Sheets-compatible CSV string."""
    content = _to_csv(REFLECTION_HEADERS, _load_jsonl(REFLECTIONS_LOG))
    if output_path:
        _save(content, output_path)
    return content


# ---------------------------------------------------------------------------
# 3. Manual Trade Log
# ---------------------------------------------------------------------------


def export_manual_trade_log(output_path: Path | None = None) -> str:
    """Export manual trade log as a Google-Sheets-compatible CSV string."""
    content = _to_csv(MANUAL_TRADE_HEADERS, _load_jsonl(MANUAL_TRADE_LOG))
    if output_path:
        _save(content, output_path)
    return content


# ---------------------------------------------------------------------------
# 4. Reconciliation Log
# ---------------------------------------------------------------------------


def export_reconciliation_log(output_path: Path | None = None) -> str:
    """Export trade reconciliations as a Google-Sheets-compatible CSV string."""
    content = _to_csv(RECONCILIATION_HEADERS, _load_jsonl(RECONCILIATIONS_LOG))
    if output_path:
        _save(content, output_path)
    return content


# ---------------------------------------------------------------------------
# 5. Moltbook Mistake Log
# ---------------------------------------------------------------------------


def export_moltbook_mistake_log(output_path: Path | None = None) -> str:
    """Export Moltbook mistake-learning entries as a Google-Sheets-compatible CSV string."""
    content = _to_csv(MOLTBOOK_HEADERS, _load_jsonl(MOLTBOOK_LOG))
    if output_path:
        _save(content, output_path)
    return content


# ---------------------------------------------------------------------------
# 6. Source Health Log
# ---------------------------------------------------------------------------


def export_source_health_log(output_path: Path | None = None) -> str:
    """Export a single-row source health snapshot as a Google-Sheets-compatible CSV string."""
    result = list_inbox_items(write_runtime=False)
    stats = result.get("fabric_stats", {})
    row: dict[str, Any] = {
        "export_timestamp": utc_timestamp(),
        "snapshot_count": stats.get("total_snapshot_rows", 0),
        "signal_event_count": stats.get("total_signal_events", 0),
        "ticker_count": stats.get("total_tickers_observed", 0),
        "killed_count": stats.get("killed_signal_count", 0),
        "blocked_count": stats.get("blocked_signal_count", 0),
        "attribution_event_count": stats.get("attribution_event_count", 0),
        "kill_log_event_count": stats.get("kill_log_event_count", 0),
        "snapshot_event_count": stats.get("snapshot_event_count", 0),
        "fabric_bull_state": result.get("fabric_bull_state", "UNKNOWN"),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
    }
    content = _to_csv(SOURCE_HEALTH_HEADERS, [row])
    if output_path:
        _save(content, output_path)
    return content


# ---------------------------------------------------------------------------
# Export all logs to a directory
# ---------------------------------------------------------------------------

_EXPORT_MANIFEST: list[tuple[str, Any]] = [
    ("signal_inbox_log.csv", export_signal_inbox_log),
    ("reflection_log.csv", export_reflection_log),
    ("manual_trade_log.csv", export_manual_trade_log),
    ("reconciliation_log.csv", export_reconciliation_log),
    ("moltbook_mistake_log.csv", export_moltbook_mistake_log),
    ("source_health_log.csv", export_source_health_log),
]


def export_all_logs(output_dir: Path) -> dict[str, str]:
    """Write all 6 CSV exports to output_dir.

    Returns a dict mapping filename -> absolute path written.
    No network calls, no Google API.  Only writes when called explicitly.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for filename, fn in _EXPORT_MANIFEST:
        path = output_dir / filename
        fn(output_path=path)
        written[filename] = str(path)
    return written


__all__ = [
    "SIGNAL_INBOX_HEADERS",
    "REFLECTION_HEADERS",
    "MANUAL_TRADE_HEADERS",
    "RECONCILIATION_HEADERS",
    "MOLTBOOK_HEADERS",
    "SOURCE_HEALTH_HEADERS",
    "export_signal_inbox_log",
    "export_reflection_log",
    "export_manual_trade_log",
    "export_reconciliation_log",
    "export_moltbook_mistake_log",
    "export_source_health_log",
    "export_all_logs",
]
