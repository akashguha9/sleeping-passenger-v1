from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.action_engine import build_action_report
    from scripts.paper_execution import close_paper_position
    from scripts.runtime_common import (
        EXTERNAL_MARKS_PATH,
        MODEL_UPGRADE_REPORT_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_FILL_LEDGER_PATH,
        PAPER_ORDER_LEDGER_PATH,
        PAPER_POSITIONS_PATH,
        PAPER_RETIREMENT_REPORT_PATH,
        POST_TRADE_FEEDBACK_PATH,
        build_deployment_permissions,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
        append_jsonl,
    )
    from scripts.yahoo_market_data_adapter import build_external_market_marks_report
except ModuleNotFoundError:
    from action_engine import build_action_report
    from paper_execution import close_paper_position
    from runtime_common import (
        EXTERNAL_MARKS_PATH,
        MODEL_UPGRADE_REPORT_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_FILL_LEDGER_PATH,
        PAPER_ORDER_LEDGER_PATH,
        PAPER_POSITIONS_PATH,
        PAPER_RETIREMENT_REPORT_PATH,
        POST_TRADE_FEEDBACK_PATH,
        build_deployment_permissions,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
        append_jsonl,
    )
    from yahoo_market_data_adapter import build_external_market_marks_report


DEFAULT_TARGET_RETURN_PCT = 3.0
DEFAULT_STOP_RETURN_PCT = -3.0
DEFAULT_STALE_SIGNAL_DAYS = 7
DEFAULT_STALE_BAND_PCT = 1.0
DEFAULT_INVALIDATED_RETURN_PCT = -1.5
DEFAULT_INVALIDATED_5D_PCT = -5.0
DEFAULT_MAX_RETIREMENTS = 2

REASON_PRIORITY = {
    "manual_rule_close": 0,
    "stop_hit": 1,
    "target_hit": 2,
    "invalidated_by_market_move": 3,
    "stale_signal_timeout": 4,
}


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
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


def _load_paper_positions_payload(path: Path | None = None) -> dict[str, Any]:
    payload = load_json_file(path or PAPER_POSITIONS_PATH, default={}) or {}
    if not isinstance(payload, dict):
        payload = {"positions": []}
    positions = payload.get("positions", [])
    if not isinstance(positions, list):
        positions = []
    payload["positions"] = [dict(row) for row in positions if isinstance(row, dict)]
    return payload


def _write_paper_positions_payload(
    payload: dict[str, Any],
    runtime_state: dict[str, Any],
    path: Path | None = None,
) -> None:
    rows = payload.get("positions", [])
    stamped = stamp_payload(
        {
            "artifact_kind": "paper_positions_ledger",
            "positions": rows,
            "open_position_count": sum(
                1 for row in rows if str(row.get("status") or "").upper() == "OPEN"
            ),
            "note": (
                "Open paper positions only. Latest marks may be sourced from Yahoo Finance "
                "for paper observation and retirement only."
            ),
        },
        runtime_state=runtime_state,
    )
    write_json_atomic(path or PAPER_POSITIONS_PATH, stamped, stamp=False)


def _paper_only_required(runtime_state: dict[str, Any]) -> None:
    deployment = build_deployment_permissions(runtime_state)
    if deployment["live_execution_enabled"] or deployment["can_emit_live_actions"]:
        raise ValueError("paper retirement refuses to run while live execution is enabled")
    if not deployment["paper_execution_enabled"]:
        raise ValueError("paper execution is disabled; enable PIPELINE_ENABLE_PAPER_EXECUTION first")


def _tracked_tickers(
    position_rows: list[dict[str, Any]],
    action_rows: list[dict[str, Any]],
) -> list[str]:
    tickers = {
        str(row.get("ticker") or "").upper()
        for row in position_rows + action_rows
        if str(row.get("ticker") or "").strip()
    }
    return sorted(tickers)


def _signal_lookup(runtime_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in runtime_state.get("per_signal_attribution", []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            mapping[ticker] = row
    return mapping


def _action_lookup(action_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in action_rows:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            mapping[ticker] = dict(row)
    return mapping


def _position_lookup(position_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in position_rows:
        ticker = str(row.get("ticker") or "").upper()
        if ticker and str(row.get("status") or "").upper() == "OPEN":
            mapping[ticker] = dict(row)
    return mapping


def _build_external_runtime_state(
    runtime_state: dict[str, Any],
    fetched_at: str,
    success_count: int,
) -> dict[str, Any]:
    state = dict(runtime_state)
    state["external_observation_active"] = success_count > 0
    state["external_observation_source"] = "yahoo_finance"
    state["external_observation_fetched_at"] = fetched_at
    return state


def _link_mark_rows(
    marks_report: dict[str, Any],
    position_rows: list[dict[str, Any]],
    action_rows: list[dict[str, Any]],
    runtime_state: dict[str, Any],
) -> None:
    signal_lookup = _signal_lookup(runtime_state)
    action_lookup = _action_lookup(action_rows)
    position_lookup = _position_lookup(position_rows)

    for row in marks_report.get("marks", []):
        ticker = str(row.get("ticker") or "").upper()
        signal_row = signal_lookup.get(ticker, {})
        action_row = action_lookup.get(ticker, {})
        position_row = position_lookup.get(ticker, {})

        tracking_roles: list[str] = []
        if position_row:
            tracking_roles.append("paper_position")
        if action_row:
            tracking_roles.append("paper_candidate")

        row["tracking_roles"] = tracking_roles
        row["signal_id"] = (
            position_row.get("signal_id")
            or signal_row.get("signal_id")
            or row.get("signal_id")
            or ""
        )
        row["position_id"] = position_row.get("position_id")
        row["decision_id"] = position_row.get("decision_id")
        row["paper_order_id"] = position_row.get("paper_order_id")
        row["paper_fill_id"] = position_row.get("paper_fill_id")
        row["candidate_action_type"] = action_row.get("action")
        row["candidate_priority_score"] = action_row.get("priority_score")


def _position_return_pct(position_row: dict[str, Any], exit_price: float | None) -> float | None:
    entry_price = _coerce_float(position_row.get("avg_entry_price"))
    qty = _coerce_float(position_row.get("qty"))
    if entry_price in {None, 0.0} or qty in {None, 0.0} or exit_price is None:
        return None
    side = str(position_row.get("side") or "").upper()
    realized = (exit_price - entry_price) if side != "SELL" else (entry_price - exit_price)
    return round((realized / entry_price) * 100.0, 4)


def _holding_period_days(position_row: dict[str, Any], observed_at: str | None) -> float | None:
    opened_at = _parse_iso_timestamp(position_row.get("opened_at"))
    observed = _parse_iso_timestamp(observed_at)
    if opened_at is None or observed is None:
        return None
    return round((observed - opened_at).total_seconds() / 86400.0, 3)


def evaluate_close_rule(
    position_row: dict[str, Any],
    mark_row: dict[str, Any],
    manual_close_targets: set[str] | None = None,
    target_return_pct: float = DEFAULT_TARGET_RETURN_PCT,
    stop_return_pct: float = DEFAULT_STOP_RETURN_PCT,
    stale_signal_days: int = DEFAULT_STALE_SIGNAL_DAYS,
    stale_band_pct: float = DEFAULT_STALE_BAND_PCT,
    invalidated_return_pct: float = DEFAULT_INVALIDATED_RETURN_PCT,
    invalidated_5d_pct: float = DEFAULT_INVALIDATED_5D_PCT,
) -> dict[str, Any]:
    ticker = str(position_row.get("ticker") or "").upper()
    position_id = str(position_row.get("position_id") or "").upper()
    manual_targets = {str(value).strip().upper() for value in (manual_close_targets or set())}
    if ticker in manual_targets or position_id in manual_targets:
        return {
            "eligible": True,
            "close_reason": "manual_rule_close",
            "thesis_state": "unresolved",
            "reason_note": "manual_close_targeted",
            "return_pct": _position_return_pct(position_row, _coerce_float(mark_row.get("last_price"))),
            "holding_period_days": _holding_period_days(position_row, mark_row.get("observed_at")),
        }

    if not bool(mark_row.get("ok")) or _coerce_float(mark_row.get("last_price")) is None:
        return {
            "eligible": False,
            "close_reason": "no_data_unresolved",
            "thesis_state": "unresolved",
            "reason_note": "no_external_price_available",
            "return_pct": None,
            "holding_period_days": _holding_period_days(position_row, mark_row.get("fetched_at")),
        }

    return_pct = _position_return_pct(position_row, _coerce_float(mark_row.get("last_price")))
    holding_days = _holding_period_days(position_row, mark_row.get("observed_at"))
    context_5d = _coerce_float(mark_row.get("context_5d_change_pct"))

    if return_pct is not None and return_pct <= stop_return_pct:
        return {
            "eligible": True,
            "close_reason": "stop_hit",
            "thesis_state": "invalidated",
            "reason_note": "return_pct_below_stop_threshold",
            "return_pct": return_pct,
            "holding_period_days": holding_days,
        }
    if return_pct is not None and return_pct >= target_return_pct:
        return {
            "eligible": True,
            "close_reason": "target_hit",
            "thesis_state": "confirmed",
            "reason_note": "return_pct_above_target_threshold",
            "return_pct": return_pct,
            "holding_period_days": holding_days,
        }
    if (
        holding_days is not None
        and holding_days >= stale_signal_days
        and return_pct is not None
        and abs(return_pct) <= stale_band_pct
    ):
        return {
            "eligible": True,
            "close_reason": "stale_signal_timeout",
            "thesis_state": "unresolved",
            "reason_note": "holding_period_exceeded_without_resolution",
            "return_pct": return_pct,
            "holding_period_days": holding_days,
        }
    if (
        return_pct is not None
        and return_pct <= invalidated_return_pct
        and context_5d is not None
        and context_5d <= invalidated_5d_pct
    ):
        return {
            "eligible": True,
            "close_reason": "invalidated_by_market_move",
            "thesis_state": "invalidated",
            "reason_note": "adverse_short_term_market_move",
            "return_pct": return_pct,
            "holding_period_days": holding_days,
        }
    return {
        "eligible": False,
        "close_reason": None,
        "thesis_state": "unresolved",
        "reason_note": "no_close_rule_triggered",
        "return_pct": return_pct,
        "holding_period_days": holding_days,
    }


def _unrealized_pnl(position_row: dict[str, Any], mark_price: float | None) -> float | None:
    entry_price = _coerce_float(position_row.get("avg_entry_price"))
    qty = _coerce_float(position_row.get("qty"))
    if entry_price is None or qty is None or mark_price is None:
        return None
    side = str(position_row.get("side") or "").upper()
    if side == "SELL":
        return round((entry_price - mark_price) * qty, 4)
    return round((mark_price - entry_price) * qty, 4)


def _update_open_position_marks(
    positions_payload: dict[str, Any],
    mark_lookup: dict[str, dict[str, Any]],
) -> None:
    for position_row in positions_payload.get("positions", []):
        ticker = str(position_row.get("ticker") or "").upper()
        mark_row = mark_lookup.get(ticker)
        if not mark_row:
            continue
        position_row["last_mark_source"] = mark_row.get("source_name")
        position_row["last_marked_at"] = mark_row.get("fetched_at")
        position_row["last_mark_staleness"] = mark_row.get("staleness_classification")
        position_row["last_mark_id"] = mark_row.get("mark_id")
        if bool(mark_row.get("ok")) and _coerce_float(mark_row.get("last_price")) is not None:
            mark_price = float(mark_row["last_price"])
            position_row["latest_mark"] = round(mark_price, 4)
            position_row["unrealized_pnl"] = _unrealized_pnl(position_row, mark_price)
            position_row["unrealized_return_pct"] = _position_return_pct(
                position_row, mark_price
            )
        else:
            position_row["mark_error_state"] = mark_row.get("retrieval_error") or "no_data"


def _load_decision_map(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("decision_id") or ""): row
        for row in _load_jsonl_rows(path or PAPER_DECISION_LEDGER_PATH)
        if str(row.get("decision_id") or "").strip()
    }


def _feedback_row(
    position_row: dict[str, Any],
    mark_row: dict[str, Any],
    close_report: dict[str, Any],
    evaluation: dict[str, Any],
    decision_lookup: dict[str, dict[str, Any]],
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    opening_decision = decision_lookup.get(str(position_row.get("decision_id") or ""), {})
    realized_return_pct = _position_return_pct(position_row, _coerce_float(close_report.get("exit_price")))
    conviction_score = _coerce_float(opening_decision.get("conviction_score"))
    if conviction_score is None:
        calibration_note = "no_opening_conviction_available"
    elif conviction_score >= 0.7 and (realized_return_pct or 0.0) > 0:
        calibration_note = "high_conviction_aligned_with_positive_outcome"
    elif conviction_score >= 0.7 and (realized_return_pct or 0.0) < 0:
        calibration_note = "high_conviction_missed_negative_outcome"
    else:
        calibration_note = "limited_conviction_signal"

    entry_visibility_context = {
        "light_score": opening_decision.get("entry_light_score"),
        "shadow_score": opening_decision.get("entry_shadow_score"),
        "moon_phase": opening_decision.get("entry_moon_phase"),
        "temporal_position": opening_decision.get("entry_temporal_position"),
        "crowding_score": opening_decision.get("entry_crowding_score"),
        "light_velocity": opening_decision.get("entry_light_velocity"),
        "shadow_velocity": opening_decision.get("entry_shadow_velocity"),
        "edge_context_score": opening_decision.get("entry_edge_context_score"),
        "full_moon_trap_flag": opening_decision.get("entry_full_moon_trap_flag"),
    }

    return stamp_payload(
        {
            "artifact_kind": "post_trade_feedback_entry",
            "feedback_id": f"feedback_{close_report['close_id']}",
            "signal_id": position_row.get("signal_id", ""),
            "ticker": position_row["ticker"],
            "decision_id": position_row.get("decision_id"),
            "paper_order_id": position_row.get("paper_order_id"),
            "paper_fill_id": position_row.get("paper_fill_id"),
            "position_id": position_row["position_id"],
            "close_id": close_report["close_id"],
            "mark_id": mark_row.get("mark_id"),
            "entry_context": {
                "avg_entry_price": position_row.get("avg_entry_price"),
                "opened_at": position_row.get("opened_at"),
                "qty": position_row.get("qty"),
                "side": position_row.get("side"),
                "opening_conviction_score": conviction_score,
                **entry_visibility_context,
            },
            "exit_context": {
                "exit_price": close_report.get("exit_price"),
                "closed_at": close_report.get("closed_at"),
                "close_reason": close_report.get("close_reason"),
                "source_name": mark_row.get("source_name"),
                "staleness_classification": mark_row.get("staleness_classification"),
            },
            "holding_period_days": evaluation.get("holding_period_days"),
            "realized_pnl": close_report.get("realized_pnl"),
            "realized_return_pct": realized_return_pct,
            "entry_light_score": entry_visibility_context["light_score"],
            "entry_shadow_score": entry_visibility_context["shadow_score"],
            "entry_moon_phase": entry_visibility_context["moon_phase"],
            "entry_temporal_position": entry_visibility_context["temporal_position"],
            "entry_crowding_score": entry_visibility_context["crowding_score"],
            "entry_light_velocity": entry_visibility_context["light_velocity"],
            "entry_shadow_velocity": entry_visibility_context["shadow_velocity"],
            "entry_edge_context_score": entry_visibility_context["edge_context_score"],
            "entry_full_moon_trap_flag": entry_visibility_context["full_moon_trap_flag"],
            "thesis_state": evaluation.get("thesis_state"),
            "source_quality_notes": (
                "Yahoo Finance external observation only; authority_bias_risk=medium, "
                "validation_dependency=high."
            ),
            "confidence_calibration_note": calibration_note,
        },
        runtime_state=runtime_state,
    )


def _summarize_feedback_rows(
    feedback_rows: list[dict[str, Any]],
    retirement_report: dict[str, Any],
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    returns = [
        float(row["realized_return_pct"])
        for row in feedback_rows
        if _coerce_float(row.get("realized_return_pct")) is not None
    ]
    winners = sum(1 for value in returns if value > 0)
    losers = sum(1 for value in returns if value < 0)

    best_trade = max(feedback_rows, key=lambda row: _coerce_float(row.get("realized_return_pct")) or -9999, default=None)
    worst_trade = min(feedback_rows, key=lambda row: _coerce_float(row.get("realized_return_pct")) or 9999, default=None)

    if not feedback_rows:
        systematic_issue = "no_retired_trades_in_batch"
    elif retirement_report["missing_data_count"] > 0:
        systematic_issue = "market_data_gaps_present"
    elif losers > winners:
        systematic_issue = "losses_outnumber_winners"
    elif retirement_report["close_reason_counts"].get("stale_signal_timeout", 0) > 0:
        systematic_issue = "stale_signal_exits_present"
    else:
        systematic_issue = "none_obvious"

    evidence_note = (
        "insufficient_evidence_for_parameter_change"
        if len(feedback_rows) < 5
        else "batch_large_enough_for_observation_only_not_parameter_change"
    )

    return stamp_payload(
        {
            "artifact_kind": "model_upgrade_report",
            "retired_paper_trades": len(feedback_rows),
            "winners": winners,
            "losers": losers,
            "average_realized_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
            "median_realized_return_pct": round(statistics.median(returns), 4) if returns else None,
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
            "close_reason_counts": retirement_report["close_reason_counts"],
            "stale_signal_count": retirement_report["close_reason_counts"].get("stale_signal_timeout", 0),
            "missing_data_count": retirement_report["missing_data_count"],
            "systematic_issue": systematic_issue,
            "paper_expectancy_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
            "parameter_change_note": evidence_note,
        },
        runtime_state=runtime_state,
    )


def retire_paper_trades(
    runtime_state: dict[str, Any] | None = None,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    manual_close_targets: set[str] | None = None,
    max_retirements: int = DEFAULT_MAX_RETIREMENTS,
    paper_positions_path: Path | None = None,
    external_marks_path: Path | None = None,
    retirement_report_path: Path | None = None,
    model_upgrade_report_path: Path | None = None,
    feedback_ledger_path: Path | None = None,
    decision_ledger_path: Path | None = None,
    order_ledger_path: Path | None = None,
    fill_ledger_path: Path | None = None,
    close_ledger_path: Path | None = None,
) -> dict[str, Any]:
    base_state = runtime_state or load_current_pipeline_state()
    _paper_only_required(base_state)

    positions_path = paper_positions_path or PAPER_POSITIONS_PATH
    marks_path = external_marks_path or EXTERNAL_MARKS_PATH
    retirement_path = retirement_report_path or PAPER_RETIREMENT_REPORT_PATH
    model_path = model_upgrade_report_path or MODEL_UPGRADE_REPORT_PATH
    feedback_path = feedback_ledger_path or POST_TRADE_FEEDBACK_PATH
    decisions_path = decision_ledger_path or PAPER_DECISION_LEDGER_PATH
    orders_path = order_ledger_path or PAPER_ORDER_LEDGER_PATH
    fills_path = fill_ledger_path or PAPER_FILL_LEDGER_PATH
    closes_path = close_ledger_path or PAPER_CLOSE_LEDGER_PATH

    positions_payload = _load_paper_positions_payload(positions_path)
    open_positions = [
        dict(row)
        for row in positions_payload.get("positions", [])
        if str(row.get("status") or "").upper() == "OPEN"
    ]
    action_report = build_action_report(runtime_state=base_state, write_runtime=False)
    action_rows = list(action_report.get("actions", []))
    tracked_tickers = _tracked_tickers(open_positions, action_rows)

    marks_report = build_external_market_marks_report(
        tickers=tracked_tickers,
        runtime_state=base_state,
        fetcher=fetcher,
    )
    _link_mark_rows(
        marks_report=marks_report,
        position_rows=open_positions,
        action_rows=action_rows,
        runtime_state=base_state,
    )
    write_json_atomic(marks_path, marks_report, stamp=False)

    external_state = _build_external_runtime_state(
        runtime_state=base_state,
        fetched_at=marks_report["fetched_at"],
        success_count=int(marks_report["success_count"]),
    )
    mark_lookup = {
        str(row.get("ticker") or "").upper(): row
        for row in marks_report.get("marks", [])
    }

    candidate_evaluations: list[dict[str, Any]] = []
    missing_data_count = 0
    for position_row in open_positions:
        mark_row = mark_lookup.get(str(position_row.get("ticker") or "").upper(), {})
        evaluation = evaluate_close_rule(
            position_row=position_row,
            mark_row=mark_row,
            manual_close_targets=manual_close_targets,
        )
        if evaluation["close_reason"] == "no_data_unresolved":
            missing_data_count += 1
        if evaluation["eligible"]:
            candidate_evaluations.append(
                {
                    "position_row": position_row,
                    "mark_row": mark_row,
                    "evaluation": evaluation,
                }
            )

    candidate_evaluations.sort(
        key=lambda item: (
            REASON_PRIORITY.get(item["evaluation"]["close_reason"] or "", 99),
            -abs(item["evaluation"]["return_pct"] or 0.0),
            -(item["evaluation"]["holding_period_days"] or 0.0),
            str(item["position_row"].get("ticker") or ""),
        )
    )
    selected = candidate_evaluations[: max(0, int(max_retirements))]

    decision_lookup = _load_decision_map(decisions_path)
    feedback_rows_written = 0
    retired_rows: list[dict[str, Any]] = []
    close_reason_counts: dict[str, int] = {}
    feedback_rows_batch: list[dict[str, Any]] = []

    for item in selected:
        position_row = item["position_row"]
        mark_row = item["mark_row"]
        evaluation = item["evaluation"]
        close_report = close_paper_position(
            position_id=str(position_row["position_id"]),
            exit_price=float(mark_row["last_price"]),
            close_reason=str(evaluation["close_reason"]),
            runtime_state=external_state,
            decision_ledger_path=decisions_path,
            order_ledger_path=orders_path,
            fill_ledger_path=fills_path,
            close_ledger_path=closes_path,
            paper_positions_path=positions_path,
            fill_source="yahoo_finance_mark",
            decision_source="paper_retirement_engine",
            close_context={
                "mark_id": mark_row.get("mark_id"),
                "mark_source_name": mark_row.get("source_name"),
                "mark_source_type": mark_row.get("source_type"),
                "mark_fetched_at": mark_row.get("fetched_at"),
                "mark_staleness_classification": mark_row.get("staleness_classification"),
            },
        )
        feedback_row = _feedback_row(
            position_row=position_row,
            mark_row=mark_row,
            close_report=close_report,
            evaluation=evaluation,
            decision_lookup=decision_lookup,
            runtime_state=external_state,
        )
        append_jsonl(feedback_path, feedback_row, stamp=False)
        feedback_rows_written += 1
        feedback_rows_batch.append(feedback_row)
        close_reason = str(evaluation["close_reason"])
        close_reason_counts[close_reason] = close_reason_counts.get(close_reason, 0) + 1
        retired_rows.append(
            {
                "ticker": position_row["ticker"],
                "position_id": position_row["position_id"],
                "close_id": close_report["close_id"],
                "mark_id": mark_row.get("mark_id"),
                "close_reason": close_reason,
                "realized_pnl": close_report["realized_pnl"],
                "realized_return_pct": feedback_row["realized_return_pct"],
            }
        )

    updated_positions_payload = _load_paper_positions_payload(positions_path)
    _update_open_position_marks(updated_positions_payload, mark_lookup)
    _write_paper_positions_payload(updated_positions_payload, external_state, positions_path)

    retirement_report = stamp_payload(
        {
            "artifact_kind": "paper_retirement_report",
            "fetched_at": marks_report["fetched_at"],
            "tracked_ticker_count": len(tracked_tickers),
            "open_position_count_before": len(open_positions),
            "open_position_count_after": updated_positions_payload.get("open_position_count", len(updated_positions_payload.get("positions", []))),
            "mark_success_count": marks_report["success_count"],
            "mark_failure_count": marks_report["failure_count"],
            "eligible_retirement_count": len(candidate_evaluations),
            "retired_trade_count": len(retired_rows),
            "skipped_due_to_limit_count": max(0, len(candidate_evaluations) - len(selected)),
            "missing_data_count": missing_data_count,
            "close_reason_counts": close_reason_counts,
            "retired_positions": retired_rows,
            "feedback_rows_written": feedback_rows_written,
            "note": (
                "Paper retirements use Yahoo Finance marks as external observation only. "
                "Closes remain paper-simulated and non-broker."
            ),
        },
        runtime_state=external_state,
    )
    write_json_atomic(retirement_path, retirement_report, stamp=False)

    model_upgrade_report = _summarize_feedback_rows(
        feedback_rows=feedback_rows_batch,
        retirement_report=retirement_report,
        runtime_state=external_state,
    )
    write_json_atomic(model_path, model_upgrade_report, stamp=False)

    return {
        "external_marks_path": repo_relative(marks_path),
        "retirement_report_path": repo_relative(retirement_path),
        "model_upgrade_report_path": repo_relative(model_path),
        "feedback_ledger_path": repo_relative(feedback_path),
        "retired_trade_count": len(retired_rows),
        "operating_mode": retirement_report["operating_mode"],
        "truth_origin": retirement_report["truth_origin"],
        "close_reason_counts": close_reason_counts,
        "retired_positions": retired_rows,
    }


def format_retirement_summary(report: dict[str, Any]) -> str:
    close_reasons = ", ".join(
        f"{key}={value}" for key, value in sorted(report["close_reason_counts"].items())
    ) or "NONE"
    return "\n".join(
        [
            "Paper Trade Retirement",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"retired_trade_count={report['retired_trade_count']}",
            f"close_reason_counts={close_reasons}",
            f"external_marks_path={report['external_marks_path']}",
            f"retirement_report_path={report['retirement_report_path']}",
            f"model_upgrade_report_path={report['model_upgrade_report_path']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Yahoo Finance marks, retire a few eligible paper trades, and write post-trade feedback artifacts."
    )
    parser.add_argument(
        "--max-retirements",
        type=int,
        default=DEFAULT_MAX_RETIREMENTS,
        help="Maximum number of eligible paper trades to retire in one run.",
    )
    parser.add_argument(
        "--manual-close",
        action="append",
        default=[],
        help="Force a manual_rule_close for a ticker or position_id. May be repeated.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    try:
        report = retire_paper_trades(
            manual_close_targets={str(value).strip().upper() for value in args.manual_close if str(value).strip()},
            max_retirements=int(args.max_retirements),
        )
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")

    if args.summary:
        print(format_retirement_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
