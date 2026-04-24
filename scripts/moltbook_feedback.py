from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        MOLTBOOK_FEEDBACK_CASES_PATH,
        MOLTBOOK_FEEDBACK_SUMMARY_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        MOLTBOOK_FEEDBACK_CASES_PATH,
        MOLTBOOK_FEEDBACK_SUMMARY_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


FEEDBACK_CLASSIFICATIONS = {
    "SUCCESS_VALID_SIGNAL",
    "FAIL_SIGNAL",
    "FAIL_TIMING",
    "FAIL_NOISE",
    "FAIL_REGIME",
    "FAIL_EXECUTION",
    "FAIL_DATA_QUALITY",
    "INCONCLUSIVE",
}
FAILURE_CLASSIFICATIONS = {
    "FAIL_SIGNAL",
    "FAIL_TIMING",
    "FAIL_NOISE",
    "FAIL_REGIME",
    "FAIL_EXECUTION",
    "FAIL_DATA_QUALITY",
}
REGIME_MARKERS = {
    "chaos",
    "high_volatility",
    "liquidity_stress",
    "macro_event",
    "shock",
    "event_cluster",
    "realm_bis",
    "executed_chaos",
    "chaos_entry",
}
EXECUTION_MARKERS = {
    "manual_rule_close",
    "override",
    "approval",
    "delay",
    "late_close",
    "rule_breach",
    "escalate_risk",
    "manual_exit",
}
LOW_QUALITY_TRUTH_ORIGINS = {"", "seeded", "synthetic", "placeholder", "unknown"}
CLASSIFICATION_ADJUSTMENTS = {
    "SUCCESS_VALID_SIGNAL": "Preserve this setup pattern but continue collecting paper evidence.",
    "FAIL_SIGNAL": "Reduce weight for this signal type until more validated outcomes appear.",
    "FAIL_TIMING": "Increase timing confirmation threshold before promotion.",
    "FAIL_NOISE": "Require stronger movement, volume, or persistence confirmation.",
    "FAIL_REGIME": "Add or strengthen regime compatibility gate.",
    "FAIL_EXECUTION": "Tighten operator checklist, approval discipline, or exit rules.",
    "FAIL_DATA_QUALITY": "Do not promote until timestamped external data quality improves.",
    "INCONCLUSIVE": "Improve metadata capture before using this case for learning.",
}


@dataclass(frozen=True)
class MoltbookFeedbackCase:
    case_id: str
    created_at_utc: str
    trade_id: str
    asset: str
    symbol: str
    side: str | None
    direction: str | None
    entry_time: str | None
    exit_time: str | None
    holding_period_seconds: float | None
    expected_outcome: str | None
    actual_outcome: str | None
    pnl: float | None
    return_pct: float | None
    classification: str
    classification_confidence: float
    primary_reason: str
    contributing_reasons: list[str]
    data_quality_flags: list[str]
    truth_origin: str
    operating_mode: str
    regime_context: dict[str, Any] = field(default_factory=dict)
    signal_context: dict[str, Any] = field(default_factory=dict)
    operator_override_context: dict[str, Any] = field(default_factory=dict)
    source_context: dict[str, Any] = field(default_factory=dict)
    suggested_adjustment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _holding_period_seconds(entry_time: Any, exit_time: Any, fallback_days: Any = None) -> float | None:
    entry_dt = _parse_iso_timestamp(entry_time)
    exit_dt = _parse_iso_timestamp(exit_time)
    if entry_dt is not None and exit_dt is not None:
        return round(max(0.0, (exit_dt - entry_dt).total_seconds()), 3)
    fallback = _coerce_float(fallback_days)
    if fallback is None:
        return None
    return round(max(0.0, fallback * 86400.0), 3)


def _sorted_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


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


def load_feedback_cases(path: Path | None = None) -> list[dict[str, Any]]:
    return _load_jsonl_rows(path or MOLTBOOK_FEEDBACK_CASES_PATH)


def append_feedback_case(case: MoltbookFeedbackCase | dict[str, Any], path: Path | None = None) -> None:
    target = path or MOLTBOOK_FEEDBACK_CASES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = case.to_dict() if isinstance(case, MoltbookFeedbackCase) else dict(case)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _write_feedback_cases(cases: list[MoltbookFeedbackCase], path: Path | None = None) -> None:
    target = path or MOLTBOOK_FEEDBACK_CASES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(case.to_dict(), separators=(",", ":")) for case in cases)
    if body:
        body += "\n"
    temp_path = target.with_suffix(target.suffix + ".tmp")
    temp_path.write_text(body, encoding="utf-8")
    temp_path.replace(target)


def write_feedback_summary(
    summary: dict[str, Any],
    path: Path | None = None,
    *,
    runtime_state: dict[str, Any] | None = None,
) -> None:
    stamped = stamp_payload(summary, runtime_state=runtime_state)
    write_json_atomic(path or MOLTBOOK_FEEDBACK_SUMMARY_PATH, stamped, stamp=False)


def _direction_from_side(side: str | None) -> str | None:
    normalized = _text(side).upper()
    if normalized == "BUY":
        return "LONG"
    if normalized == "SELL":
        return "SHORT"
    return None


def _expected_outcome(direction: str | None) -> str | None:
    if direction == "LONG":
        return "positive_return"
    if direction == "SHORT":
        return "negative_return"
    return None


def _actual_outcome(return_pct: float | None) -> str | None:
    if return_pct is None:
        return None
    if return_pct > 0.25:
        return "positive_return"
    if return_pct < -0.25:
        return "negative_return"
    return "flat_return"


def _signal_context_lookup(runtime_state: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    by_signal_id: dict[str, dict[str, Any]] = {}
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in state.get("per_signal_attribution", []):
        if not isinstance(row, dict):
            continue
        signal_id = _text(row.get("signal_id"))
        ticker = _text(row.get("ticker")).upper()
        if signal_id:
            by_signal_id[signal_id] = row
        if ticker:
            by_ticker[ticker] = row
    return by_signal_id, by_ticker


def _operator_override_lookup(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_signal_id: dict[str, dict[str, Any]] = {}
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        signal_id = _text(row.get("signal_id"))
        ticker = _text(row.get("ticker")).upper()
        if signal_id:
            by_signal_id[signal_id] = row
        if ticker:
            by_ticker[ticker] = row
    return by_signal_id, by_ticker


def _resolved_operator_override_context(
    row: dict[str, Any],
    operator_override_by_signal: dict[str, dict[str, Any]],
    operator_override_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    signal_id = _text(row.get("signal_id"))
    ticker = _text(row.get("ticker")).upper()
    override = (
        operator_override_by_signal.get(signal_id)
        or operator_override_by_ticker.get(ticker)
        or {}
    )
    if not override:
        return {}
    return {
        "override_id": override.get("override_id"),
        "suggested_action": override.get("suggested_action"),
        "override_action": override.get("override_action"),
        "override_classification": override.get("override_classification"),
        "risk_direction": override.get("risk_direction"),
        "manual_fpeg_state": override.get("manual_fpeg_state"),
        "confidence_source": override.get("confidence_source"),
    }


def _build_signal_context(
    row: dict[str, Any],
    signal_lookup_by_id: dict[str, dict[str, Any]],
    signal_lookup_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    signal_id = _text(row.get("signal_id"))
    ticker = _text(row.get("ticker")).upper()
    signal_row = signal_lookup_by_id.get(signal_id) or signal_lookup_by_ticker.get(ticker) or {}
    if not signal_row:
        return {}
    return {
        "signal_id": signal_row.get("signal_id"),
        "status": signal_row.get("status"),
        "blocker_attribution": signal_row.get("blocker_attribution"),
        "watchlist_tier": signal_row.get("watchlist_tier"),
        "pre_entry_state": signal_row.get("pre_entry_state"),
        "candidate_conversion_state": signal_row.get("candidate_conversion_state"),
        "ce_score": signal_row.get("ce_score"),
        "source_name": signal_row.get("source_name"),
        "signal_origin": signal_row.get("signal_origin"),
    }


def _build_regime_context(row: dict[str, Any], signal_context: dict[str, Any]) -> dict[str, Any]:
    markers: list[str] = []
    raw_values = [
        row.get("close_reason"),
        row.get("thesis_state"),
        signal_context.get("status"),
        signal_context.get("blocker_attribution"),
        signal_context.get("pre_entry_state"),
        signal_context.get("candidate_conversion_state"),
    ]
    for value in raw_values:
        lowered = _text(value).lower()
        for marker in REGIME_MARKERS:
            if marker in lowered:
                markers.append(marker)
    if _text(signal_context.get("status")).upper() == "EXECUTED_CHAOS":
        markers.append("executed_chaos")
    return {
        "markers": _sorted_unique(markers),
        "status": signal_context.get("status"),
        "blocker_attribution": signal_context.get("blocker_attribution"),
        "pre_entry_state": signal_context.get("pre_entry_state"),
    }


def _build_source_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "mark_source": row.get("mark_source"),
        "mark_staleness": row.get("mark_staleness"),
        "source_quality_note": row.get("source_quality_note"),
        "reconciliation_status": row.get("reconciliation_status"),
        "data_gap_flags": list(row.get("data_gap_flags", []))
        if isinstance(row.get("data_gap_flags"), list)
        else [],
    }


def _data_quality_flags(
    row: dict[str, Any],
    source_context: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    truth_origin = _text(row.get("truth_origin")).lower()
    operating_mode = _text(row.get("operating_mode")).lower()
    reconciliation_status = _text(row.get("reconciliation_status")).lower()
    mark_staleness = _text(source_context.get("mark_staleness")).lower()
    source_quality_note = _text(source_context.get("source_quality_note")).lower()

    if truth_origin in LOW_QUALITY_TRUTH_ORIGINS:
        flags.append(f"truth_origin_{truth_origin or 'missing'}")
    if operating_mode == "seeded":
        flags.append("operating_mode_seeded")
    for value in source_context.get("data_gap_flags", []):
        flags.append(str(value))
    if reconciliation_status in {"missing_mark", "data_gap_unresolved", "legacy_incomplete"}:
        flags.append(reconciliation_status)
    if mark_staleness in {"stale", "unknown", "clock_skew"}:
        flags.append(f"mark_staleness_{mark_staleness}")
    if "placeholder" in source_quality_note:
        flags.append("placeholder_source_note")
    if "validation_dependency=high" in source_quality_note:
        flags.append("validation_dependency_high")
    if "external observation only" in source_quality_note:
        flags.append("external_observation_only")
    return _sorted_unique(flags)


def _classification_payload(
    *,
    classification: str,
    confidence: float,
    primary_reason: str,
    contributing_reasons: list[str],
) -> tuple[str, float, str, list[str], str]:
    resolved = classification if classification in FEEDBACK_CLASSIFICATIONS else "INCONCLUSIVE"
    return (
        resolved,
        round(float(confidence), 3),
        primary_reason,
        _sorted_unique(contributing_reasons),
        CLASSIFICATION_ADJUSTMENTS[resolved],
    )


def _classify_case(
    row: dict[str, Any],
    *,
    signal_context: dict[str, Any],
    regime_context: dict[str, Any],
    operator_override_context: dict[str, Any],
    data_quality_flags: list[str],
) -> tuple[str, float, str, list[str], str]:
    realized_return = _coerce_float(row.get("realized_return_pct"))
    realized_pnl = _coerce_float(row.get("realized_pnl"))
    close_reason = _text(row.get("close_reason")).lower()
    thesis_state = _text(row.get("thesis_state")).lower()
    mfe = _coerce_float(row.get("mfe") or row.get("max_favorable_excursion_pct"))
    entry_delay_seconds = _coerce_float(row.get("entry_delay_seconds"))
    exit_delay_seconds = _coerce_float(row.get("exit_delay_seconds"))
    side = _text(row.get("side")).upper()
    unreliable_data = bool(data_quality_flags)
    reliable_outcome = realized_return is not None or realized_pnl is not None or bool(close_reason)

    regime_markers = list(regime_context.get("markers", []))
    override_classification = _text(operator_override_context.get("override_classification")).lower()
    override_action = _text(operator_override_context.get("override_action")).lower()
    strong_execution_cue = bool(
        override_classification
        or override_action
        or close_reason == "manual_rule_close"
    )
    strong_regime_cue = bool(regime_markers)

    if not reliable_outcome:
        if unreliable_data:
            return _classification_payload(
                classification="FAIL_DATA_QUALITY",
                confidence=0.5,
                primary_reason="No reliable outcome is available under low-quality paper evidence.",
                contributing_reasons=data_quality_flags,
            )
        return _classification_payload(
            classification="INCONCLUSIVE",
            confidence=0.3,
            primary_reason="Outcome evidence is insufficient for deterministic learning.",
            contributing_reasons=["outcome_missing"],
        )

    if close_reason in {"target_hit", "target_reached"} or (
        thesis_state in {"confirmed", "full"} and (realized_return or 0.0) >= 1.0
    ) or ((realized_return or 0.0) >= 2.0 and (realized_pnl or 0.0) > 0.0):
        reasons = ["positive_outcome"]
        if close_reason:
            reasons.append(f"close_reason_{close_reason}")
        if thesis_state:
            reasons.append(f"thesis_state_{thesis_state}")
        return _classification_payload(
            classification="SUCCESS_VALID_SIGNAL",
            confidence=0.9 if close_reason in {"target_hit", "target_reached"} or (realized_return or 0.0) >= 2.0 else 0.7,
            primary_reason="The paper outcome was directionally positive and met a success threshold.",
            contributing_reasons=reasons,
        )

    if (
        mfe is not None
        and realized_return is not None
        and mfe >= 2.0
        and realized_return <= 0.5
    ) or (
        (entry_delay_seconds is not None and entry_delay_seconds > 0)
        or (exit_delay_seconds is not None and exit_delay_seconds > 0)
    ) and (realized_return is None or realized_return <= 0.5):
        timing_reasons: list[str] = []
        if mfe is not None:
            timing_reasons.append("favorable_excursion_not_captured")
        if entry_delay_seconds is not None and entry_delay_seconds > 0:
            timing_reasons.append("entry_delay_recorded")
        if exit_delay_seconds is not None and exit_delay_seconds > 0:
            timing_reasons.append("exit_delay_recorded")
        return _classification_payload(
            classification="FAIL_TIMING",
            confidence=0.9 if mfe is not None else 0.7,
            primary_reason="The setup showed timing slippage or missed favorable excursion.",
            contributing_reasons=timing_reasons,
        )

    direction_known = side in {"BUY", "SELL"}
    contradicted_direction = False
    if direction_known and realized_return is not None:
        contradicted_direction = (
            (side == "BUY" and realized_return <= -2.0)
            or (side == "SELL" and realized_return >= 2.0)
        )
    if contradicted_direction and not strong_regime_cue and not strong_execution_cue:
        return _classification_payload(
            classification="FAIL_SIGNAL",
            confidence=0.9,
            primary_reason="The realized move materially contradicted the expected signal direction.",
            contributing_reasons=["directional_contradiction", f"side_{side.lower()}"],
        )

    if (
        realized_return is not None
        and abs(realized_return) <= 1.0
        and (close_reason == "stale_signal_timeout" or thesis_state in {"unresolved", "partial", ""})
    ):
        return _classification_payload(
            classification="FAIL_NOISE",
            confidence=0.7,
            primary_reason="The paper outcome was weak and did not show durable follow-through.",
            contributing_reasons=["flat_or_choppy_outcome", f"close_reason_{close_reason or 'none'}"],
        )

    if strong_regime_cue and realized_return is not None and realized_return < 0:
        return _classification_payload(
            classification="FAIL_REGIME",
            confidence=0.7,
            primary_reason="The setup failed under an incompatible regime or chaos context.",
            contributing_reasons=regime_markers or ["regime_marker_present"],
        )

    if strong_execution_cue and realized_return is not None and realized_return < 0:
        execution_reasons: list[str] = []
        if close_reason == "manual_rule_close":
            execution_reasons.append("manual_rule_close")
        if override_classification:
            execution_reasons.append(f"override_{override_classification}")
        if override_action:
            execution_reasons.append(f"override_action_{override_action}")
        return _classification_payload(
            classification="FAIL_EXECUTION",
            confidence=0.7,
            primary_reason="The idea was harmed by manual override or execution handling rather than clean signal quality.",
            contributing_reasons=execution_reasons or ["execution_issue_marker"],
        )

    if unreliable_data and (realized_return is None or close_reason in {"", "unknown"}):
        return _classification_payload(
            classification="FAIL_DATA_QUALITY",
            confidence=0.5,
            primary_reason="The case lacks enough reliable paper data to support learning.",
            contributing_reasons=data_quality_flags,
        )

    return _classification_payload(
        classification="INCONCLUSIVE",
        confidence=0.3 if unreliable_data else 0.5,
        primary_reason="The case does not yet contain enough deterministic evidence for a stronger label.",
        contributing_reasons=data_quality_flags or ["insufficient_distinguishing_evidence"],
    )


def build_feedback_case_from_reconciliation_row(
    row: dict[str, Any],
    *,
    runtime_state: dict[str, Any] | None = None,
    operator_override_by_signal: dict[str, dict[str, Any]] | None = None,
    operator_override_by_ticker: dict[str, dict[str, Any]] | None = None,
    generated_at_utc: str | None = None,
) -> MoltbookFeedbackCase:
    signal_lookup_by_id, signal_lookup_by_ticker = _signal_context_lookup(runtime_state)
    signal_context = _build_signal_context(row, signal_lookup_by_id, signal_lookup_by_ticker)
    regime_context = _build_regime_context(row, signal_context)
    operator_override_context = _resolved_operator_override_context(
        row,
        operator_override_by_signal or {},
        operator_override_by_ticker or {},
    )
    source_context = _build_source_context(row)
    data_quality_flags = _data_quality_flags(row, source_context)
    (
        classification,
        classification_confidence,
        primary_reason,
        contributing_reasons,
        suggested_adjustment,
    ) = _classify_case(
        row,
        signal_context=signal_context,
        regime_context=regime_context,
        operator_override_context=operator_override_context,
        data_quality_flags=data_quality_flags,
    )

    symbol = _text(row.get("ticker")).upper()
    trade_id = (
        _text(row.get("close_id"))
        or _text(row.get("position_id"))
        or _text(row.get("paper_fill_id"))
        or _text(row.get("signal_id"))
    )
    direction = _direction_from_side(_text(row.get("side")).upper() or None)
    expected_outcome = _expected_outcome(direction)
    return_pct = _coerce_float(row.get("realized_return_pct"))
    actual_outcome = _actual_outcome(return_pct)
    case_id = f"feedback_case_{trade_id}" if trade_id else f"feedback_case_{symbol.lower()}"
    created_at = generated_at_utc or utc_timestamp()

    return MoltbookFeedbackCase(
        case_id=case_id,
        created_at_utc=created_at,
        trade_id=trade_id,
        asset=symbol,
        symbol=symbol,
        side=_text(row.get("side")).upper() or None,
        direction=direction,
        entry_time=_text(row.get("entry_time")) or None,
        exit_time=_text(row.get("exit_time")) or None,
        holding_period_seconds=_holding_period_seconds(
            row.get("entry_time"),
            row.get("exit_time"),
            row.get("holding_period_days"),
        ),
        expected_outcome=expected_outcome,
        actual_outcome=actual_outcome,
        pnl=_safe_round(_coerce_float(row.get("realized_pnl"))),
        return_pct=_safe_round(return_pct),
        classification=classification,
        classification_confidence=classification_confidence,
        primary_reason=primary_reason,
        contributing_reasons=contributing_reasons,
        data_quality_flags=data_quality_flags,
        truth_origin=_text(row.get("truth_origin")) or "unknown",
        operating_mode=_text(row.get("operating_mode")) or "unknown",
        regime_context=regime_context,
        signal_context=signal_context,
        operator_override_context=operator_override_context,
        source_context=source_context,
        suggested_adjustment=suggested_adjustment,
    )


def build_feedback_cases_from_rows(
    rows: list[dict[str, Any]],
    *,
    runtime_state: dict[str, Any] | None = None,
    operator_overrides: list[dict[str, Any]] | None = None,
    generated_at_utc: str | None = None,
) -> list[MoltbookFeedbackCase]:
    override_by_signal, override_by_ticker = _operator_override_lookup(
        operator_overrides or []
    )
    generated_at = generated_at_utc or utc_timestamp()
    return [
        build_feedback_case_from_reconciliation_row(
            row,
            runtime_state=runtime_state,
            operator_override_by_signal=override_by_signal,
            operator_override_by_ticker=override_by_ticker,
            generated_at_utc=generated_at,
        )
        for row in rows
        if isinstance(row, dict)
    ]


#: Flags in data_quality_flags that indicate the learning evidence is
#: contaminated even when the case is classified as SUCCESS_VALID_SIGNAL.
#: These are substrings — any ``data_quality_flag`` containing one of these
#: tokens is treated as serious for contamination accounting.
SERIOUS_DATA_QUALITY_FLAG_TOKENS = (
    "truth_origin_seeded",
    "missing_feedback",
    "data_gap",
    "legacy_incomplete",
    "placeholder",
    "missing_mark",
)


def _case_has_serious_data_quality_flags(case: MoltbookFeedbackCase) -> bool:
    flags = getattr(case, "data_quality_flags", None) or []
    if not isinstance(flags, list):
        return False
    for raw_flag in flags:
        flag = str(raw_flag or "").strip().lower()
        if not flag:
            continue
        for token in SERIOUS_DATA_QUALITY_FLAG_TOKENS:
            if token in flag:
                return True
    return False


def build_feedback_summary(cases: list[MoltbookFeedbackCase]) -> dict[str, Any]:
    total_cases = len(cases)
    cases_by_classification: dict[str, int] = {}
    failure_by_asset: dict[str, int] = {}
    contaminated_case_count = 0
    contaminated_success_count = 0
    # Union of "explicit FAIL_DATA_QUALITY" and "contaminated" — used to
    # compute effective_data_quality_failure_ratio without double counting a
    # case that is both classified FAIL_DATA_QUALITY and carrying flags.
    compromised_case_count = 0
    for case in cases:
        cases_by_classification[case.classification] = (
            cases_by_classification.get(case.classification, 0) + 1
        )
        if case.classification in FAILURE_CLASSIFICATIONS:
            failure_by_asset[case.asset] = failure_by_asset.get(case.asset, 0) + 1
        is_contaminated = _case_has_serious_data_quality_flags(case)
        if is_contaminated:
            contaminated_case_count += 1
            if case.classification == "SUCCESS_VALID_SIGNAL":
                contaminated_success_count += 1
        if is_contaminated or case.classification == "FAIL_DATA_QUALITY":
            compromised_case_count += 1

    success_count = cases_by_classification.get("SUCCESS_VALID_SIGNAL", 0)
    failure_count = sum(
        cases_by_classification.get(label, 0) for label in FAILURE_CLASSIFICATIONS
    )
    top_failure_modes = sorted(
        [
            {"classification": label, "count": count}
            for label, count in cases_by_classification.items()
            if label in FAILURE_CLASSIFICATIONS
        ],
        key=lambda item: (-int(item["count"]), item["classification"]),
    )
    repeated_failure_modes = [
        item["classification"]
        for item in top_failure_modes
        if int(item["count"]) >= 2
    ]
    assets_with_repeated_failures = [
        {"asset": asset, "count": count}
        for asset, count in sorted(
            failure_by_asset.items(),
            key=lambda item: (-int(item[1]), item[0]),
        )
        if count >= 2
    ]
    timing_failure_ratio = round(
        cases_by_classification.get("FAIL_TIMING", 0) / total_cases, 4
    ) if total_cases else 0.0
    data_quality_failure_ratio = round(
        cases_by_classification.get("FAIL_DATA_QUALITY", 0) / total_cases, 4
    ) if total_cases else 0.0
    inconclusive_ratio = round(
        cases_by_classification.get("INCONCLUSIVE", 0) / total_cases, 4
    ) if total_cases else 0.0
    top_failure_mode = top_failure_modes[0]["classification"] if top_failure_modes else "NONE"
    dominant_failure_ratio = (
        round(int(top_failure_modes[0]["count"]) / total_cases, 4)
        if top_failure_modes and total_cases
        else 0.0
    )

    if total_cases == 0:
        feedback_learning_state = "NO_FEEDBACK"
    elif data_quality_failure_ratio >= 0.4 and total_cases >= 5:
        feedback_learning_state = "DATA_QUALITY_BLOCKED"
    elif dominant_failure_ratio >= 0.5 and total_cases >= 10:
        feedback_learning_state = "FAILURE_CLUSTER_DETECTED"
    elif total_cases < 10:
        feedback_learning_state = "INSUFFICIENT_FEEDBACK"
    else:
        feedback_learning_state = "LEARNING_ACTIVE"

    readiness_penalty = {
        "NO_FEEDBACK": 0.00,
        "INSUFFICIENT_FEEDBACK": 0.05,
        "LEARNING_ACTIVE": 0.15,
        "FAILURE_CLUSTER_DETECTED": 0.25,
        "DATA_QUALITY_BLOCKED": 0.35,
    }[feedback_learning_state]

    suggested_global_adjustments = _sorted_unique(
        [case.suggested_adjustment for case in cases if case.classification in FAILURE_CLASSIFICATIONS]
    )
    if feedback_learning_state == "NO_FEEDBACK":
        suggested_global_adjustments.insert(
            0,
            "Feedback loop has no evaluated paper cases yet.",
        )
    elif feedback_learning_state == "INSUFFICIENT_FEEDBACK":
        suggested_global_adjustments.append(
            "Collect more reconciled paper outcomes before upgrading readiness.",
        )
    elif feedback_learning_state == "DATA_QUALITY_BLOCKED":
        suggested_global_adjustments.insert(
            0,
            "Do not promote until timestamped external data quality improves.",
        )
    elif feedback_learning_state == "FAILURE_CLUSTER_DETECTED" and top_failure_mode != "NONE":
        suggested_global_adjustments.insert(
            0,
            f"Raise thresholds against the dominant failure mode: {top_failure_mode}.",
        )
    elif feedback_learning_state == "LEARNING_ACTIVE" and suggested_global_adjustments:
        suggested_global_adjustments.insert(
            0,
            f"Current strongest lesson: {suggested_global_adjustments[0]}",
        )
    suggested_global_adjustments = _sorted_unique(suggested_global_adjustments)

    raw_success_rate = round(success_count / total_cases, 4) if total_cases else 0.0
    clean_success_count = max(success_count - contaminated_success_count, 0)
    clean_success_rate = (
        round(clean_success_count / total_cases, 4) if total_cases else 0.0
    )
    contaminated_case_ratio = (
        round(contaminated_case_count / total_cases, 4) if total_cases else 0.0
    )
    # Contamination inflates the data-quality failure signal so that contaminated
    # successes reduce learning-evidence quality instead of being counted as
    # clean wins. The original FAIL_DATA_QUALITY ratio is kept for backwards
    # compatibility, and the new effective ratio is published separately.
    effective_data_quality_failure_ratio = (
        round(compromised_case_count / total_cases, 4)
        if total_cases
        else 0.0
    )
    learning_quality_warning = None
    if contaminated_success_count > 0:
        learning_quality_warning = (
            f"{contaminated_success_count} of {success_count} successes carry "
            "serious data-quality flags (seeded truth_origin, missing feedback, "
            "data gaps, legacy_incomplete). Treat clean_success_rate as the "
            "honest learning-evidence rate."
        )
    elif contaminated_case_count > 0 and total_cases >= 3:
        learning_quality_warning = (
            f"{contaminated_case_count} of {total_cases} feedback cases carry "
            "serious data-quality flags. Learning evidence is partially "
            "contaminated even though no successes are affected."
        )

    return {
        "artifact_kind": "moltbook_feedback_summary",
        "generated_at_utc": utc_timestamp(),
        "moltbook_feedback_available": True,
        "total_cases": total_cases,
        "feedback_cases_total": total_cases,
        "cases_by_classification": cases_by_classification,
        "success_rate": raw_success_rate,
        "feedback_success_rate": raw_success_rate,
        "raw_success_rate": raw_success_rate,
        "clean_success_rate": clean_success_rate,
        "clean_success_count": clean_success_count,
        "contaminated_case_count": contaminated_case_count,
        "contaminated_success_count": contaminated_success_count,
        "contaminated_case_ratio": contaminated_case_ratio,
        "failure_rate": round(failure_count / total_cases, 4) if total_cases else 0.0,
        "top_failure_modes": top_failure_modes,
        "repeated_failure_modes": repeated_failure_modes,
        "assets_with_repeated_failures": assets_with_repeated_failures,
        "timing_failure_ratio": timing_failure_ratio,
        "data_quality_failure_ratio": data_quality_failure_ratio,
        "effective_data_quality_failure_ratio": effective_data_quality_failure_ratio,
        "inconclusive_ratio": inconclusive_ratio,
        "feedback_top_failure_mode": top_failure_mode,
        "feedback_learning_state": feedback_learning_state,
        "feedback_readiness_penalty": round(readiness_penalty, 2),
        "readiness_penalty": round(readiness_penalty, 2),
        "learning_quality_warning": learning_quality_warning,
        "suggested_global_adjustments": suggested_global_adjustments,
        "suggested_feedback_adjustments": suggested_global_adjustments,
        "note": (
            "Feedback learning is deterministic and advisory-only. It summarizes paper outcome patterns "
            "without enabling live execution or claiming predictive certainty."
        ),
    }


def build_moltbook_feedback_report(
    runtime_state: dict[str, Any] | None = None,
    *,
    reconciliation_history_path: Path | None = None,
    feedback_cases_path: Path | None = None,
    feedback_summary_path: Path | None = None,
    operator_override_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    history_path = reconciliation_history_path or PAPER_RECONCILIATION_HISTORY_PATH
    cases_path = feedback_cases_path or MOLTBOOK_FEEDBACK_CASES_PATH
    summary_path = feedback_summary_path or MOLTBOOK_FEEDBACK_SUMMARY_PATH
    override_path = operator_override_path or OPERATOR_OVERRIDE_LEDGER_PATH

    reconciliation_rows = _load_jsonl_rows(history_path)
    operator_overrides = _load_jsonl_rows(override_path)
    cases = build_feedback_cases_from_rows(
        reconciliation_rows,
        runtime_state=runtime_state,
        operator_overrides=operator_overrides,
    )
    summary = build_feedback_summary(cases)
    summary["source_history_path"] = repo_relative(history_path)
    summary["feedback_cases_path"] = repo_relative(cases_path)
    summary["feedback_summary_path"] = repo_relative(summary_path)
    summary["operator_override_ledger_path"] = repo_relative(override_path)

    if write_runtime:
        _write_feedback_cases(cases, cases_path)
        write_feedback_summary(summary, summary_path, runtime_state=runtime_state)

    return summary
