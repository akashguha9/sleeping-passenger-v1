"""Signal decay + waste-load manager — pure, deterministic, advisory-only.

Engineering translation of the reflection's "signal half-life" and
"nuclear waste must decay/archive/teach" doctrine. The module models
how signal strength decays with age and classifies the cumulative
"waste load" of stale, duplicate, contradicted, and failed-thesis
debt across a batch.

Safety contract on every public output

    output["safety"]["advisory_status"]     == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]      == "LOCKED"
    output["safety"]["broker_api_called"]   is False
    output["safety"]["ai_execution_count"]  == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]         is False

Public API

    compute_decay_factor(age_hours, half_life_hours) -> float
    compute_signal_half_life(signal)                 -> dict
    classify_signal_waste(signal)                    -> dict
    summarize_waste_load(signals)                    -> dict
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

DEFAULT_HALF_LIFE_HOURS: dict[str, float] = {
    "official_filing": 168.0,
    "regulatory": 168.0,
    "filing": 168.0,
    "market_price": 24.0,
    "social_hype": 6.0,
    "social": 6.0,
    "news": 48.0,
    "polymarket": 24.0,
    "ai_summary": 12.0,
    "unknown": 24.0,
}

WASTE_CLASSES: tuple[str, ...] = (
    "active",
    "stale",
    "duplicate_echo",
    "contradicted",
    "failed_thesis_debt",
    "unresolved_contradiction",
    "archive_candidate",
)

WASTE_STATES: tuple[str, ...] = (
    "clean",
    "accumulating",
    "overloaded",
    "cleanup_required",
    "insufficient_data",
)


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["safety"] = dict(SAFETY_STAMPS)
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if x != x:
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _parse_iso(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def compute_decay_factor(age_hours: Any, half_life_hours: Any) -> float:
    age = max(_coerce_float(age_hours), 0.0)
    half_life = max(_coerce_float(half_life_hours, 24.0), 0.1)
    return math.exp(-math.log(2.0) * (age / half_life))


def _resolve_age_hours(signal: dict[str, Any], now: datetime | None) -> float:
    explicit = _coerce_float(signal.get("age_hours"), -1.0)
    if explicit >= 0.0:
        return explicit
    created_at = _parse_iso(signal.get("created_at"))
    if created_at is None:
        return 0.0
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta = (reference - created_at).total_seconds() / 3600.0
    return max(delta, 0.0)


def _resolve_half_life_hours(signal: dict[str, Any]) -> float:
    explicit = _coerce_float(signal.get("half_life_hours"), -1.0)
    if explicit > 0:
        return explicit
    signal_type = _text(signal.get("signal_type")) or "unknown"
    return DEFAULT_HALF_LIFE_HOURS.get(signal_type, DEFAULT_HALF_LIFE_HOURS["unknown"])


def compute_signal_half_life(signal: Any, *, now: datetime | None = None) -> dict[str, Any]:
    data = signal if isinstance(signal, dict) else {}
    age_hours = _resolve_age_hours(data, now)
    half_life_hours = _resolve_half_life_hours(data)
    decay_factor = compute_decay_factor(age_hours, half_life_hours)
    initial = _clamp(data.get("initial_strength"), 0.0, 1.0)
    decayed_strength = _clamp(initial * decay_factor)
    stale_threshold_hours = max(
        _coerce_float(data.get("stale_threshold_hours"), 3.0 * half_life_hours),
        half_life_hours,
    )
    stale = age_hours >= stale_threshold_hours
    damping_rate = round(math.log(2.0) / half_life_hours, 6)
    operator_action = "decay_archive" if stale else (
        "watch" if decay_factor >= 0.5 else "review_later"
    )
    return _stamp({
        "signal_age_hours": round(age_hours, 4),
        "signal_half_life_hours": round(half_life_hours, 4),
        "decay_factor": round(decay_factor, 4),
        "decayed_strength": round(decayed_strength, 4),
        "stale_signal": bool(stale),
        "stale_threshold_hours": round(stale_threshold_hours, 4),
        "damping_rate": damping_rate,
        "operator_action": operator_action,
    })


def classify_signal_waste(signal: Any, *, now: datetime | None = None) -> dict[str, Any]:
    data = signal if isinstance(signal, dict) else {}
    half_life_payload = compute_signal_half_life(data, now=now)
    stale = bool(half_life_payload["stale_signal"])
    duplicate_count = _coerce_int(data.get("duplicate_count"))
    contradiction_count = _coerce_int(data.get("contradiction_count"))
    reinforcement_count = _coerce_int(data.get("reinforcement_count"))
    failed_thesis = bool(data.get("failed_thesis"))
    unresolved_contradiction = bool(data.get("unresolved_contradiction"))

    if failed_thesis:
        waste_class = "failed_thesis_debt"
    elif unresolved_contradiction:
        waste_class = "unresolved_contradiction"
    elif contradiction_count >= 3 and reinforcement_count <= contradiction_count:
        waste_class = "contradicted"
    elif duplicate_count >= 3:
        waste_class = "duplicate_echo"
    elif stale and reinforcement_count == 0:
        waste_class = "archive_candidate"
    elif stale:
        waste_class = "stale"
    else:
        waste_class = "active"

    operator_action_map = {
        "active": "observe",
        "stale": "decay_archive",
        "duplicate_echo": "decay_archive",
        "contradicted": "review_later",
        "failed_thesis_debt": "decay_archive",
        "unresolved_contradiction": "review_later",
        "archive_candidate": "decay_archive",
    }

    return _stamp({
        "waste_class": waste_class,
        "stale_signal": stale,
        "duplicate_count": duplicate_count,
        "contradiction_count": contradiction_count,
        "reinforcement_count": reinforcement_count,
        "failed_thesis": failed_thesis,
        "unresolved_contradiction": unresolved_contradiction,
        "signal_age_hours": half_life_payload["signal_age_hours"],
        "decay_factor": half_life_payload["decay_factor"],
        "decayed_strength": half_life_payload["decayed_strength"],
        "operator_action": operator_action_map[waste_class],
    })


def _summary_inputs_from_signals(signals: list[dict[str, Any]], now: datetime | None) -> dict[str, int]:
    out = {
        "false_positive_count": 0,
        "duplicate_count": 0,
        "stale_signal_count": 0,
        "unresolved_contradiction_count": 0,
        "failed_thesis_count": 0,
        "unreconciled_trade_count": 0,
        "quarantined_signal_count": 0,
        "total_signal_count": 0,
    }
    for s in signals:
        out["total_signal_count"] += 1
        if s.get("false_positive") is True:
            out["false_positive_count"] += 1
        if _coerce_int(s.get("duplicate_count")) > 0:
            out["duplicate_count"] += 1
        waste = classify_signal_waste(s, now=now)
        if waste["stale_signal"]:
            out["stale_signal_count"] += 1
        if waste["waste_class"] == "unresolved_contradiction":
            out["unresolved_contradiction_count"] += 1
        if waste["waste_class"] == "failed_thesis_debt":
            out["failed_thesis_count"] += 1
        if s.get("unreconciled_trade") is True:
            out["unreconciled_trade_count"] += 1
        if s.get("quarantined") is True or _text(s.get("waste_class")) == "quarantine":
            out["quarantined_signal_count"] += 1
    return out


def summarize_waste_load(signals_or_summary: Any, *, now: datetime | None = None) -> dict[str, Any]:
    if isinstance(signals_or_summary, list):
        sig_rows = [s for s in signals_or_summary if isinstance(s, dict)]
        counts = _summary_inputs_from_signals(sig_rows, now)
    elif isinstance(signals_or_summary, dict):
        counts = {
            "false_positive_count": _coerce_int(signals_or_summary.get("false_positive_count")),
            "duplicate_count": _coerce_int(signals_or_summary.get("duplicate_count")),
            "stale_signal_count": _coerce_int(signals_or_summary.get("stale_signal_count")),
            "unresolved_contradiction_count": _coerce_int(
                signals_or_summary.get("unresolved_contradiction_count")
            ),
            "failed_thesis_count": _coerce_int(signals_or_summary.get("failed_thesis_count")),
            "unreconciled_trade_count": _coerce_int(
                signals_or_summary.get("unreconciled_trade_count")
            ),
            "quarantined_signal_count": _coerce_int(
                signals_or_summary.get("quarantined_signal_count")
            ),
            "total_signal_count": _coerce_int(signals_or_summary.get("total_signal_count")),
        }
    else:
        counts = {
            "false_positive_count": 0, "duplicate_count": 0,
            "stale_signal_count": 0, "unresolved_contradiction_count": 0,
            "failed_thesis_count": 0, "unreconciled_trade_count": 0,
            "quarantined_signal_count": 0, "total_signal_count": 0,
        }

    waste_load_raw = (
        counts["false_positive_count"]
        + counts["duplicate_count"]
        + counts["stale_signal_count"]
        + counts["unresolved_contradiction_count"]
        + counts["failed_thesis_count"]
    )

    total = counts["total_signal_count"]
    if total == 0:
        waste_state = "insufficient_data"
        waste_load_score = 0.0
        signal_clarity = 0.0
    else:
        waste_load_score = _clamp(waste_load_raw / max(total, 1))
        useful = max(total - waste_load_raw, 0)
        denom = useful + waste_load_raw
        signal_clarity = _clamp(useful / denom) if denom else 0.0
        if waste_load_score < 0.2:
            waste_state = "clean"
        elif waste_load_score < 0.5:
            waste_state = "accumulating"
        elif waste_load_score < 0.75:
            waste_state = "overloaded"
        else:
            waste_state = "cleanup_required"

    recommendations: list[str] = []
    if counts["duplicate_count"] >= 3:
        recommendations.append("prune_duplicate_signals")
    if counts["stale_signal_count"] >= 3:
        recommendations.append("archive_stale_signals")
    if counts["unresolved_contradiction_count"] >= 1:
        recommendations.append("resolve_or_quarantine_contradictions")
    if counts["failed_thesis_count"] >= 1:
        recommendations.append("retire_failed_thesis_debt")
    if counts["unreconciled_trade_count"] >= 1:
        recommendations.append("reconcile_open_trades")

    operator_action_map = {
        "clean": "observe",
        "accumulating": "watch",
        "overloaded": "decay_archive",
        "cleanup_required": "decay_archive",
        "insufficient_data": "observe",
    }

    return _stamp({
        "waste_state": waste_state,
        "waste_load_raw": waste_load_raw,
        "waste_load_score": round(waste_load_score, 4),
        "signal_clarity_score": round(signal_clarity, 4),
        "counts": counts,
        "cleanup_recommendations": recommendations,
        "operator_action": operator_action_map[waste_state],
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "DEFAULT_HALF_LIFE_HOURS",
    "WASTE_CLASSES",
    "WASTE_STATES",
    "compute_decay_factor",
    "compute_signal_half_life",
    "classify_signal_waste",
    "summarize_waste_load",
]
