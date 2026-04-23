from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from scripts.runtime_common import (
        ACTIVE_WORK_BLOCK_PATH,
        OPERATOR_BLOCK_EVENTS_PATH,
        OPERATOR_CONTROL_CONFIG_PATH,
        OPERATOR_PHASE_BALANCE_PATH,
        OPERATOR_PHASE_REPORT_PATH,
        OPERATOR_STATE_PATH,
        SIGNAL_GATE_SUMMARY_PATH,
        SIGNAL_KILL_LOG_PATH,
        STRUCTURAL_COVER_MAP_PATH,
        append_jsonl,
        get_run_id,
        load_json_file,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        ACTIVE_WORK_BLOCK_PATH,
        OPERATOR_BLOCK_EVENTS_PATH,
        OPERATOR_CONTROL_CONFIG_PATH,
        OPERATOR_PHASE_BALANCE_PATH,
        OPERATOR_PHASE_REPORT_PATH,
        OPERATOR_STATE_PATH,
        SIGNAL_GATE_SUMMARY_PATH,
        SIGNAL_KILL_LOG_PATH,
        STRUCTURAL_COVER_MAP_PATH,
        append_jsonl,
        get_run_id,
        load_json_file,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )


DEFAULT_CONFIG: dict[str, Any] = {
    "signal_admission_gate": {
        "relevance_floor": 0.55,
        "timeliness_max_age_days": 30.0,
        "allow_missing_timeliness": False,
        "actionable_statuses": ["EXECUTED_CLEAN"],
        "actionable_pre_entry_states": [
            "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
            "CLEAN_READY_PENDING_TRIGGER",
            "CLEAN_ENTRY_ELIGIBLE",
        ],
        "allow_promotable_watchlist": False,
        "allow_standard_watchlist": False,
        "allow_chaos_active_signals": False,
    },
    "closure_thresholds": {
        "accepted_evidence": [
            "output_exists",
            "validation_exists",
            "report_exists",
        ],
        "minimum_evidence_count": 1,
        "allow_manual_close": True,
    },
    "phase_balance": {
        "unfinished_closure_burden_cap": 5,
        "artifact_coverage_targets": [
            "operator_state",
            "signal_gate_summary",
            "block_logging",
            "structural_cover_map",
        ],
    },
}

_MANUAL_OPERATOR_STATE_FIELDS = (
    "active_objective",
    "active_task",
    "active_block_id",
    "operator_mode",
    "context_switch_count",
    "unfinished_closures",
    "baseline_score",
    "current_score",
    "peak_score",
    "recent_scores",
    "instability_reasons",
    "notes",
)

_ACTIVE_WORK_BLOCK_FIELDS = (
    "block_id",
    "block_type",
    "objective",
    "active_task",
    "success_metric",
    "time_boundary",
    "non_goals",
    "operator_mode",
    "status",
    "context_switch_count",
    "reopened_decision_count",
    "selection_started_at",
    "execution_started_at",
    "closed_at",
    "closure_result",
)

_VALID_CLOSURE_EVIDENCE_FIELDS = (
    "output_exists",
    "validation_exists",
    "report_exists",
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_operator_control_config(path: Path | None = None) -> dict[str, Any]:
    payload = load_json_file(path or OPERATOR_CONTROL_CONFIG_PATH, default={})
    if not isinstance(payload, dict):
        payload = {}
    return _deep_merge(DEFAULT_CONFIG, payload)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _safe_round(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _average(values: list[float]) -> float | None:
    return float(mean(values)) if values else None


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalize_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in (_text(value) for value in values) if item]


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_meaningful_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    return bool(value)


def _has_any_fields(payload: dict[str, Any], field_names: tuple[str, ...]) -> bool:
    return any(_has_meaningful_value(payload.get(field_name)) for field_name in field_names)


def _signal_row_key(row: dict[str, Any]) -> str:
    signal_id = _text(row.get("signal_id"))
    if signal_id:
        return f"signal_id:{signal_id}"
    return "|".join(
        [
            f"ticker:{_text(row.get('ticker')).upper()}",
            f"status:{_text(row.get('status'), 'UNKNOWN').upper()}",
            f"watchlist_tier:{_text(row.get('watchlist_tier'), 'NONE').upper()}",
            f"pre_entry_state:{_text(row.get('pre_entry_state'), 'NONE').upper()}",
            f"ce_score:{_text(_safe_round(_coerce_float(row.get('ce_score')), 3))}",
        ]
    )


def _resolve_closure_rule(
    closure_config: dict[str, Any] | None,
    block_type: str,
) -> dict[str, Any]:
    active_config = closure_config if isinstance(closure_config, dict) else {}

    # Current repo shape: one global evidence threshold across block types.
    if "accepted_evidence" in active_config:
        accepted_evidence = [
            field
            for field in _normalize_string_list(active_config.get("accepted_evidence"))
            if field in _VALID_CLOSURE_EVIDENCE_FIELDS
        ]
        if not accepted_evidence:
            accepted_evidence = list(_VALID_CLOSURE_EVIDENCE_FIELDS)
        return {
            "accepted_evidence": accepted_evidence,
            "minimum_evidence_count": max(
                1,
                _coerce_int(active_config.get("minimum_evidence_count"), 1),
            ),
            "allow_manual_close": _coerce_bool(
                active_config.get("allow_manual_close"),
                True,
            ),
            "rule_source": "global_closure_threshold",
        }

    # Backward compatibility for earlier per-block AND-style rules.
    legacy_rule = active_config.get(block_type) or active_config.get("default") or {}
    accepted_evidence: list[str] = []
    if _coerce_bool(legacy_rule.get("requires_output"), True):
        accepted_evidence.append("output_exists")
    if _coerce_bool(legacy_rule.get("requires_validation"), False):
        accepted_evidence.append("validation_exists")
    if _coerce_bool(legacy_rule.get("requires_report"), False):
        accepted_evidence.append("report_exists")
    if not accepted_evidence:
        accepted_evidence = list(_VALID_CLOSURE_EVIDENCE_FIELDS)
    return {
        "accepted_evidence": accepted_evidence,
        "minimum_evidence_count": len(accepted_evidence),
        "allow_manual_close": _coerce_bool(legacy_rule.get("allow_manual_close"), True),
        "rule_source": "legacy_block_rule",
    }


def _normalize_operator_state_payload(
    payload: dict[str, Any] | None,
    target: Path,
) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    recent_scores = data.get("recent_scores", [])
    if not isinstance(recent_scores, list):
        recent_scores = []
    normalized_recent_scores = [
        float(value)
        for value in (_coerce_float(item) for item in recent_scores)
        if value is not None
    ]

    instability_reasons = data.get("instability_reasons", [])
    if not isinstance(instability_reasons, list):
        instability_reasons = []

    note_value = data.get("notes")
    if isinstance(note_value, list):
        notes = [str(item).strip() for item in note_value if str(item).strip()]
    elif _text(note_value):
        notes = [_text(note_value)]
    else:
        notes = []

    configured = _has_any_fields(data, _MANUAL_OPERATOR_STATE_FIELDS)
    return {
        "configured": configured,
        "state_source": "manual_runtime_file" if configured else "manual_optional_absent",
        "active_objective": _text(data.get("active_objective")),
        "active_task": _text(data.get("active_task")),
        "active_block_id": _text(data.get("active_block_id")),
        "operator_mode": _text(data.get("operator_mode"), "unspecified").lower(),
        "context_switch_count": _coerce_int(data.get("context_switch_count"), 0),
        "unfinished_closures": _coerce_int(data.get("unfinished_closures"), 0),
        "baseline_score": _coerce_float(data.get("baseline_score")),
        "current_score": _coerce_float(data.get("current_score")),
        "peak_score": _coerce_float(data.get("peak_score")),
        "recent_scores": normalized_recent_scores,
        "instability_reasons": [str(item).strip() for item in instability_reasons if str(item).strip()],
        "notes": notes,
        "path": repo_relative(target),
    }


def _normalize_active_work_block_payload(
    payload: dict[str, Any] | None,
    target: Path,
) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    non_goals = data.get("non_goals", [])
    if not isinstance(non_goals, list):
        non_goals = []
    configured = _has_any_fields(data, _ACTIVE_WORK_BLOCK_FIELDS)
    return {
        "configured": configured,
        "path": repo_relative(target),
        "block_id": _text(data.get("block_id")),
        "block_type": _text(data.get("block_type"), "default").lower(),
        "objective": _text(data.get("objective")),
        "active_task": _text(data.get("active_task")),
        "success_metric": _text(data.get("success_metric")),
        "time_boundary": _text(data.get("time_boundary")),
        "non_goals": [str(item).strip() for item in non_goals if str(item).strip()],
        "operator_mode": _text(data.get("operator_mode"), "unspecified").lower(),
        "status": _text(data.get("status"), "inactive").lower(),
        "context_switch_count": _coerce_int(data.get("context_switch_count"), 0),
        "reopened_decision_count": _coerce_int(data.get("reopened_decision_count"), 0),
        "selection_started_at": _text(data.get("selection_started_at")),
        "execution_started_at": _text(data.get("execution_started_at")),
        "closed_at": _text(data.get("closed_at")),
        "closure_result": data.get("closure_result", {}),
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_signal_emergence_ts(signal_id: Any) -> datetime | None:
    text = _text(signal_id)
    if not text:
        return None
    parts = text.split("_")
    if len(parts) < 4:
        return None
    try:
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
    except (TypeError, ValueError):
        return None
    return datetime(year, month, day, tzinfo=timezone.utc)


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


def load_operator_state(path: Path | None = None) -> dict[str, Any]:
    target = path or OPERATOR_STATE_PATH
    payload = load_json_file(target, default={})
    return _normalize_operator_state_payload(payload, target)


def record_operator_state(
    *,
    active_objective: str | None = None,
    active_task: str | None = None,
    active_block_id: str | None = None,
    operator_mode: str | None = None,
    context_switch_count: int | None = None,
    unfinished_closures: int | None = None,
    baseline_score: float | None = None,
    current_score: float | None = None,
    peak_score: float | None = None,
    recent_scores: list[float] | None = None,
    instability_reasons: list[str] | None = None,
    notes: list[str] | None = None,
    path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    target = path or OPERATOR_STATE_PATH
    existing = load_json_file(target, default={})
    if not isinstance(existing, dict):
        existing = {}

    payload = dict(existing)
    updates = {
        "active_objective": active_objective,
        "active_task": active_task,
        "active_block_id": active_block_id,
        "operator_mode": operator_mode,
        "context_switch_count": context_switch_count,
        "unfinished_closures": unfinished_closures,
        "baseline_score": baseline_score,
        "current_score": current_score,
        "peak_score": peak_score,
    }
    for key, value in updates.items():
        if value is not None:
            payload[key] = value

    if recent_scores is not None:
        payload["recent_scores"] = [float(item) for item in recent_scores]
    if instability_reasons is not None:
        payload["instability_reasons"] = [str(item).strip() for item in instability_reasons if str(item).strip()]
    if notes is not None:
        payload["notes"] = [str(item).strip() for item in notes if str(item).strip()]

    normalized_payload = _normalize_operator_state_payload(payload, target)
    if not normalized_payload["configured"]:
        return normalized_payload

    payload["artifact_kind"] = "operator_state"
    payload["mode_honesty"] = "manual_optional_input"
    payload["updated_at"] = utc_timestamp()

    if write_runtime:
        write_json_atomic(target, payload)
        return load_operator_state(target)
    return normalized_payload


def summarize_baseline_vs_peak(operator_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = operator_state if isinstance(operator_state, dict) else load_operator_state()
    baseline = _coerce_float(state.get("baseline_score"))
    current = _coerce_float(state.get("current_score"))
    peak = _coerce_float(state.get("peak_score"))
    recent_scores = state.get("recent_scores", [])
    if not isinstance(recent_scores, list):
        recent_scores = []
    numeric_recent_scores = [
        float(value)
        for value in (_coerce_float(item) for item in recent_scores)
        if value is not None
    ]

    spread = None
    if baseline is not None and peak is not None:
        spread = peak - baseline

    volatility = None
    if len(numeric_recent_scores) >= 2:
        volatility = max(numeric_recent_scores) - min(numeric_recent_scores)

    if baseline is None and current is None and peak is None:
        state_name = "manual_scores_absent"
    elif current is not None and peak is not None and current >= peak:
        state_name = "at_recent_peak"
    elif current is not None and baseline is not None and current < baseline:
        state_name = "below_baseline"
    else:
        state_name = "between_baseline_and_peak"

    return {
        "state": state_name,
        "baseline_score": _safe_round(baseline),
        "current_score": _safe_round(current),
        "peak_score": _safe_round(peak),
        "current_minus_baseline": _safe_round(
            current - baseline if current is not None and baseline is not None else None
        ),
        "peak_minus_current": _safe_round(
            peak - current if peak is not None and current is not None else None
        ),
        "spread": _safe_round(spread),
        "volatility": _safe_round(volatility),
        "recent_scores": [_safe_round(item) for item in numeric_recent_scores],
        "manual_only": True,
        "note": "Baseline, current, peak, and recent scores remain manual unless the operator logs them.",
    }


def evaluate_signal_admission(
    signal_row: dict[str, Any],
    *,
    operator_state: dict[str, Any] | None = None,
    as_of: datetime | None = None,
    config: dict[str, Any] | None = None,
    source: str = "runtime_state",
) -> dict[str, Any]:
    active_config = config or load_operator_control_config()
    gate_config = active_config["signal_admission_gate"]
    row = signal_row if isinstance(signal_row, dict) else {}
    state = operator_state if isinstance(operator_state, dict) else load_operator_state()

    ticker = _text(row.get("ticker")).upper()
    signal_id = _text(row.get("signal_id"))
    status = _text(row.get("status"), "UNKNOWN").upper()
    watchlist_tier = _text(row.get("watchlist_tier"), "NONE").upper()
    pre_entry_state = _text(row.get("pre_entry_state"), "NONE").upper()
    ce_score = _coerce_float(row.get("ce_score"))

    relevance_floor = float(gate_config.get("relevance_floor", 0.55))
    if ce_score is None:
        relevance_passed = False
        relevance_reason = "ce_score_unavailable"
    else:
        relevance_passed = ce_score >= relevance_floor
        relevance_reason = (
            "ce_score_meets_floor"
            if relevance_passed
            else f"ce_score_below_floor_{ce_score:.3f}<{relevance_floor:.3f}"
        )

    actionable_statuses = {
        _text(item).upper() for item in gate_config.get("actionable_statuses", [])
    }
    actionable_pre_entry_states = {
        _text(item).upper() for item in gate_config.get("actionable_pre_entry_states", [])
    }

    actionability_passed = False
    actionability_source = "none"
    if status in actionable_statuses:
        actionability_passed = True
        actionability_source = f"status:{status}"
    elif pre_entry_state in actionable_pre_entry_states:
        actionability_passed = True
        actionability_source = f"pre_entry_state:{pre_entry_state}"
    elif (
        _coerce_bool(gate_config.get("allow_promotable_watchlist"), False)
        and watchlist_tier == "PROMOTABLE"
    ):
        actionability_passed = True
        actionability_source = "watchlist_tier_shortcut:PROMOTABLE"
    elif (
        _coerce_bool(gate_config.get("allow_standard_watchlist"), False)
        and watchlist_tier == "STANDARD"
    ):
        actionability_passed = True
        actionability_source = "watchlist_tier_shortcut:STANDARD"
    elif (
        _coerce_bool(gate_config.get("allow_chaos_active_signals"), False)
        and status == "EXECUTED_CHAOS"
    ):
        actionability_passed = True
        actionability_source = "status_shortcut:EXECUTED_CHAOS"

    actionability_reason = (
        f"actionable_via_{actionability_source}"
        if actionability_passed
        else "not_actionable_for_refinement"
    )

    emergence_ts = _parse_signal_emergence_ts(signal_id)
    measurement_ts = as_of or datetime.now(timezone.utc)
    signal_age_days = None
    if emergence_ts is not None:
        signal_age_days = max(0.0, (measurement_ts - emergence_ts).total_seconds() / 86400.0)
    allow_missing_timeliness = _coerce_bool(
        gate_config.get("allow_missing_timeliness"),
        False,
    )
    timeliness_max_age_days = float(gate_config.get("timeliness_max_age_days", 30.0))
    if signal_age_days is None:
        timeliness_passed = allow_missing_timeliness
        timeliness_reason = (
            "timeliness_unavailable_but_allowed"
            if timeliness_passed
            else "timeliness_unavailable"
        )
    else:
        timeliness_passed = signal_age_days <= timeliness_max_age_days
        timeliness_reason = (
            "signal_within_timeliness_window"
            if timeliness_passed
            else f"signal_stale_{signal_age_days:.2f}d>{timeliness_max_age_days:.2f}d"
        )

    dimension_states = {
        "relevance": {
            "passed": relevance_passed,
            "observed_ce_score": _safe_round(ce_score),
            "floor": _safe_round(relevance_floor),
            "reason": relevance_reason,
        },
        "actionability": {
            "passed": actionability_passed,
            "status": status,
            "watchlist_tier": watchlist_tier,
            "pre_entry_state": pre_entry_state,
            "reason": actionability_reason,
        },
        "timeliness": {
            "passed": timeliness_passed,
            "signal_age_days": _safe_round(signal_age_days, 2),
            "max_age_days": _safe_round(timeliness_max_age_days, 2),
            "reason": timeliness_reason,
        },
    }
    rejection_dimensions = [
        name for name, details in dimension_states.items() if not details["passed"]
    ]
    rejection_reasons = [
        details["reason"] for details in dimension_states.values() if not details["passed"]
    ]
    dimension_product = int(relevance_passed) * int(actionability_passed) * int(timeliness_passed)
    admit = dimension_product == 1
    review_later = bool(
        not admit and relevance_passed and timeliness_passed and not actionability_passed
    )

    return {
        "row_key": _signal_row_key(row),
        "signal_id": signal_id,
        "ticker": ticker,
        "source": source,
        "status": status,
        "watchlist_tier": watchlist_tier,
        "pre_entry_state": pre_entry_state,
        "ce_score": _safe_round(ce_score),
        "signal_age_days": _safe_round(signal_age_days, 2),
        "objective_context": _text(state.get("active_objective")),
        "dimension_states": dimension_states,
        "dimension_product": dimension_product,
        "admit": admit,
        "rejection_dimensions": rejection_dimensions,
        "rejection_reasons": rejection_reasons,
        "review_later": review_later,
        "note": (
            "Signal admission is a hard gate over repo-visible proxies only: "
            "ce_score for relevance, explicit state fields for actionability, "
            "and signal_id-derived age for timeliness."
        ),
    }


def filter_admitted_signal_rows(
    rows: list[dict[str, Any]],
    gate_report: dict[str, Any],
) -> list[dict[str, Any]]:
    admitted_row_keys = set(gate_report.get("admitted_row_keys", []))
    admitted_signal_ids = set(gate_report.get("admitted_signal_ids", []))
    admitted_tickers = set(gate_report.get("admitted_tickers", []))
    admitted_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_key = _signal_row_key(row)
        signal_id = _text(row.get("signal_id"))
        ticker = _text(row.get("ticker")).upper()
        if admitted_row_keys:
            if row_key in admitted_row_keys:
                admitted_rows.append(row)
            continue
        if signal_id and signal_id in admitted_signal_ids:
            admitted_rows.append(row)
            continue
        if not signal_id and ticker in admitted_tickers:
            admitted_rows.append(row)
    return admitted_rows


def _persist_signal_kill_log(
    rejections: list[dict[str, Any]],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    target = path or SIGNAL_KILL_LOG_PATH
    existing_rows = _load_jsonl_rows(target)
    current_run_id = get_run_id()
    existing_keys = {
        (
            _text(row.get("run_id")),
            _text(row.get("row_key")),
            "|".join(sorted(_text(item) for item in row.get("rejection_dimensions", []))),
        )
        for row in existing_rows
        if _text(row.get("run_id")) == current_run_id
    }

    appended_count = 0
    for row in rejections:
        rejection_dimensions = [
            _text(item) for item in row.get("rejection_dimensions", []) if _text(item)
        ]
        dedupe_key = (
            current_run_id,
            _text(row.get("row_key")),
            "|".join(sorted(rejection_dimensions)),
        )
        if dedupe_key in existing_keys:
            continue
        entry = {
            "artifact_kind": "signal_kill_entry",
            "timestamp": utc_timestamp(),
            "row_key": _text(row.get("row_key")),
            "source": _text(row.get("source"), "runtime_state"),
            "signal_id": _text(row.get("signal_id")),
            "ticker": _text(row.get("ticker")).upper(),
            "status": _text(row.get("status")).upper(),
            "watchlist_tier": _text(row.get("watchlist_tier"), "NONE").upper(),
            "pre_entry_state": _text(row.get("pre_entry_state"), "NONE").upper(),
            "ce_score": _coerce_float(row.get("ce_score")),
            "signal_age_days": _coerce_float(row.get("signal_age_days")),
            "summary": (
                f"{_text(row.get('ticker')).upper()} "
                f"{_text(row.get('status')).upper()} "
                f"{_text(row.get('watchlist_tier'), 'NONE').upper()}"
            ).strip(),
            "signal_summary": (
                f"{_text(row.get('ticker')).upper()} "
                f"{_text(row.get('status')).upper()} "
                f"{_text(row.get('watchlist_tier'), 'NONE').upper()}"
            ).strip(),
            "rejection_dimensions": rejection_dimensions,
            "rejection_reasons": [
                _text(item) for item in row.get("rejection_reasons", []) if _text(item)
            ],
            "rejection_reason": " | ".join(
                _text(item) for item in row.get("rejection_reasons", []) if _text(item)
            ),
            "objective_context": _text(row.get("objective_context")),
            "review_later": bool(row.get("review_later", False)),
        }
        append_jsonl(target, entry)
        existing_keys.add(dedupe_key)
        appended_count += 1

    return {
        "path": repo_relative(target),
        "appended_count": appended_count,
    }


def build_signal_admission_report(
    runtime_state: dict[str, Any],
    *,
    operator_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    output_path: Path | None = None,
    kill_log_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    active_operator_state = (
        operator_state if isinstance(operator_state, dict) else load_operator_state()
    )
    config = load_operator_control_config(config_path)
    generated_at = datetime.now(timezone.utc)
    rows = state.get("per_signal_attribution", [])
    if not isinstance(rows, list):
        rows = []

    decisions: list[dict[str, Any]] = []
    admitted_ce_scores: list[float] = []
    rejected_ce_scores: list[float] = []
    reason_counter: Counter[str] = Counter()
    missing_relevance_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        decision = evaluate_signal_admission(
            row,
            operator_state=active_operator_state,
            as_of=generated_at,
            config=config,
            source=_text(state.get("source"), "runtime_state"),
        )
        decisions.append(decision)
        if decision["admit"]:
            if decision["ce_score"] is not None:
                admitted_ce_scores.append(float(decision["ce_score"]))
        else:
            if decision["ce_score"] is not None:
                rejected_ce_scores.append(float(decision["ce_score"]))
            for reason in decision["rejection_reasons"]:
                reason_counter[reason] += 1
        if decision["dimension_states"]["relevance"]["reason"] == "ce_score_unavailable":
            missing_relevance_count += 1

    admitted_decisions = [row for row in decisions if row["admit"]]
    rejected_decisions = [row for row in decisions if not row["admit"]]
    admitted_signal_ids = _unique_preserve_order(
        [row["signal_id"] for row in admitted_decisions if row["signal_id"]]
    )
    rejected_signal_ids = _unique_preserve_order(
        [row["signal_id"] for row in rejected_decisions if row["signal_id"]]
    )
    admitted_tickers = _unique_preserve_order(
        [row["ticker"] for row in admitted_decisions if row["ticker"]]
    )
    rejected_tickers = _unique_preserve_order(
        [row["ticker"] for row in rejected_decisions if row["ticker"]]
    )
    admitted_row_keys = _unique_preserve_order(
        [row["row_key"] for row in admitted_decisions if row["row_key"]]
    )
    rejected_row_keys = _unique_preserve_order(
        [row["row_key"] for row in rejected_decisions if row["row_key"]]
    )

    payload = {
        "artifact_kind": "signal_admission_gate_summary",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "mode": "hard_boolean_gate",
        "objective_context": _text(active_operator_state.get("active_objective")),
        "total_signals_considered": len(decisions),
        "admitted_count": len(admitted_decisions),
        "rejected_count": len(rejected_decisions),
        "admitted_ratio": _safe_round(
            (len(admitted_decisions) / len(decisions)) if decisions else None
        ),
        "rejected_ratio": _safe_round(
            (len(rejected_decisions) / len(decisions)) if decisions else None
        ),
        "average_admitted_ce_score": _safe_round(_average(admitted_ce_scores)),
        "average_rejected_ce_score": _safe_round(_average(rejected_ce_scores)),
        "admitted_ce_score_sample_size": len(admitted_ce_scores),
        "rejected_ce_score_sample_size": len(rejected_ce_scores),
        "missing_relevance_count": missing_relevance_count,
        "reason_counts": dict(sorted(reason_counter.items())),
        "admitted_row_keys": admitted_row_keys,
        "rejected_row_keys": rejected_row_keys,
        "admitted_signal_ids": admitted_signal_ids,
        "rejected_signal_ids": rejected_signal_ids,
        "admitted_tickers": admitted_tickers,
        "rejected_tickers": rejected_tickers,
        "signals": decisions,
        "note": (
            "Rejected signals are logged only from explicit gate failures. "
            "Missing relevance data remains missing and is not converted into a synthetic zero."
        ),
    }

    if write_runtime:
        kill_log_result = _persist_signal_kill_log(
            [row for row in decisions if not row["admit"]],
            path=kill_log_path,
        )
        payload["kill_log"] = kill_log_result
        write_json_atomic(output_path or SIGNAL_GATE_SUMMARY_PATH, payload)
    else:
        payload["kill_log"] = {
            "path": repo_relative(kill_log_path or SIGNAL_KILL_LOG_PATH),
            "appended_count": 0,
        }
    return payload


def load_active_work_block(path: Path | None = None) -> dict[str, Any]:
    target = path or ACTIVE_WORK_BLOCK_PATH
    payload = load_json_file(target, default={})
    return _normalize_active_work_block_payload(payload, target)


def _write_active_work_block(target: Path, payload: dict[str, Any], write_runtime: bool) -> None:
    if write_runtime:
        write_json_atomic(target, payload)


def start_work_block(
    *,
    objective: str,
    success_metric: str,
    time_boundary: str,
    non_goals: list[str] | None = None,
    active_task: str | None = None,
    operator_mode: str | None = None,
    block_type: str = "default",
    block_id: str | None = None,
    path: Path | None = None,
    events_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    target = path or ACTIVE_WORK_BLOCK_PATH
    resolved_block_id = _text(block_id) or (
        f"block_{get_run_id()}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    )
    payload = {
        "artifact_kind": "active_work_block",
        "mode_honesty": "manual_event_logged",
        "block_id": resolved_block_id,
        "block_type": _text(block_type, "default").lower(),
        "objective": _text(objective),
        "active_task": _text(active_task),
        "success_metric": _text(success_metric),
        "time_boundary": _text(time_boundary),
        "non_goals": [str(item).strip() for item in (non_goals or []) if str(item).strip()],
        "operator_mode": _text(operator_mode, "unspecified").lower(),
        "status": "selected",
        "context_switch_count": 0,
        "reopened_decision_count": 0,
        "selection_started_at": utc_timestamp(),
        "execution_started_at": None,
        "closed_at": None,
        "closure_result": {},
    }
    _write_active_work_block(target, payload, write_runtime=write_runtime)
    if write_runtime:
        append_jsonl(
            events_path or OPERATOR_BLOCK_EVENTS_PATH,
            {
                "artifact_kind": "operator_block_event",
                "timestamp": utc_timestamp(),
                "block_id": resolved_block_id,
                "event_type": "selected",
                "objective": payload["objective"],
                "active_task": payload["active_task"],
                "success_metric": payload["success_metric"],
                "time_boundary": payload["time_boundary"],
                "non_goals": payload["non_goals"],
            },
        )
        return load_active_work_block(target)
    return _normalize_active_work_block_payload(payload, target)


def record_work_block_event(
    *,
    event_type: str,
    reason: str | None = None,
    block_id: str | None = None,
    path: Path | None = None,
    events_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    target = path or ACTIVE_WORK_BLOCK_PATH
    active_block = load_json_file(target, default={})
    if not isinstance(active_block, dict):
        active_block = {}

    resolved_block_id = _text(block_id or active_block.get("block_id"))
    if not resolved_block_id:
        raise ValueError("block_id is required when no active work block exists")

    normalized_event_type = _text(event_type).lower()
    if normalized_event_type not in {
        "selected",
        "execution_started",
        "context_switch",
        "decision_reopened",
        "abandoned",
        "note",
    }:
        raise ValueError(f"unsupported work block event_type: {normalized_event_type}")

    active_block_id = _text(active_block.get("block_id"))
    if (
        active_block_id
        and block_id
        and active_block_id != resolved_block_id
        and normalized_event_type in {"execution_started", "context_switch", "decision_reopened", "abandoned"}
    ):
        raise ValueError("block_id does not match the active work block")

    if active_block.get("block_id") == resolved_block_id:
        if normalized_event_type == "execution_started":
            active_block["status"] = "executing"
            active_block["execution_started_at"] = active_block.get("execution_started_at") or utc_timestamp()
        elif normalized_event_type == "context_switch":
            active_block["context_switch_count"] = _coerce_int(
                active_block.get("context_switch_count"),
                0,
            ) + 1
        elif normalized_event_type == "decision_reopened":
            active_block["reopened_decision_count"] = _coerce_int(
                active_block.get("reopened_decision_count"),
                0,
            ) + 1
        elif normalized_event_type == "abandoned":
            active_block["status"] = "abandoned"
            active_block["closed_at"] = utc_timestamp()
        if write_runtime:
            write_json_atomic(target, active_block)

    event_row = {
        "artifact_kind": "operator_block_event",
        "timestamp": utc_timestamp(),
        "block_id": resolved_block_id,
        "event_type": normalized_event_type,
        "reason": _text(reason),
    }
    if write_runtime:
        append_jsonl(events_path or OPERATOR_BLOCK_EVENTS_PATH, event_row)
    return event_row


def evaluate_closure_threshold(
    *,
    block_type: str = "default",
    output_exists: bool = False,
    validation_exists: bool = False,
    report_exists: bool = False,
    manual_closed: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_config = config or load_operator_control_config()
    resolved_block_type = _text(block_type, "default").lower()
    closure_config = active_config.get("closure_thresholds", {})
    rule = _resolve_closure_rule(closure_config, resolved_block_type)

    checks = {
        "output_exists": bool(output_exists),
        "validation_exists": bool(validation_exists),
        "report_exists": bool(report_exists),
        "manual_closed": bool(manual_closed),
    }
    accepted_evidence = [
        field
        for field in rule.get("accepted_evidence", [])
        if field in _VALID_CLOSURE_EVIDENCE_FIELDS
    ]
    if not accepted_evidence:
        accepted_evidence = list(_VALID_CLOSURE_EVIDENCE_FIELDS)
    minimum_evidence_count = max(
        1,
        min(
            _coerce_int(rule.get("minimum_evidence_count"), 1),
            len(accepted_evidence),
        ),
    )
    evidence_found = [
        check_name for check_name in accepted_evidence if checks.get(check_name, False)
    ]
    missing_evidence = [
        check_name for check_name in accepted_evidence if check_name not in evidence_found
    ]
    closure_met = False
    if _coerce_bool(rule.get("allow_manual_close"), True) and checks["manual_closed"]:
        closure_met = True
    elif len(evidence_found) >= minimum_evidence_count:
        closure_met = True

    return {
        "block_type": resolved_block_type,
        "closure_met": closure_met,
        "accepted_evidence": accepted_evidence,
        "minimum_evidence_count": minimum_evidence_count,
        "evidence_found": evidence_found,
        "required_checks": accepted_evidence,
        "checks": checks,
        "missing_evidence": missing_evidence,
        "missing_requirements": missing_evidence,
        "rule_source": _text(rule.get("rule_source"), "global_closure_threshold"),
        "closure_mode": (
            "manual_override" if checks["manual_closed"] and closure_met else "evidence_based"
        ),
        "note": (
            "Closure is explicit and transparent. The engine only checks logged evidence and "
            "does not infer completeness. In the current repo default, any one of "
            "output_exists, validation_exists, or report_exists is enough to close a block."
        ),
    }


def close_work_block(
    *,
    output_exists: bool = False,
    validation_exists: bool = False,
    report_exists: bool = False,
    manual_closed: bool = False,
    abandoned: bool = False,
    reason: str | None = None,
    block_id: str | None = None,
    path: Path | None = None,
    events_path: Path | None = None,
    config_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    target = path or ACTIVE_WORK_BLOCK_PATH
    payload = load_json_file(target, default={})
    if not isinstance(payload, dict):
        payload = {}

    resolved_block_id = _text(block_id or payload.get("block_id"))
    if not resolved_block_id:
        raise ValueError("block_id is required when no active work block exists")
    active_block_id = _text(payload.get("block_id"))
    if active_block_id and block_id and active_block_id != resolved_block_id:
        raise ValueError("block_id does not match the active work block")

    block_type = _text(payload.get("block_type"), "default")
    closure_result = evaluate_closure_threshold(
        block_type=block_type,
        output_exists=output_exists,
        validation_exists=validation_exists,
        report_exists=report_exists,
        manual_closed=manual_closed,
        config=load_operator_control_config(config_path),
    )
    payload["closure_result"] = closure_result
    payload["closed_at"] = utc_timestamp()
    if abandoned:
        payload["status"] = "abandoned"
    elif closure_result["closure_met"]:
        payload["status"] = "closed"
    else:
        payload["status"] = "closure_incomplete"

    if write_runtime:
        write_json_atomic(target, payload)
        append_jsonl(
            events_path or OPERATOR_BLOCK_EVENTS_PATH,
            {
                "artifact_kind": "operator_block_event",
                "timestamp": utc_timestamp(),
                "block_id": resolved_block_id,
                "event_type": "closed" if closure_result["closure_met"] and not abandoned else (
                    "abandoned" if abandoned else "closure_failed"
                ),
                "reason": _text(reason),
                "closure_result": closure_result,
            },
        )
        return load_active_work_block(target)
    return _normalize_active_work_block_payload(payload, target)


def build_work_block_summary(
    *,
    events_path: Path | None = None,
    active_block_path: Path | None = None,
) -> dict[str, Any]:
    rows = _load_jsonl_rows(events_path or OPERATOR_BLOCK_EVENTS_PATH)
    active_block = load_active_work_block(active_block_path)
    block_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        block_id = _text(row.get("block_id"))
        if block_id:
            block_events[block_id].append(row)

    selected_blocks = set()
    execution_blocks = set()
    closed_blocks = set()
    abandoned_blocks = set()
    mid_block_switches = 0
    reopened_decisions = 0
    for block_id, event_rows in block_events.items():
        event_types = {_text(row.get("event_type")).lower() for row in event_rows}
        if "selected" in event_types:
            selected_blocks.add(block_id)
        if event_types.intersection({"execution_started", "closed", "closure_failed", "abandoned"}):
            execution_blocks.add(block_id)
        if "closed" in event_types:
            closed_blocks.add(block_id)
        if "abandoned" in event_types:
            abandoned_blocks.add(block_id)
        mid_block_switches += sum(
            1 for row in event_rows if _text(row.get("event_type")).lower() == "context_switch"
        )
        reopened_decisions += sum(
            1
            for row in event_rows
            if _text(row.get("event_type")).lower() == "decision_reopened"
        )

    if active_block.get("configured") and active_block["block_id"]:
        selected_blocks.add(active_block["block_id"])
        if active_block["status"] in {"executing", "closed", "closure_incomplete", "abandoned"}:
            execution_blocks.add(active_block["block_id"])
        if active_block["status"] == "closed":
            closed_blocks.add(active_block["block_id"])
        if active_block["status"] == "abandoned":
            abandoned_blocks.add(active_block["block_id"])
        if active_block["status"] not in {"closed", "inactive"}:
            selected_blocks.add(active_block["block_id"])

    total_execution_blocks = len(execution_blocks)
    closed_block_count = len(closed_blocks)
    unfinished_closure_count = max(total_execution_blocks - closed_block_count, 0)

    return {
        "artifact_kind": "operator_block_summary",
        "event_log_path": repo_relative(events_path or OPERATOR_BLOCK_EVENTS_PATH),
        "active_block_path": repo_relative(active_block_path or ACTIVE_WORK_BLOCK_PATH),
        "selected_block_count": len(selected_blocks),
        "total_execution_blocks": total_execution_blocks,
        "closed_block_count": closed_block_count,
        "abandoned_block_count": len(abandoned_blocks),
        "unfinished_closure_count": unfinished_closure_count,
        "mid_block_switches": mid_block_switches,
        "reopened_decisions": reopened_decisions,
        "drift_rate": _safe_round(
            (mid_block_switches / total_execution_blocks) if total_execution_blocks else None
        ),
        "closure_ratio": _safe_round(
            (closed_block_count / total_execution_blocks) if total_execution_blocks else None
        ),
        "note": (
            "Drift and closure metrics are event-based only. If no execution blocks are logged, "
            "the rates stay null rather than implying observed behavior."
        ),
    }


def load_structural_cover_map(path: Path | None = None) -> dict[str, Any]:
    payload = load_json_file(path or STRUCTURAL_COVER_MAP_PATH, default={})
    if isinstance(payload, list):
        controls = [row for row in payload if isinstance(row, dict)]
        version = "STRUCTURAL_COVER_MAP_V1"
    elif isinstance(payload, dict):
        controls = payload.get("controls", [])
        if not isinstance(controls, list):
            controls = []
        controls = [row for row in controls if isinstance(row, dict)]
        version = _text(payload.get("version"), "STRUCTURAL_COVER_MAP_V1")
    else:
        controls = []
        version = "STRUCTURAL_COVER_MAP_V1"
    return {
        "version": version,
        "control_count": len(controls),
        "controls": controls,
        "path": repo_relative(path or STRUCTURAL_COVER_MAP_PATH),
    }


def _artifact_coverage(
    *,
    operator_state: dict[str, Any],
    gate_summary: dict[str, Any],
    block_summary: dict[str, Any],
    structural_cover_map: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    targets = config["phase_balance"].get("artifact_coverage_targets", [])
    if not isinstance(targets, list):
        targets = []

    states = {
        "operator_state": bool(operator_state.get("configured")),
        "signal_gate_summary": (
            gate_summary.get("artifact_kind") == "signal_admission_gate_summary"
            or "total_signals_considered" in gate_summary
        ),
        "block_logging": (
            block_summary.get("artifact_kind") == "operator_block_summary"
            or "selected_block_count" in block_summary
            or "total_execution_blocks" in block_summary
        ),
        "structural_cover_map": bool(structural_cover_map.get("control_count", 0)),
    }
    target_count = len(targets) if targets else len(states)
    present_count = sum(1 for key in targets or states if states.get(key, False))
    return {
        "states": states,
        "present_count": present_count,
        "target_count": target_count,
        "coverage_ratio": _safe_round((present_count / target_count) if target_count else 0.0),
    }


def _phase_summary(
    components: dict[str, float | None],
    *,
    minimum_component_count: int = 2,
) -> dict[str, Any]:
    values = [float(value) for value in components.values() if value is not None]
    observed_component_count = len(values)
    if observed_component_count < minimum_component_count:
        return {
            "score": None,
            "components": components,
            "observed_component_count": observed_component_count,
            "minimum_component_count_for_score": minimum_component_count,
            "score_state": "insufficient_evidence",
        }
    return {
        "score": round(sum(values) / len(values), 2),
        "components": components,
        "observed_component_count": observed_component_count,
        "minimum_component_count_for_score": minimum_component_count,
        "score_state": "observed_proxy_blend",
    }


def build_operator_control_report(
    *,
    operator_state_path: Path | None = None,
    gate_summary: dict[str, Any] | None = None,
    block_summary: dict[str, Any] | None = None,
    active_block_path: Path | None = None,
    structural_cover_map_path: Path | None = None,
    test_status: dict[str, Any] | None = None,
    config_path: Path | None = None,
    output_balance_path: Path | None = None,
    output_report_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    config = load_operator_control_config(config_path)
    state = load_operator_state(operator_state_path)
    active_block = load_active_work_block(active_block_path)
    signal_gate_summary = (
        gate_summary
        if isinstance(gate_summary, dict)
        else load_json_file(SIGNAL_GATE_SUMMARY_PATH, default={}) or {}
    )
    if not isinstance(signal_gate_summary, dict):
        signal_gate_summary = {}
    drift_summary = (
        block_summary if isinstance(block_summary, dict) else build_work_block_summary()
    )
    structural_cover = load_structural_cover_map(structural_cover_map_path)
    baseline_peak = summarize_baseline_vs_peak(state)
    artifact_coverage = _artifact_coverage(
        operator_state=state,
        gate_summary=signal_gate_summary,
        block_summary=drift_summary,
        structural_cover_map=structural_cover,
        config=config,
    )

    unfinished_burden_source = max(
        _coerce_int(state.get("unfinished_closures"), 0),
        _coerce_int(drift_summary.get("unfinished_closure_count"), 0),
    )
    burden_cap = max(
        _coerce_int(config["phase_balance"].get("unfinished_closure_burden_cap"), 5),
        1,
    )
    has_execution_blocks = _coerce_int(drift_summary.get("total_execution_blocks"), 0) > 0
    has_gate_data = _coerce_int(signal_gate_summary.get("total_signals_considered"), 0) > 0
    has_unfinished_burden_data = has_execution_blocks or bool(state.get("configured")) or unfinished_burden_source > 0
    phase_1_components = {
        "drift_inverse": (
            _safe_round(1.0 - float(drift_summary.get("drift_rate", 0.0)))
            if has_execution_blocks
            else None
        ),
        "closure_ratio": (
            _coerce_float(drift_summary.get("closure_ratio")) if has_execution_blocks else None
        ),
        "unfinished_burden_inverse": (
            _safe_round(max(0.0, 1.0 - (unfinished_burden_source / burden_cap)))
            if has_unfinished_burden_data
            else None
        ),
    }
    phase_2_components = {
        "reject_rate": (
            _coerce_float(signal_gate_summary.get("rejected_ratio")) if has_gate_data else None
        ),
        "average_admitted_ce_score": (
            _coerce_float(signal_gate_summary.get("average_admitted_ce_score"))
            if has_gate_data
            else None
        ),
    }
    test_score = None
    if isinstance(test_status, dict) and test_status.get("passed") is True:
        test_score = 1.0
    elif isinstance(test_status, dict) and test_status.get("passed") is False:
        test_score = 0.0
    phase_3_components = {
        "closure_ratio": (
            _coerce_float(drift_summary.get("closure_ratio")) if has_execution_blocks else None
        ),
        "test_status": test_score,
        "artifact_coverage": _coerce_float(artifact_coverage.get("coverage_ratio")),
    }
    phase_balance = {
        "phase_1_self_alignment": _phase_summary(phase_1_components),
        "phase_2_selective_expansion": _phase_summary(phase_2_components),
        "phase_3_system_building": _phase_summary(phase_3_components),
        "note": (
            "Phase scores are transparent proxy blends over logged drift, closure, "
            "gate behavior, tests, and artifact coverage. A phase score stays null unless "
            "at least two observable components are present."
        ),
    }

    if active_block.get("configured") and active_block.get("objective"):
        header_source = "active_work_block"
    elif state.get("configured") and state.get("active_objective"):
        header_source = "operator_state"
    else:
        header_source = "absent"

    top_down_constraint_header = {
        "active_block_id": active_block.get("block_id"),
        "objective": active_block.get("objective") or state.get("active_objective"),
        "active_task": active_block.get("active_task") or state.get("active_task"),
        "success_metric": active_block.get("success_metric"),
        "time_boundary": active_block.get("time_boundary"),
        "non_goals": active_block.get("non_goals", []),
        "status": active_block.get("status"),
        "header_source": header_source,
        "manual_only": True,
        "note": (
            "This header is logged only when the operator explicitly opens a work block "
            "or writes operator_state metadata."
        ),
    }

    report = {
        "artifact_kind": "operator_control_report",
        "manual_operator_state": state,
        "top_down_constraint_header": top_down_constraint_header,
        "signal_admission_gate": signal_gate_summary,
        "drift_monitor": drift_summary,
        "closure_engine": {
            "active_block": active_block,
            "active_closure_result": active_block.get("closure_result", {}),
        },
        "baseline_vs_peak": baseline_peak,
        "phase_balance": phase_balance,
        "artifact_coverage": artifact_coverage,
        "structural_cover_map": structural_cover,
        "note": (
            "Operator control remains manual or event-driven unless an explicit runtime source exists. "
            "No operator-state inference is performed."
        ),
    }

    if write_runtime:
        balance_payload = {
            "artifact_kind": "operator_phase_balance",
            "phase_balance": phase_balance,
            "artifact_coverage": artifact_coverage,
        }
        write_json_atomic(output_balance_path or OPERATOR_PHASE_BALANCE_PATH, balance_payload)
        write_json_atomic(output_report_path or OPERATOR_PHASE_REPORT_PATH, report)
    return report


def format_operator_control_summary(report: dict[str, Any]) -> str:
    gate = report.get("signal_admission_gate", {})
    drift = report.get("drift_monitor", {})
    phase_balance = report.get("phase_balance", {})
    phase_1 = phase_balance.get("phase_1_self_alignment", {})
    phase_2 = phase_balance.get("phase_2_selective_expansion", {})
    phase_3 = phase_balance.get("phase_3_system_building", {})
    header = report.get("top_down_constraint_header", {})
    return "\n".join(
        [
            "Operator Control",
            f"objective={header.get('objective') or 'NONE'}",
            f"active_task={header.get('active_task') or 'NONE'}",
            f"admitted_count={gate.get('admitted_count', 0)}",
            f"rejected_count={gate.get('rejected_count', 0)}",
            f"drift_rate={drift.get('drift_rate')}",
            f"closure_ratio={drift.get('closure_ratio')}",
            f"phase_1_score={phase_1.get('score')}",
            f"phase_2_score={phase_2.get('score')}",
            f"phase_3_score={phase_3.get('score')}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manual operator-control utilities for state, work blocks, gates, and phase reporting."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    state_parser = subparsers.add_parser("state", help="Write or update manual operator_state.json.")
    state_parser.add_argument("--active-objective", default=None)
    state_parser.add_argument("--active-task", default=None)
    state_parser.add_argument("--active-block-id", default=None)
    state_parser.add_argument("--operator-mode", default=None)
    state_parser.add_argument("--context-switch-count", type=int, default=None)
    state_parser.add_argument("--unfinished-closures", type=int, default=None)
    state_parser.add_argument("--baseline-score", type=float, default=None)
    state_parser.add_argument("--current-score", type=float, default=None)
    state_parser.add_argument("--peak-score", type=float, default=None)
    state_parser.add_argument("--recent-score", type=float, action="append", dest="recent_scores")
    state_parser.add_argument("--instability-reason", action="append", dest="instability_reasons")
    state_parser.add_argument("--note", action="append", dest="notes")

    start_parser = subparsers.add_parser("start-block", help="Open an active work block with a top-down constraint header.")
    start_parser.add_argument("--objective", required=True)
    start_parser.add_argument("--success-metric", required=True)
    start_parser.add_argument("--time-boundary", required=True)
    start_parser.add_argument("--non-goal", action="append", dest="non_goals")
    start_parser.add_argument("--active-task", default=None)
    start_parser.add_argument("--operator-mode", default=None)
    start_parser.add_argument("--block-type", default="default")
    start_parser.add_argument("--block-id", default=None)

    event_parser = subparsers.add_parser("log-event", help="Log a block event such as execution_started or context_switch.")
    event_parser.add_argument("--event-type", required=True)
    event_parser.add_argument("--block-id", default=None)
    event_parser.add_argument("--reason", default=None)

    close_parser = subparsers.add_parser("close-block", help="Evaluate closure and close the active work block.")
    close_parser.add_argument("--block-id", default=None)
    close_parser.add_argument("--output-exists", action="store_true")
    close_parser.add_argument("--validation-exists", action="store_true")
    close_parser.add_argument("--report-exists", action="store_true")
    close_parser.add_argument("--manual-closed", action="store_true")
    close_parser.add_argument("--abandoned", action="store_true")
    close_parser.add_argument("--reason", default=None)

    report_parser = subparsers.add_parser("report", help="Build the operator phase balance and report.")
    report_parser.add_argument("--write-runtime", action="store_true")

    mode_parser = parser.add_mutually_exclusive_group()
    mode_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode_parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    if args.command == "state":
        payload = record_operator_state(
            active_objective=args.active_objective,
            active_task=args.active_task,
            active_block_id=args.active_block_id,
            operator_mode=args.operator_mode,
            context_switch_count=args.context_switch_count,
            unfinished_closures=args.unfinished_closures,
            baseline_score=args.baseline_score,
            current_score=args.current_score,
            peak_score=args.peak_score,
            recent_scores=args.recent_scores,
            instability_reasons=args.instability_reasons,
            notes=args.notes,
            write_runtime=True,
        )
    elif args.command == "start-block":
        payload = start_work_block(
            objective=args.objective,
            success_metric=args.success_metric,
            time_boundary=args.time_boundary,
            non_goals=args.non_goals,
            active_task=args.active_task,
            operator_mode=args.operator_mode,
            block_type=args.block_type,
            block_id=args.block_id,
            write_runtime=True,
        )
    elif args.command == "log-event":
        payload = record_work_block_event(
            event_type=args.event_type,
            reason=args.reason,
            block_id=args.block_id,
            write_runtime=True,
        )
    elif args.command == "close-block":
        payload = close_work_block(
            block_id=args.block_id,
            output_exists=args.output_exists,
            validation_exists=args.validation_exists,
            report_exists=args.report_exists,
            manual_closed=args.manual_closed,
            abandoned=args.abandoned,
            reason=args.reason,
            write_runtime=True,
        )
    else:
        payload = build_operator_control_report(write_runtime=args.write_runtime)

    if args.summary:
        print(format_operator_control_summary(payload if isinstance(payload, dict) else {}))
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
