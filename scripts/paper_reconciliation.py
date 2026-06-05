from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.runtime_common import (
        EXTERNAL_MARKS_PATH,
        MODEL_UPGRADE_REPORT_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_FILL_LEDGER_PATH,
        PAPER_ORDER_LEDGER_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        PAPER_RECONCILIATION_REPORT_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        POST_TRADE_FEEDBACK_PATH,
        build_deployment_permissions,
        compute_config_fingerprint,
        get_git_commit_hash,
        get_run_id,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        EXTERNAL_MARKS_PATH,
        MODEL_UPGRADE_REPORT_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_FILL_LEDGER_PATH,
        PAPER_ORDER_LEDGER_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        PAPER_RECONCILIATION_REPORT_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        POST_TRADE_FEEDBACK_PATH,
        build_deployment_permissions,
        compute_config_fingerprint,
        get_git_commit_hash,
        get_run_id,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


LINEAGE_FIELDS = [
    "signal_id",
    "decision_id",
    "paper_order_id",
    "paper_fill_id",
    "position_id",
    "close_id",
    "mark_id",
]
SEVERE_RECONCILIATION_STATUSES = {
    "missing_mark",
    "missing_fill",
    "missing_close_context",
    "legacy_incomplete",
    "data_gap_unresolved",
}


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(
        json.dumps(row, separators=(",", ":")) for row in rows
    )
    if body:
        body += "\n"
    temp_path.write_text(body, encoding="utf-8")
    temp_path.replace(path)


def _history_key(row: dict[str, Any]) -> str:
    close_id = str(row.get("close_id") or "").strip()
    if close_id:
        return close_id
    position_id = str(row.get("position_id") or "").strip()
    exit_time = str(row.get("exit_time") or row.get("closed_at") or "").strip()
    return f"{position_id}:{exit_time}"


def lineage_completeness_score(row: dict[str, Any]) -> float:
    present = 0
    for key in LINEAGE_FIELDS:
        value = row.get(key)
        if isinstance(value, str):
            if value.strip():
                present += 1
        elif value is not None:
            present += 1
    return round(present / len(LINEAGE_FIELDS), 3)


def assign_reconciliation_status(
    data_gap_flags: list[str],
    unresolved_fields: list[str],
    close_row: dict[str, Any],
) -> str:
    opening_keys = [
        "opening_decision_id",
        "opening_paper_order_id",
        "opening_paper_fill_id",
    ]
    if any(not str(close_row.get(key) or "").strip() for key in opening_keys):
        return "legacy_incomplete"
    if "missing_mark" in data_gap_flags:
        return "missing_mark"
    if any(flag in data_gap_flags for flag in ("missing_open_fill", "missing_open_order")):
        return "missing_fill"
    if any(
        field in unresolved_fields
        for field in ("exit_price", "exit_time", "close_reason")
    ):
        return "missing_close_context"
    if any(flag in data_gap_flags for flag in ("mark_error", "missing_feedback")):
        return "data_gap_unresolved"
    if data_gap_flags or unresolved_fields:
        return "partially_reconciled"
    return "fully_reconciled"


def classify_evidence_strength(sample_size: int) -> str:
    if sample_size < 5:
        return "insufficient_evidence"
    if sample_size < 10:
        return "weak_signal"
    if sample_size < 20:
        return "early_pattern"
    return "moderate_pattern"


def _parameter_change_note(sample_size: int) -> tuple[bool, str]:
    strength = classify_evidence_strength(sample_size)
    if strength == "insufficient_evidence":
        return False, "insufficient_evidence_for_parameter_change"
    if strength == "weak_signal":
        return False, "weak_signal_hold_parameters"
    if strength == "early_pattern":
        return False, "early_pattern_observe_only"
    return True, "moderate_pattern_review_parameter_candidates"


def _runtime_state_with_external_marks(
    runtime_state: dict[str, Any],
    marks_payload: dict[str, Any],
) -> dict[str, Any]:
    state = dict(runtime_state)
    success_count = int(marks_payload.get("success_count") or 0)
    fetched_at = (
        marks_payload.get("fetched_at")
        or marks_payload.get("artifact_written_at")
        or utc_timestamp()
    )
    state["external_observation_active"] = success_count > 0
    state["external_observation_source"] = marks_payload.get("source_name") or "yahoo_finance"
    state["external_observation_fetched_at"] = fetched_at
    return state


def _lookup_by_id(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip()
        if value:
            mapping[value] = row
    return mapping


def _lookup_mark_rows(
    marks_payload: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    marks = marks_payload.get("marks", [])
    if not isinstance(marks, list):
        marks = []
    by_id: dict[str, dict[str, Any]] = {}
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in marks:
        if not isinstance(row, dict):
            continue
        mark_id = str(row.get("mark_id") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        if mark_id:
            by_id[mark_id] = row
        if ticker:
            by_ticker[ticker] = row
    return by_id, by_ticker


def _compute_holding_period_days(entry_time: Any, exit_time: Any) -> float | None:
    entry_dt = _parse_iso_timestamp(entry_time)
    exit_dt = _parse_iso_timestamp(exit_time)
    if entry_dt is None or exit_dt is None:
        return None
    # A negative holding period means exit precedes entry — a swapped/invalid
    # date pair, not a real holding window.  Treat it the same as a missing
    # date (return None) instead of emitting a misleading negative number that
    # could silently corrupt holding-period stats.  Same-day (0.0) is valid.
    if exit_dt < entry_dt:
        return None
    return round((exit_dt - entry_dt).total_seconds() / 86400.0, 3)


def _compute_realized_return_pct(
    entry_price: float | None,
    exit_price: float | None,
    side: str,
) -> float | None:
    if entry_price in {None, 0.0} or exit_price is None:
        return None
    normalized_side = str(side or "").upper()
    if normalized_side == "SELL":
        return round(((entry_price - exit_price) / entry_price) * 100.0, 4)
    return round(((exit_price - entry_price) / entry_price) * 100.0, 4)


def build_reconciliation_row(
    close_row: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
    orders_by_id: dict[str, dict[str, Any]],
    fills_by_id: dict[str, dict[str, Any]],
    feedback_by_close_id: dict[str, dict[str, Any]],
    marks_by_id: dict[str, dict[str, Any]],
    marks_by_ticker: dict[str, dict[str, Any]],
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    opening_decision_id = str(
        close_row.get("opening_decision_id") or close_row.get("decision_id") or ""
    ).strip()
    opening_order_id = str(
        close_row.get("opening_paper_order_id") or close_row.get("paper_order_id") or ""
    ).strip()
    opening_fill_id = str(
        close_row.get("opening_paper_fill_id") or close_row.get("paper_fill_id") or ""
    ).strip()
    close_fill_id = str(close_row.get("paper_fill_id") or "").strip()
    close_decision_id = str(close_row.get("decision_id") or "").strip()
    close_order_id = str(close_row.get("paper_order_id") or "").strip()
    position_id = str(close_row.get("position_id") or "").strip()
    close_id = str(close_row.get("close_id") or "").strip()
    ticker = str(close_row.get("ticker") or "").strip().upper()
    signal_id = str(close_row.get("signal_id") or "").strip()

    opening_decision = decisions_by_id.get(opening_decision_id, {})
    opening_order = orders_by_id.get(opening_order_id, {})
    opening_fill = fills_by_id.get(opening_fill_id, {})
    close_fill = fills_by_id.get(close_fill_id, {})
    feedback_row = feedback_by_close_id.get(close_id, {})
    mark_id = str(
        close_row.get("mark_id") or feedback_row.get("mark_id") or ""
    ).strip()
    mark_row = marks_by_id.get(mark_id) if mark_id else None
    if mark_row is None and ticker:
        mark_row = marks_by_ticker.get(ticker)
        if mark_row is not None:
            mark_id = str(mark_row.get("mark_id") or "").strip()

    side = str(
        opening_order.get("side")
        or opening_fill.get("side")
        or ""
    ).strip().upper()
    entry_price = _coerce_float(
        opening_fill.get("fill_price") or opening_fill.get("entry_price")
    )
    entry_qty = _coerce_float(
        opening_fill.get("fill_qty") or opening_order.get("requested_qty")
    )
    entry_time = (
        opening_fill.get("filled_at")
        or opening_order.get("created_at")
        or opening_decision.get("decided_at")
    )
    exit_price = _coerce_float(close_row.get("exit_price") or close_fill.get("fill_price"))
    exit_time = close_row.get("closed_at") or close_fill.get("filled_at")
    close_reason = str(close_row.get("close_reason") or "").strip()
    realized_pnl = _coerce_float(close_row.get("realized_pnl"))
    realized_return_pct = _coerce_float(feedback_row.get("realized_return_pct"))
    if realized_return_pct is None:
        realized_return_pct = _compute_realized_return_pct(entry_price, exit_price, side)

    holding_period_days = _coerce_float(feedback_row.get("holding_period_days"))
    if holding_period_days is None:
        holding_period_days = _compute_holding_period_days(entry_time, exit_time)

    mark_source = str(
        close_row.get("mark_source_name")
        or (mark_row or {}).get("source_name")
        or ""
    ).strip()
    mark_fetched_at = (
        close_row.get("mark_fetched_at")
        or (mark_row or {}).get("fetched_at")
    )
    mark_staleness = str(
        close_row.get("mark_staleness_classification")
        or (mark_row or {}).get("staleness_classification")
        or ""
    ).strip()
    entry_light_score = feedback_row.get("entry_light_score")
    if entry_light_score is None:
        entry_light_score = opening_decision.get("entry_light_score")
    entry_shadow_score = feedback_row.get("entry_shadow_score")
    if entry_shadow_score is None:
        entry_shadow_score = opening_decision.get("entry_shadow_score")
    entry_moon_phase = feedback_row.get("entry_moon_phase") or opening_decision.get(
        "entry_moon_phase"
    )
    entry_temporal_position = feedback_row.get("entry_temporal_position")
    if entry_temporal_position is None:
        entry_temporal_position = opening_decision.get("entry_temporal_position")
    entry_crowding_score = feedback_row.get("entry_crowding_score")
    if entry_crowding_score is None:
        entry_crowding_score = opening_decision.get("entry_crowding_score")
    entry_light_velocity = feedback_row.get("entry_light_velocity")
    if entry_light_velocity is None:
        entry_light_velocity = opening_decision.get("entry_light_velocity")
    entry_shadow_velocity = feedback_row.get("entry_shadow_velocity")
    if entry_shadow_velocity is None:
        entry_shadow_velocity = opening_decision.get("entry_shadow_velocity")
    entry_edge_context_score = feedback_row.get("entry_edge_context_score")
    if entry_edge_context_score is None:
        entry_edge_context_score = opening_decision.get("entry_edge_context_score")
    entry_full_moon_trap_flag = feedback_row.get("entry_full_moon_trap_flag")
    if entry_full_moon_trap_flag is None:
        entry_full_moon_trap_flag = opening_decision.get("entry_full_moon_trap_flag")

    data_gap_flags: list[str] = []
    unresolved_fields: list[str] = []
    if not mark_id or mark_row is None:
        data_gap_flags.append("missing_mark")
    elif not bool(mark_row.get("ok", True)):
        data_gap_flags.append("mark_error")
    if not opening_order_id or not opening_order:
        data_gap_flags.append("missing_open_order")
    if not opening_fill_id or not opening_fill:
        data_gap_flags.append("missing_open_fill")
    if not feedback_row:
        data_gap_flags.append("missing_feedback")
    if mark_staleness in {"stale", "unknown", "clock_skew"}:
        data_gap_flags.append("stale_mark_data")

    if not signal_id:
        unresolved_fields.append("signal_id")
    if entry_price is None:
        unresolved_fields.append("entry_price")
    if entry_qty is None:
        unresolved_fields.append("entry_qty")
    if not entry_time:
        unresolved_fields.append("entry_time")
    if exit_price is None:
        unresolved_fields.append("exit_price")
    if not exit_time:
        unresolved_fields.append("exit_time")
    if not close_reason:
        unresolved_fields.append("close_reason")
    if (
        entry_light_score is None
        and entry_shadow_score is None
        and not str(entry_moon_phase or "").strip()
        and entry_temporal_position is None
        and entry_crowding_score is None
    ):
        data_gap_flags.append("missing_entry_context")

    reconciliation_status = assign_reconciliation_status(
        data_gap_flags=data_gap_flags,
        unresolved_fields=unresolved_fields,
        close_row=close_row,
    )
    thesis_state = str(
        feedback_row.get("thesis_state")
        or (
            "invalidated"
            if close_reason in {"stop_hit", "invalidated_by_market_move"}
            else "confirmed"
            if close_reason == "target_hit"
            else "unresolved"
        )
    ).strip()
    stale_signal_flag = close_reason == "stale_signal_timeout"
    invalidation_flag = close_reason == "invalidated_by_market_move" or thesis_state == "invalidated"
    false_positive_flag = bool(
        invalidation_flag
        and realized_return_pct is not None
        and realized_return_pct < 0
    )

    stamped = stamp_payload({}, runtime_state=runtime_state)
    row = {
        "artifact_kind": "paper_reconciliation_row",
        "signal_id": signal_id,
        "decision_id": opening_decision_id,
        "paper_order_id": opening_order_id,
        "paper_fill_id": opening_fill_id,
        "position_id": position_id,
        "close_id": close_id,
        "mark_id": mark_id,
        "run_id": close_row.get("run_id"),
        "ticker": ticker,
        "side": side or None,
        "entry_price": entry_price,
        "entry_qty": entry_qty,
        "entry_time": entry_time,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "close_reason": close_reason or None,
        "realized_pnl": realized_pnl,
        "realized_return_pct": realized_return_pct,
        "holding_period_days": holding_period_days,
        "mfe": None,
        "mae": None,
        "entry_light_score": _coerce_float(entry_light_score),
        "entry_shadow_score": _coerce_float(entry_shadow_score),
        "entry_moon_phase": str(entry_moon_phase).strip() or None,
        "entry_temporal_position": _coerce_float(entry_temporal_position),
        "entry_crowding_score": _coerce_float(entry_crowding_score),
        "entry_light_velocity": _coerce_float(entry_light_velocity),
        "entry_shadow_velocity": _coerce_float(entry_shadow_velocity),
        "entry_edge_context_score": _coerce_float(entry_edge_context_score),
        "entry_full_moon_trap_flag": bool(entry_full_moon_trap_flag)
        if entry_full_moon_trap_flag is not None
        else None,
        "signal_to_fill_drift_bps": None,
        "fill_to_close_move_pct": realized_return_pct,
        "mark_source": mark_source or None,
        "mark_fetched_at": mark_fetched_at,
        "mark_staleness": mark_staleness or None,
        "truth_origin": close_row.get("truth_origin") or feedback_row.get("truth_origin"),
        "operating_mode": close_row.get("operating_mode") or feedback_row.get("operating_mode"),
        "source_quality_note": feedback_row.get("source_quality_notes")
        or "Yahoo Finance external observation only; validation_dependency=high.",
        "reconciliation_status": reconciliation_status,
        "lineage_completeness_score": 0.0,
        "data_gap_flags": sorted(set(data_gap_flags)),
        "unresolved_fields": sorted(set(unresolved_fields)),
        "thesis_state": thesis_state,
        "calibration_note": feedback_row.get("confidence_calibration_note"),
        "false_positive_flag": false_positive_flag,
        "stale_signal_flag": stale_signal_flag,
        "invalidation_flag": invalidation_flag,
        "parameter_change_eligible": False,
        "parameter_change_note": "insufficient_evidence_for_parameter_change",
        "close_decision_id": close_decision_id or None,
        "close_paper_order_id": close_order_id or None,
        "close_paper_fill_id": close_fill_id or None,
        "reconciliation_run_id": stamped["run_id"],
        "reconciliation_written_at": stamped["artifact_written_at"],
        "commit_hash": stamped["commit_hash"],
        "config_fingerprint": stamped["config_fingerprint"],
        "execution_context": "paper_simulated",
        # Paper lineage carry-forward from the opening fill.
        "source_observation_id": opening_fill.get("source_observation_id"),
        "observation_provider": opening_fill.get("observation_provider"),
        "reference_price": opening_fill.get("reference_price"),
        "observed_price": opening_fill.get("observed_price"),
        "price_drift_bps_at_entry": opening_fill.get("price_drift_bps"),
        "price_drift_pct_at_entry": opening_fill.get("price_drift_pct"),
        "entry_timestamp": opening_fill.get("entry_timestamp") or entry_time,
        "reconciliation_timestamp": stamped["artifact_written_at"],
        "outcome_status": (
            "reconciled" if reconciliation_status == "fully_reconciled"
            else "partially_reconciled" if reconciliation_status == "partially_reconciled"
            else "unreconciled"
        ),
    }
    row["lineage_completeness_score"] = lineage_completeness_score(row)
    return row


def _summarize_reconciliation_rows(
    rows: list[dict[str, Any]],
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    total = len(rows)
    returns = [
        float(row["realized_return_pct"])
        for row in rows
        if _coerce_float(row.get("realized_return_pct")) is not None
    ]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    holding_periods = [
        float(row["holding_period_days"])
        for row in rows
        if _coerce_float(row.get("holding_period_days")) is not None
    ]
    close_reason_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("close_reason") or "UNKNOWN")
        close_reason_counts[reason] = close_reason_counts.get(reason, 0) + 1
        status = str(row.get("reconciliation_status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1

    unresolved_count = sum(
        1 for row in rows if row.get("reconciliation_status") in SEVERE_RECONCILIATION_STATUSES
    )
    missing_mark_count = sum(1 for row in rows if "missing_mark" in row.get("data_gap_flags", []))
    stale_data_count = sum(1 for row in rows if "stale_mark_data" in row.get("data_gap_flags", []))
    invalidation_count = sum(1 for row in rows if bool(row.get("invalidation_flag")))
    stale_signal_count = sum(1 for row in rows if bool(row.get("stale_signal_flag")))
    evidence_strength = classify_evidence_strength(total)
    parameter_change_eligible, parameter_change_note = _parameter_change_note(total)

    best_trade = max(
        rows,
        key=lambda row: _coerce_float(row.get("realized_return_pct")) if _coerce_float(row.get("realized_return_pct")) is not None else -999999.0,
        default=None,
    )
    worst_trade = min(
        rows,
        key=lambda row: _coerce_float(row.get("realized_return_pct")) if _coerce_float(row.get("realized_return_pct")) is not None else 999999.0,
        default=None,
    )

    signal_to_fill_note = (
        "not_derivable_from_current_ledgers; decision rows do not carry an entry reference price."
    )
    summary = stamp_payload(
        {
            "artifact_kind": "paper_reconciliation_summary",
            "total_closed_paper_trades": total,
            "win_rate": round(len(winners) / total, 4) if total else None,
            "loser_rate": round(len(losers) / total, 4) if total else None,
            "average_realized_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
            "median_realized_return_pct": round(statistics.median(returns), 4) if returns else None,
            "average_winner_return_pct": round(sum(winners) / len(winners), 4) if winners else None,
            "average_loser_return_pct": round(sum(losers) / len(losers), 4) if losers else None,
            "expectancy_return_pct": (
                round(
                    ((len(winners) / total) * (sum(winners) / len(winners) if winners else 0.0))
                    + ((len(losers) / total) * (sum(losers) / len(losers) if losers else 0.0)),
                    4,
                )
                if total
                else None
            ),
            "best_trade": {
                "ticker": best_trade.get("ticker"),
                "close_id": best_trade.get("close_id"),
                "realized_return_pct": best_trade.get("realized_return_pct"),
            }
            if best_trade
            else None,
            "worst_trade": {
                "ticker": worst_trade.get("ticker"),
                "close_id": worst_trade.get("close_id"),
                "realized_return_pct": worst_trade.get("realized_return_pct"),
            }
            if worst_trade
            else None,
            "average_holding_period_days": round(sum(holding_periods) / len(holding_periods), 4)
            if holding_periods
            else None,
            "close_reason_distribution": close_reason_counts,
            "reconciliation_status_distribution": status_counts,
            "stale_signal_rate": round(stale_signal_count / total, 4) if total else None,
            "invalidation_rate": round(invalidation_count / total, 4) if total else None,
            "unresolved_data_gap_rate": round(unresolved_count / total, 4) if total else None,
            "sample_size_for_learning": total,
            "evidence_strength": evidence_strength,
            "parameter_change_eligible": parameter_change_eligible,
            "parameter_change_note": parameter_change_note,
            "leakage_diagnostics": {
                "signal_to_fill_drift_avg_bps": None,
                "signal_to_fill_drift_note": signal_to_fill_note,
                "fill_to_close_move_avg_pct": round(sum(returns) / len(returns), 4) if returns else None,
                "missing_mark_frequency": round(missing_mark_count / total, 4) if total else None,
                "unresolved_close_frequency": round(unresolved_count / total, 4) if total else None,
                "stale_data_frequency": round(stale_data_count / total, 4) if total else None,
            },
        },
        runtime_state=runtime_state,
    )
    return summary


def _apply_learning_annotations(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    eligible = bool(summary.get("parameter_change_eligible"))
    note = str(summary.get("parameter_change_note") or "")
    for row in rows:
        updated = dict(row)
        updated["parameter_change_eligible"] = eligible
        updated["parameter_change_note"] = note
        annotated.append(updated)
    return annotated


def run_paper_reconciliation(
    runtime_state: dict[str, Any] | None = None,
    close_ledger_path: Path | None = None,
    decision_ledger_path: Path | None = None,
    order_ledger_path: Path | None = None,
    fill_ledger_path: Path | None = None,
    feedback_ledger_path: Path | None = None,
    external_marks_path: Path | None = None,
    history_path: Path | None = None,
    summary_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    base_state = runtime_state or load_current_pipeline_state()
    deployment = build_deployment_permissions(base_state)
    if deployment["live_execution_enabled"] or deployment["can_emit_live_actions"]:
        raise ValueError("paper reconciliation refuses to run while live execution is enabled")

    closes_path = close_ledger_path or PAPER_CLOSE_LEDGER_PATH
    decisions_path = decision_ledger_path or PAPER_DECISION_LEDGER_PATH
    orders_path = order_ledger_path or PAPER_ORDER_LEDGER_PATH
    fills_path = fill_ledger_path or PAPER_FILL_LEDGER_PATH
    feedback_path = feedback_ledger_path or POST_TRADE_FEEDBACK_PATH
    marks_path = external_marks_path or EXTERNAL_MARKS_PATH
    history_target = history_path or PAPER_RECONCILIATION_HISTORY_PATH
    summary_target = summary_path or PAPER_RECONCILIATION_SUMMARY_PATH
    report_target = report_path or PAPER_RECONCILIATION_REPORT_PATH

    close_rows = _load_jsonl_rows(closes_path)
    decisions_by_id = _lookup_by_id(_load_jsonl_rows(decisions_path), "decision_id")
    orders_by_id = _lookup_by_id(_load_jsonl_rows(orders_path), "paper_order_id")
    fills_by_id = _lookup_by_id(_load_jsonl_rows(fills_path), "paper_fill_id")
    feedback_by_close_id = _lookup_by_id(_load_jsonl_rows(feedback_path), "close_id")
    marks_payload = load_json_file(marks_path, default={}) or {}
    if not isinstance(marks_payload, dict):
        marks_payload = {}
    marks_by_id, marks_by_ticker = _lookup_mark_rows(marks_payload)
    state = _runtime_state_with_external_marks(base_state, marks_payload)

    current_rows = [
        build_reconciliation_row(
            close_row=row,
            decisions_by_id=decisions_by_id,
            orders_by_id=orders_by_id,
            fills_by_id=fills_by_id,
            feedback_by_close_id=feedback_by_close_id,
            marks_by_id=marks_by_id,
            marks_by_ticker=marks_by_ticker,
            runtime_state=state,
        )
        for row in close_rows
    ]
    current_status_counts: dict[str, int] = {}
    for row in current_rows:
        status = str(row.get("reconciliation_status") or "UNKNOWN")
        current_status_counts[status] = current_status_counts.get(status, 0) + 1

    existing_rows = _load_jsonl_rows(history_target)
    existing_by_key = {_history_key(row): row for row in existing_rows}
    current_by_key = {_history_key(row): row for row in current_rows}
    new_keys = set(current_by_key) - set(existing_by_key)
    updated_keys = {key for key in current_by_key if key in existing_by_key and current_by_key[key] != existing_by_key[key]}

    merged_by_key = dict(existing_by_key)
    merged_by_key.update(current_by_key)
    merged_rows = list(merged_by_key.values())
    summary = _summarize_reconciliation_rows(merged_rows, runtime_state=state)
    annotated_rows = _apply_learning_annotations(merged_rows, summary)
    annotated_rows.sort(
        key=lambda row: (
            str(row.get("exit_time") or ""),
            str(row.get("close_id") or ""),
        )
    )
    _write_jsonl_atomic(history_target, annotated_rows)
    write_json_atomic(summary_target, summary, stamp=False)

    report = stamp_payload(
        {
            "artifact_kind": "paper_reconciliation_report",
            "processed_close_count": len(close_rows),
            "current_reconciled_row_count": len(current_rows),
            "new_history_rows": len(new_keys),
            "updated_history_rows": len(updated_keys),
            "history_row_count": len(annotated_rows),
            "current_status_distribution": current_status_counts,
            "evidence_strength": summary["evidence_strength"],
            "parameter_change_note": summary["parameter_change_note"],
            "history_path": repo_relative(history_target),
            "summary_path": repo_relative(summary_target),
            "external_marks_path": repo_relative(marks_path),
            "note": (
                "Reconciliation joins paper-simulated lineage with Yahoo-assisted marks "
                "and closes. It does not imply broker execution truth."
            ),
        },
        runtime_state=state,
    )
    write_json_atomic(report_target, report, stamp=False)

    return {
        "history_path": repo_relative(history_target),
        "summary_path": repo_relative(summary_target),
        "report_path": repo_relative(report_target),
        "history_row_count": len(annotated_rows),
        "new_history_rows": len(new_keys),
        "updated_history_rows": len(updated_keys),
        "evidence_strength": summary["evidence_strength"],
        "parameter_change_note": summary["parameter_change_note"],
        "operating_mode": report["operating_mode"],
        "truth_origin": report["truth_origin"],
    }


def format_reconciliation_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Paper Reconciliation",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"history_row_count={report['history_row_count']}",
            f"new_history_rows={report['new_history_rows']}",
            f"updated_history_rows={report['updated_history_rows']}",
            f"evidence_strength={report['evidence_strength']}",
            f"parameter_change_note={report['parameter_change_note']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Join paper closes, fills, Yahoo marks, and feedback into a cumulative reconciliation history."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    try:
        report = run_paper_reconciliation()
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")
    if args.summary:
        print(format_reconciliation_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
