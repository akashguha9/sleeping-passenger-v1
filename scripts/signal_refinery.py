from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

try:
    from scripts.moltbook_loader import MOLTBOOK_DIR, load_moltbook_bundle
    from scripts.operator_control import (
        build_signal_admission_report,
        filter_admitted_signal_rows,
        load_operator_state,
    )
    from scripts.runtime_common import (
        OPEN_POSITIONS_PATH,
        SIGNAL_REFINERY_CONFIG_PATH,
        SIGNAL_REFINERY_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_run_started_at,
        get_source_mode,
        load_json_file,
        load_open_positions,
        repo_relative,
        write_json_atomic,
    )
    from scripts.visibility_timing_sync import (
        build_visibility_timing_context,
        summarize_visibility_timing_context,
    )
except ModuleNotFoundError:
    from moltbook_loader import MOLTBOOK_DIR, load_moltbook_bundle
    from operator_control import (
        build_signal_admission_report,
        filter_admitted_signal_rows,
        load_operator_state,
    )
    from runtime_common import (
        OPEN_POSITIONS_PATH,
        SIGNAL_REFINERY_CONFIG_PATH,
        SIGNAL_REFINERY_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_run_started_at,
        get_source_mode,
        load_json_file,
        load_open_positions,
        repo_relative,
        write_json_atomic,
    )
    from visibility_timing_sync import (
        build_visibility_timing_context,
        summarize_visibility_timing_context,
    )


DEFAULT_CONFIG: dict[str, Any] = {
    "horsepower": {
        "target_qualifying_signals": 8,
        "freshness_decay_days": 21,
    },
    "validation": {
        "validated_signal_cutoff": 0.62,
        "needs_confirmation_cutoff": 0.45,
        "neutral_cross_source_confirmation_score": 0.5,
        "neutral_source_quality_score": 0.55,
        "weights": {
            "ce_score": 0.3,
            "state_quality": 0.18,
            "blocker_clearance": 0.12,
            "first_order": 0.1,
            "cross_source_confirmation": 0.1,
            "price_lead": 0.08,
            "repricing_headroom": 0.08,
            "source_quality": 0.02,
            "novelty": 0.02,
        },
    },
    "launch_control": {
        "max_entry_review_snapshots_before_crowding": 4,
        "repricing_headroom_floor": 0.4,
    },
    "thermal_battery": {
        "max_open_positions": 6,
        "max_positions_per_cluster": 2,
        "max_chaos_positions": 0,
        "daily_trade_cap": 2,
        "cooldown_days_after_chaos_loss": 3,
        "review_requires_deployment_clear": False,
    },
    "repeatability": {
        "false_positive_alert_rate": 0.4,
        "fragile_expectancy_floor_pct": 0.0,
    },
    "maintenance": {
        "notes_excerpt_length": 160,
    },
    "visibility_timing": {
        "persistence_cap": 6,
        "light_weights": {
            "validation_score": 0.28,
            "cross_source_confirmation": 0.12,
            "source_quality": 0.08,
            "price_lead": 0.12,
            "narrative_visibility": 0.15,
            "stage_visibility": 0.15,
            "crowding_visibility": 0.10,
        },
        "phase_thresholds": {
            "new_moon_max": 0.10,
            "crescent_max": 0.30,
            "quarter_max": 0.55,
            "gibbous_max": 0.80,
            "full_moon_max": 1.00,
            "waning_decline_min": 0.05,
            "waning_peak_min": 0.55,
        },
        "temporal": {
            "age_days_cap": 30.0,
            "persistence_cap": 6.0,
            "age_weight": 0.45,
            "stage_weight": 0.35,
            "persistence_weight": 0.20,
        },
        "crowding": {
            "full_moon_light_min": 0.80,
            "late_temporal_min": 0.72,
            "trap_score_min": 0.75,
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_signal_refinery_config(path: Path | None = None) -> dict[str, Any]:
    target = path or SIGNAL_REFINERY_CONFIG_PATH
    payload = load_json_file(target, default={})
    if not isinstance(payload, dict):
        payload = {}
    return _deep_merge(DEFAULT_CONFIG, payload)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _safe_round(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_signal_emergence_ts(signal_id: str | None) -> datetime | None:
    if not signal_id:
        return None
    parts = str(signal_id).split("_")
    if len(parts) < 4:
        return None
    try:
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _latest_signal_age_days(signal_rows: list[dict[str, Any]], as_of: datetime) -> float | None:
    timestamps = [
        ts for ts in (_parse_signal_emergence_ts(row.get("signal_id")) for row in signal_rows) if ts
    ]
    if not timestamps:
        return None
    latest = max(timestamps)
    return max(0.0, (as_of - latest).total_seconds() / 86400.0)


def _position_by_ticker(open_positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in open_positions:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            mapping[ticker] = row
    return mapping


def _trade_close_by_ticker(trade_closes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in trade_closes:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            mapping[ticker] = row
    return mapping


def _count_persistence(
    trend_report: dict[str, Any] | None,
    *keys: str,
) -> dict[str, int]:
    mapping: dict[str, int] = {}
    report = trend_report if isinstance(trend_report, dict) else {}
    for key in keys:
        block = report.get(key, {})
        rows = block.get("persistent_names", []) if isinstance(block, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").upper()
            if not ticker:
                continue
            try:
                consecutive_snapshots = int(row.get("consecutive_snapshots", 0))
            except (TypeError, ValueError):
                consecutive_snapshots = 0
            mapping[ticker] = max(mapping.get(ticker, 0), consecutive_snapshots)
    return mapping


def _candidate_streak_count(
    trend_report: dict[str, Any] | None,
    key: str,
) -> dict[str, int]:
    report = trend_report if isinstance(trend_report, dict) else {}
    block = report.get(key, {})
    rows = block.get("persistent_names", []) if isinstance(block, dict) else []
    if not isinstance(rows, list):
        return {}
    mapping: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        try:
            mapping[ticker] = int(row.get("consecutive_snapshots", 0))
        except (TypeError, ValueError):
            mapping[ticker] = 0
    return mapping


def _prior_visibility_context_by_signal(
    path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    payload = load_json_file(path or SIGNAL_REFINERY_REPORT_PATH, default={})
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("validation_engine", {}).get("signals", [])
    if not isinstance(rows, list):
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        signal_id = str(row.get("signal_id") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        if signal_id:
            mapping[signal_id] = row
        if ticker and ticker not in mapping:
            mapping[ticker] = row
    return mapping


def _state_quality(row: dict[str, Any]) -> float:
    status = str(row.get("status") or "UNKNOWN").upper()
    pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()
    if status == "EXECUTED_CLEAN":
        return 0.9
    if status == "EXECUTED_CHAOS":
        return 0.15
    if pre_entry_state == "CLEAN_ENTRY_ELIGIBLE":
        return 0.8
    if pre_entry_state == "CLEAN_READY_PENDING_TRIGGER":
        return 0.68
    if pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE":
        return 0.55
    watchlist_tier = str(row.get("watchlist_tier") or "").upper()
    if watchlist_tier == "PROMOTABLE":
        return 0.5
    return 0.35


def _source_quality(row: dict[str, Any], neutral_score: float) -> float:
    status = str(row.get("status") or "UNKNOWN").upper()
    pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()
    if status == "EXECUTED_CLEAN":
        return 0.8
    if status == "EXECUTED_CHAOS":
        return 0.2
    if pre_entry_state == "CLEAN_ENTRY_ELIGIBLE":
        return 0.7
    if pre_entry_state == "CLEAN_READY_PENDING_TRIGGER":
        return 0.65
    if pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE":
        return 0.6
    return neutral_score


def _crowding_state(
    ticker: str,
    position: dict[str, Any] | None,
    entry_review_streaks: dict[str, int],
    launch_config: dict[str, Any],
) -> tuple[str, float]:
    if position:
        if float(position.get("current_price", 0.0)) >= float(position.get("take_profit", 0.0)):
            return "ALREADY_EXTENDED", 0.0
        return "EXISTING_EXPOSURE", 0.25

    streak = int(entry_review_streaks.get(ticker, 0))
    threshold = int(launch_config.get("max_entry_review_snapshots_before_crowding", 4))
    if streak >= threshold:
        return "CROWDED", 0.2
    if streak > 0:
        return "HEATING_UP", 0.55
    return "OPEN", 0.8


def _price_lead_score(
    row: dict[str, Any],
    position: dict[str, Any] | None,
) -> float:
    status = str(row.get("status") or "").upper()
    if position:
        return 0.3
    if status == "EXECUTED_CHAOS":
        return 0.2
    if str(row.get("pre_entry_state") or "").upper() == "CLEAN_ENTRY_ELIGIBLE":
        return 0.7
    return 0.65


def _first_order_score(
    row: dict[str, Any],
    persistence_map: dict[str, int],
) -> float:
    ticker = str(row.get("ticker") or "").upper()
    status = str(row.get("status") or "UNKNOWN").upper()
    if status == "EXECUTED_CHAOS":
        return 0.3
    persistence = int(persistence_map.get(ticker, 0))
    return _clamp(0.85 - (0.02 * persistence), lower=0.3, upper=0.85)


def _novelty_score(
    row: dict[str, Any],
    persistence_map: dict[str, int],
) -> float:
    ticker = str(row.get("ticker") or "").upper()
    persistence = int(persistence_map.get(ticker, 0))
    return _clamp(1.0 - (0.04 * persistence), lower=0.25, upper=1.0)


def _blocker_clearance_score(row: dict[str, Any]) -> float:
    blocker = str(row.get("blocker_attribution") or "NONE").upper()
    if blocker in {"", "NONE"}:
        return 1.0
    return 0.0


def _cross_source_score(config: dict[str, Any]) -> float:
    return float(config["validation"]["neutral_cross_source_confirmation_score"])


def _build_horsepower_monitor(
    state: dict[str, Any],
    config: dict[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    signal_summary = state.get("signal_summary", {})
    per_signal_rows = state.get("per_signal_attribution", [])
    total_signals = int(signal_summary.get("signal_count_total", 0) or 0)
    qualifying_signals = int(signal_summary.get("signals_above_ce_threshold", 0) or 0)
    status_counts = signal_summary.get("status_counts_above_threshold", {})
    clean_entries = int(status_counts.get("EXECUTED_CLEAN", 0) or 0)
    chaos_entries = int(status_counts.get("EXECUTED_CHAOS", 0) or 0)
    watchlist_count = int(status_counts.get("WATCHLIST", 0) or 0)

    coverage_ratio = qualifying_signals / total_signals if total_signals > 0 else 0.0
    clean_conversion_rate = clean_entries / qualifying_signals if qualifying_signals > 0 else 0.0
    chaos_leak_rate = chaos_entries / qualifying_signals if qualifying_signals > 0 else 0.0
    watchlist_backlog_ratio = watchlist_count / qualifying_signals if qualifying_signals > 0 else 0.0

    target_qualifying = float(config["horsepower"].get("target_qualifying_signals", 8) or 8)
    freshness_decay_days = float(config["horsepower"].get("freshness_decay_days", 21) or 21)
    latest_signal_age_days = _latest_signal_age_days(per_signal_rows, as_of)
    freshness_score = (
        0.0
        if latest_signal_age_days is None
        else _clamp(1.0 - (latest_signal_age_days / freshness_decay_days))
    )
    qualifying_capacity_ratio = qualifying_signals / target_qualifying if target_qualifying > 0 else 0.0
    horsepower_score = _clamp(
        (0.4 * _clamp(qualifying_capacity_ratio))
        + (0.3 * coverage_ratio)
        + (0.3 * freshness_score)
    )

    return {
        "source_mode": get_source_mode(),
        "signal_count_total": total_signals,
        "signals_above_threshold": qualifying_signals,
        "coverage_ratio": round(coverage_ratio, 3),
        "clean_conversion_rate": round(clean_conversion_rate, 3),
        "chaos_leak_rate": round(chaos_leak_rate, 3),
        "watchlist_backlog_ratio": round(watchlist_backlog_ratio, 3),
        "latest_signal_age_days": _safe_round(latest_signal_age_days, 2),
        "horsepower_score": round(horsepower_score, 3),
        "ingestion_latency_measurement": "ABSENT_LIVE_INGESTION_CLOCK",
        "note": "Horsepower measures crude signal throughput, not decision quality.",
    }


def _build_validation_engine(
    state: dict[str, Any],
    config: dict[str, Any],
    trend_report: dict[str, Any] | None,
    open_positions: list[dict[str, Any]],
    as_of: datetime,
    prior_context_by_signal: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validation_config = config["validation"]
    weights = validation_config["weights"]
    validation_cutoff = float(validation_config["validated_signal_cutoff"])
    confirmation_cutoff = float(validation_config["needs_confirmation_cutoff"])
    neutral_source_quality_score = float(validation_config["neutral_source_quality_score"])
    position_map = _position_by_ticker(open_positions)
    persistence_map = _count_persistence(
        trend_report,
        "blocked_promotable_transition_streak",
        "clean_ready_pending_transition_streak",
        "clean_entry_eligible_transition_streak",
    )
    entry_review_streaks = _count_persistence(
        trend_report,
        "entry_review_candidate_streak",
        "clean_entry_eligible_transition_streak",
    )
    prior_context_map = prior_context_by_signal if isinstance(prior_context_by_signal, dict) else {}

    rows: list[dict[str, Any]] = []
    validated_count = 0
    needs_confirmation_count = 0
    invalidated_count = 0

    for row in state.get("per_signal_attribution", []):
        ticker = str(row.get("ticker") or "").upper()
        position = position_map.get(ticker)
        state_quality = _state_quality(row)
        blocker_clearance_score = _blocker_clearance_score(row)
        first_order_score = _first_order_score(row, persistence_map)
        cross_source_confirmation_score = _cross_source_score(config)
        crowding_state, repricing_headroom_score = _crowding_state(
            ticker=ticker,
            position=position,
            entry_review_streaks=entry_review_streaks,
            launch_config=config["launch_control"],
        )
        price_lead_score = _price_lead_score(row, position)
        source_quality_score = _source_quality(row, neutral_source_quality_score)
        novelty_score = _novelty_score(row, persistence_map)

        validation_score = _clamp(
            (float(row.get("ce_score", 0.0)) * float(weights["ce_score"]))
            + (state_quality * float(weights["state_quality"]))
            + (blocker_clearance_score * float(weights["blocker_clearance"]))
            + (first_order_score * float(weights["first_order"]))
            + (
                cross_source_confirmation_score
                * float(weights["cross_source_confirmation"])
            )
            + (price_lead_score * float(weights["price_lead"]))
            + (repricing_headroom_score * float(weights["repricing_headroom"]))
            + (source_quality_score * float(weights["source_quality"]))
            + (novelty_score * float(weights["novelty"]))
        )

        pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()
        tradable_structure = str(row.get("status") or "").upper() == "EXECUTED_CLEAN" or (
            pre_entry_state
            in {
                "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
                "CLEAN_READY_PENDING_TRIGGER",
                "CLEAN_ENTRY_ELIGIBLE",
            }
        )
        if (
            validation_score >= validation_cutoff
            and blocker_clearance_score >= 1.0
            and tradable_structure
        ):
            validation_state = "VALIDATED"
            validated_count += 1
        elif validation_score >= confirmation_cutoff:
            validation_state = "NEEDS_CONFIRMATION"
            needs_confirmation_count += 1
        else:
            validation_state = "INVALIDATED"
            invalidated_count += 1

        event_emergence_ts = _parse_signal_emergence_ts(row.get("signal_id"))
        validation_completion_ts = as_of if validation_state == "VALIDATED" else None
        time_to_valid_signal_hours = None
        if event_emergence_ts and validation_completion_ts:
            time_to_valid_signal_hours = (
                validation_completion_ts - event_emergence_ts
            ).total_seconds() / 3600.0

        persistence_count = max(
            int(persistence_map.get(ticker, 0)),
            int(entry_review_streaks.get(ticker, 0)),
        )
        prior_context = prior_context_map.get(
            str(row.get("signal_id") or "").strip()
        ) or prior_context_map.get(ticker)
        visibility_timing_context = build_visibility_timing_context(
            signal_row=row,
            validation_score=validation_score,
            cross_source_confirmation_score=cross_source_confirmation_score,
            source_quality_score=source_quality_score,
            price_lead_score=price_lead_score,
            novelty_score=novelty_score,
            blocker_clearance_score=blocker_clearance_score,
            crowding_state=crowding_state,
            pre_entry_state=pre_entry_state,
            status=str(row.get("status") or ""),
            validation_state=validation_state,
            event_emergence_ts=(
                event_emergence_ts.isoformat(timespec="seconds")
                if event_emergence_ts
                else None
            ),
            persistence_count=persistence_count,
            as_of=as_of,
            previous_context=prior_context,
            config=config.get("visibility_timing"),
        )

        rows.append(
            {
                "signal_id": row.get("signal_id"),
                "ticker": ticker,
                "status": row.get("status"),
                "pre_entry_state": row.get("pre_entry_state", "NONE"),
                "validation_score": round(validation_score, 3),
                "validation_state": validation_state,
                "first_order_score": round(first_order_score, 3),
                "cross_source_confirmation_score": round(
                    cross_source_confirmation_score,
                    3,
                ),
                "price_lead_score": round(price_lead_score, 3),
                "repricing_headroom_score": round(repricing_headroom_score, 3),
                "source_quality_score": round(source_quality_score, 3),
                "novelty_score": round(novelty_score, 3),
                "crowding_state": crowding_state,
                "blocker_clearance_score": round(blocker_clearance_score, 3),
                "event_emergence_ts": (
                    event_emergence_ts.isoformat(timespec="seconds")
                    if event_emergence_ts
                    else None
                ),
                "validation_completion_ts": (
                    validation_completion_ts.isoformat(timespec="seconds")
                    if validation_completion_ts
                    else None
                ),
                "time_to_valid_signal_hours": _safe_round(time_to_valid_signal_hours, 2),
                **visibility_timing_context,
            }
        )

    rows.sort(key=lambda item: (-item["validation_score"], item["ticker"]))
    average_validation_score = _mean([float(item["validation_score"]) for item in rows])
    return {
        "validated_signal_cutoff": validation_cutoff,
        "needs_confirmation_cutoff": confirmation_cutoff,
        "validated_signal_count": validated_count,
        "needs_confirmation_count": needs_confirmation_count,
        "invalidated_signal_count": invalidated_count,
        "average_validation_score": round(average_validation_score, 3),
        "traction_score": round(average_validation_score, 3),
        "cross_source_measurement": "HEURISTIC_NEUTRAL_UNTIL_ETIL_EVIDENCE",
        "signals": rows,
    }


def _build_thermal_battery_manager(
    state: dict[str, Any],
    config: dict[str, Any],
    open_positions: list[dict[str, Any]],
    trade_closes: list[dict[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    thermal_config = config["thermal_battery"]
    open_position_count = len(open_positions)
    chaos_open_position_count = sum(
        1
        for row in open_positions
        if str(row.get("entry_type") or "").upper() == "CHAOS"
        and str(row.get("state") or "").upper() in {"OPEN", "REDUCED", "EXIT_PENDING"}
    )
    cluster_counter: Counter[str] = Counter(
        str(row.get("thesis_cluster") or "").upper()
        for row in open_positions
        if str(row.get("state") or "").upper() in {"OPEN", "REDUCED", "EXIT_PENDING"}
    )
    cluster_concentration = [
        {"thesis_cluster": cluster, "open_count": count}
        for cluster, count in sorted(
            cluster_counter.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    max_open_positions = int(thermal_config.get("max_open_positions", 6))
    max_positions_per_cluster = int(thermal_config.get("max_positions_per_cluster", 2))
    max_chaos_positions = int(thermal_config.get("max_chaos_positions", 0))
    daily_trade_cap = int(thermal_config.get("daily_trade_cap", 2))
    cooldown_days = int(thermal_config.get("cooldown_days_after_chaos_loss", 3))

    recent_chaos_losses = 0
    latest_chaos_loss_date = None
    for row in trade_closes:
        if str(row.get("classification") or "").upper() != "CHAOS_LOSS":
            continue
        exit_date = _parse_iso_datetime(f"{row.get('exit_date')}T00:00:00+00:00")
        if exit_date is None:
            continue
        if latest_chaos_loss_date is None or exit_date > latest_chaos_loss_date:
            latest_chaos_loss_date = exit_date
        if (as_of.date() - exit_date.date()).days <= cooldown_days:
            recent_chaos_losses += 1

    cooldown_active = recent_chaos_losses > 0
    over_cluster_limit = any(count > max_positions_per_cluster for count in cluster_counter.values())
    deployment_allowed = (
        bool(state.get("execution_policy", {}).get("allow_new_risk", False))
        and chaos_open_position_count <= max_chaos_positions
        and open_position_count < max_open_positions
        and not over_cluster_limit
        and not cooldown_active
    )

    if cooldown_active or chaos_open_position_count > max_chaos_positions:
        thermal_state = "COOLING"
    elif open_position_count >= max_open_positions or over_cluster_limit:
        thermal_state = "SATURATED"
    elif not bool(state.get("execution_policy", {}).get("allow_new_risk", False)):
        thermal_state = "CONSTRAINED"
    else:
        thermal_state = "READY"

    return {
        "thermal_state": thermal_state,
        "open_position_count": open_position_count,
        "position_headroom": max(0, max_open_positions - open_position_count),
        "chaos_open_position_count": chaos_open_position_count,
        "max_open_positions": max_open_positions,
        "max_positions_per_cluster": max_positions_per_cluster,
        "max_chaos_positions": max_chaos_positions,
        "daily_trade_cap": daily_trade_cap,
        "daily_trade_slots_remaining": daily_trade_cap,
        "cooldown_active": cooldown_active,
        "recent_chaos_losses_within_cooldown_window": recent_chaos_losses,
        "latest_chaos_loss_date": (
            latest_chaos_loss_date.date().isoformat() if latest_chaos_loss_date else None
        ),
        "cluster_concentration": cluster_concentration,
        "review_allowed": True,
        "deployment_allowed": deployment_allowed,
        "note": "Thermal state governs deployability. Review can remain open while deployment is blocked.",
    }


def _build_launch_control(
    state: dict[str, Any],
    config: dict[str, Any],
    validation_engine: dict[str, Any],
    thermal_manager: dict[str, Any],
    open_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    policy = state.get("execution_policy", {})
    position_map = _position_by_ticker(open_positions)
    review_ready_names: list[str] = []
    blocked_validation_names: list[str] = []
    blocked_crowding_names: list[str] = []
    blocked_policy_names: list[str] = []
    blocked_thermal_names: list[str] = []
    active_clean_names: list[str] = []
    launch_rows: list[dict[str, Any]] = []
    headroom_floor = float(config["launch_control"].get("repricing_headroom_floor", 0.4))
    require_deployment_clear = bool(
        config["thermal_battery"].get("review_requires_deployment_clear", False)
    )

    for row in validation_engine.get("signals", []):
        ticker = str(row.get("ticker") or "").upper()
        pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()
        position = position_map.get(ticker)
        validation_state = str(row.get("validation_state") or "INVALIDATED").upper()
        crowding_state = str(row.get("crowding_state") or "UNKNOWN").upper()
        repricing_headroom_score = float(row.get("repricing_headroom_score", 0.0))
        signal_status = str(row.get("status") or "").upper()

        launch_state = "OBSERVE"
        launch_reason = "Validation not yet sufficient for review."
        deployment_state = "OBSERVE_ONLY"

        if position and str(position.get("entry_type") or "").upper() == "CLEAN":
            launch_state = "ACTIVE_VALIDATED_POSITION"
            launch_reason = "Clean position is already deployed."
            deployment_state = "ALREADY_DEPLOYED"
            active_clean_names.append(ticker)
        elif validation_state != "VALIDATED":
            launch_state = "BLOCKED_VALIDATION"
            launch_reason = "Signal has not reached the validated cutoff."
            blocked_validation_names.append(ticker)
        elif crowding_state in {"CROWDED", "ALREADY_EXTENDED"} or repricing_headroom_score < headroom_floor:
            launch_state = "BLOCKED_CROWDING"
            launch_reason = "Repricing headroom is too low for controlled entry review."
            blocked_crowding_names.append(ticker)
        elif pre_entry_state != "CLEAN_ENTRY_ELIGIBLE":
            if signal_status == "EXECUTED_CLEAN":
                launch_state = "ACTIVE_VALIDATED_POSITION"
                launch_reason = "Clean signal already converted into a live position."
                deployment_state = "ALREADY_DEPLOYED"
                if ticker not in active_clean_names:
                    active_clean_names.append(ticker)
            elif not bool(policy.get("allow_new_risk", False)):
                launch_state = "BLOCKED_POLICY"
                launch_reason = "Policy still forbids new risk even though validation improved."
                blocked_policy_names.append(ticker)
            else:
                launch_state = "NEEDS_TRIGGER"
                launch_reason = "Signal is validated but not yet in CLEAN_ENTRY_ELIGIBLE state."
        elif require_deployment_clear and not thermal_manager.get("deployment_allowed", False):
            launch_state = "BLOCKED_THERMAL"
            launch_reason = "Thermal manager blocks deployment despite validation."
            blocked_thermal_names.append(ticker)
            deployment_state = "THERMAL_BLOCKED"
        elif not bool(policy.get("allow_new_risk", False)):
            launch_state = "BLOCKED_POLICY"
            launch_reason = "Policy forbids new risk despite a validated review candidate."
            blocked_policy_names.append(ticker)
            deployment_state = "POLICY_BLOCKED"
        else:
            launch_state = "REVIEW_READY"
            launch_reason = "First sufficiently validated tradable signal is ready for entry review."
            review_ready_names.append(ticker)
            deployment_state = (
                "DEPLOYABLE"
                if thermal_manager.get("deployment_allowed", False)
                else "REVIEW_ONLY_THERMAL_BLOCKED"
            )

        launch_rows.append(
            {
                "ticker": ticker,
                "signal_id": row.get("signal_id"),
                "validation_state": validation_state,
                "validation_score": row.get("validation_score"),
                "launch_state": launch_state,
                "launch_reason": launch_reason,
                "deployment_state": deployment_state,
                "crowding_state": crowding_state,
                "repricing_headroom_score": row.get("repricing_headroom_score"),
                "pre_entry_state": pre_entry_state,
            }
        )

    launch_rows.sort(key=lambda item: (-float(item.get("validation_score", 0.0)), item["ticker"]))
    decision_grade_signal_count = len(review_ready_names) + len(active_clean_names)
    deployable_signal_count = sum(
        1 for row in launch_rows if row.get("deployment_state") == "DEPLOYABLE"
    )
    return {
        "review_ready_count": len(review_ready_names),
        "review_ready_names": review_ready_names,
        "blocked_validation_count": len(blocked_validation_names),
        "blocked_validation_names": blocked_validation_names,
        "blocked_crowding_count": len(blocked_crowding_names),
        "blocked_crowding_names": blocked_crowding_names,
        "blocked_policy_count": len(blocked_policy_names),
        "blocked_policy_names": blocked_policy_names,
        "blocked_thermal_count": len(blocked_thermal_names),
        "blocked_thermal_names": blocked_thermal_names,
        "active_validated_position_count": len(active_clean_names),
        "active_validated_position_names": active_clean_names,
        "blocked_count": len(blocked_validation_names)
        + len(blocked_crowding_names)
        + len(blocked_policy_names)
        + len(blocked_thermal_names),
        "decision_grade_signal_count": decision_grade_signal_count,
        "deployable_signal_count": deployable_signal_count,
        "launch_rows": launch_rows,
    }


def _build_repeatability_tracker(
    trade_closes: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    pnl_values = [float(row.get("pnl_pct", 0.0)) for row in trade_closes]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value <= 0]
    trade_count = len(pnl_values)
    hit_rate = (len(wins) / trade_count) if trade_count > 0 else 0.0
    average_win_pct = _mean(wins)
    average_loss_pct = _mean(losses)
    expectancy_pct = _mean(pnl_values)
    false_positive_rate = (
        sum(1 for row in trade_closes if str(row.get("classification") or "").upper() == "CHAOS_LOSS")
        / trade_count
        if trade_count > 0
        else 0.0
    )

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    ordered_trades = sorted(
        trade_closes,
        key=lambda row: (
            str(row.get("exit_date") or ""),
            str(row.get("trade_id") or ""),
        ),
    )
    for row in ordered_trades:
        cumulative += float(row.get("pnl_pct", 0.0))
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0:
        profit_factor = None
    else:
        profit_factor = gross_profit / gross_loss

    clean_expectancy = _mean(
        [
            float(row.get("pnl_pct", 0.0))
            for row in trade_closes
            if str(row.get("classification") or "").upper() != "CHAOS_LOSS"
        ]
    )
    chaos_expectancy = _mean(
        [
            float(row.get("pnl_pct", 0.0))
            for row in trade_closes
            if str(row.get("classification") or "").upper() == "CHAOS_LOSS"
        ]
    )

    fragile_expectancy_floor = float(
        config["repeatability"].get("fragile_expectancy_floor_pct", 0.0)
    )
    false_positive_alert = float(
        config["repeatability"].get("false_positive_alert_rate", 0.4)
    )
    if expectancy_pct <= fragile_expectancy_floor or false_positive_rate >= false_positive_alert:
        durability_state = "FRAGILE"
    elif hit_rate >= 0.55 and expectancy_pct > fragile_expectancy_floor:
        durability_state = "STABLE"
    else:
        durability_state = "MIXED"

    cluster_rows = []
    cluster_names = sorted({str(row.get("thesis_cluster") or "").upper() for row in trade_closes})
    for cluster in cluster_names:
        members = [
            row for row in trade_closes if str(row.get("thesis_cluster") or "").upper() == cluster
        ]
        member_pnls = [float(row.get("pnl_pct", 0.0)) for row in members]
        cluster_rows.append(
            {
                "thesis_cluster": cluster,
                "trade_count": len(members),
                "avg_pnl_pct": round(_mean(member_pnls), 3),
                "hit_rate": round(
                    (
                        sum(1 for value in member_pnls if value > 0) / len(member_pnls)
                    )
                    if member_pnls
                    else 0.0,
                    3,
                ),
            }
        )

    return {
        "trade_close_count": trade_count,
        "rolling_expectancy_pct": round(expectancy_pct, 3),
        "hit_rate": round(hit_rate, 3),
        "average_win_pct": round(average_win_pct, 3),
        "average_loss_pct": round(average_loss_pct, 3),
        "profit_factor": _safe_round(profit_factor, 3),
        "false_positive_rate": round(false_positive_rate, 3),
        "max_drawdown_pct": round(max_drawdown, 3),
        "clean_expectancy_pct": round(clean_expectancy, 3),
        "chaos_expectancy_pct": round(chaos_expectancy, 3),
        "durability_state": durability_state,
        "regime_sensitivity": cluster_rows,
    }


def _note_excerpt(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _maintenance_entry_from_trade(row: dict[str, Any], notes_excerpt_length: int) -> dict[str, Any]:
    stack = row.get("entry_mechanism_stack") or row.get("entry_mechanism_stack_estimated") or {}
    if not isinstance(stack, dict):
        stack = {}
    timing_state = (
        str(stack.get("lalo_state") or stack.get("att_state") or "UNKNOWN").upper()
    )
    crowding_state = str(
        stack.get("nsd_state") or stack.get("osm_state") or stack.get("osm_gate") or "UNKNOWN"
    ).upper()
    entry_decision = (
        "OVERRIDE_VETO" if row.get("entered_against_veto") else "PIPELINE_ALLOWED"
    )
    failure_mode = (
        "VETO_OVERRIDE_VALIDATED"
        if row.get("entered_against_veto") and row.get("veto_validated")
        else str(row.get("classification") or "UNKNOWN").upper()
    )
    return {
        "trade_id": row.get("trade_id"),
        "ticker": row.get("ticker"),
        "signal_origin": str(row.get("entry_classification") or "CLEAN_ENTRY").upper(),
        "validation_path": str(row.get("thesis_validation") or "UNKNOWN").upper(),
        "entry_decision": entry_decision,
        "timing_state": timing_state,
        "crowding_state": crowding_state,
        "exit_path": str(row.get("exit_reason") or "UNKNOWN").upper(),
        "failure_mode": failure_mode,
        "improvement_note": _note_excerpt(row.get("notes"), notes_excerpt_length),
    }


def _build_maintenance_wear_log(
    trade_closes: list[dict[str, Any]],
    validation_engine: dict[str, Any],
    launch_control: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    notes_excerpt_length = int(config["maintenance"].get("notes_excerpt_length", 160))
    trade_rows = [
        _maintenance_entry_from_trade(row, notes_excerpt_length) for row in trade_closes
    ]
    failure_counter = Counter(
        str(row.get("exit_reason") or "UNKNOWN").upper() for row in trade_closes
    )
    current_signal_rows: list[dict[str, Any]] = []
    launch_by_ticker = {row["ticker"]: row for row in launch_control.get("launch_rows", [])}
    for row in validation_engine.get("signals", []):
        ticker = str(row.get("ticker") or "").upper()
        launch_row = launch_by_ticker.get(ticker, {})
        if str(launch_row.get("launch_state") or "OBSERVE").upper() == "REVIEW_READY":
            improvement_note = "Validated candidate is ready for review; maintain crowding discipline."
        elif str(launch_row.get("launch_state") or "").upper().startswith("BLOCKED_"):
            improvement_note = str(launch_row.get("launch_reason") or "Tighten validation before acting.")
        else:
            improvement_note = "Keep observing until validation path hardens."
        current_signal_rows.append(
            {
                "ticker": ticker,
                "validation_state": row.get("validation_state"),
                "launch_state": launch_row.get("launch_state", "OBSERVE"),
                "launch_reason": launch_row.get("launch_reason", ""),
                "timing_state": row.get("pre_entry_state"),
                "crowding_state": row.get("crowding_state"),
                "improvement_note": improvement_note,
            }
        )

    veto_override_count = sum(1 for row in trade_closes if row.get("entered_against_veto"))
    veto_override_validated_count = sum(1 for row in trade_closes if row.get("veto_validated"))
    priorities: list[str] = []
    if veto_override_validated_count > 0:
        priorities.append("Stop overriding vetoed chaos entries until repeatability improves.")
    if any(
        str(row.get("classification") or "").upper() == "CHAOS_LOSS" for row in trade_closes
    ):
        priorities.append("Prioritize traction filters that reduce chaos leakage before adding feed speed.")
    if not any(
        str(row.get("launch_state") or "").upper() == "REVIEW_READY"
        for row in launch_control.get("launch_rows", [])
    ):
        priorities.append("The refinery is still throughput-heavy: no new signal currently clears review-ready launch state.")

    return {
        "veto_override_count": veto_override_count,
        "veto_override_validated_count": veto_override_validated_count,
        "failure_mode_counts": dict(sorted(failure_counter.items())),
        "maintenance_priorities": priorities,
        "trade_maintenance_records": trade_rows,
        "current_signal_maintenance": current_signal_rows,
    }


def _build_time_to_valid_signal_kpi(
    validation_engine: dict[str, Any],
    launch_control: dict[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    launch_by_ticker = {row["ticker"]: row for row in launch_control.get("launch_rows", [])}
    signal_rows: list[dict[str, Any]] = []
    validated_durations: list[float] = []
    launch_ready_durations: list[float] = []

    for row in validation_engine.get("signals", []):
        ticker = str(row.get("ticker") or "").upper()
        launch_row = launch_by_ticker.get(ticker, {})
        emergence_ts = _parse_iso_datetime(row.get("event_emergence_ts"))
        validation_complete_ts = (
            _parse_iso_datetime(row.get("validation_completion_ts"))
            if row.get("validation_completion_ts")
            else None
        )
        execution_eligibility_ts = (
            as_of
            if str(launch_row.get("launch_state") or "").upper() == "REVIEW_READY"
            else None
        )
        crowding_breach_ts = (
            as_of
            if str(launch_row.get("crowding_state") or "").upper() == "CROWDED"
            else None
        )
        time_to_valid_signal_hours = row.get("time_to_valid_signal_hours")
        if time_to_valid_signal_hours is not None:
            validated_durations.append(float(time_to_valid_signal_hours))
        time_to_execution_eligibility_hours = None
        if emergence_ts and execution_eligibility_ts:
            time_to_execution_eligibility_hours = (
                execution_eligibility_ts - emergence_ts
            ).total_seconds() / 3600.0
            launch_ready_durations.append(time_to_execution_eligibility_hours)

        signal_rows.append(
            {
                "ticker": ticker,
                "signal_id": row.get("signal_id"),
                "event_emergence_ts": row.get("event_emergence_ts"),
                "ingestion_observed_ts": row.get("event_emergence_ts"),
                "validation_completion_ts": row.get("validation_completion_ts"),
                "execution_eligibility_ts": (
                    execution_eligibility_ts.isoformat(timespec="seconds")
                    if execution_eligibility_ts
                    else None
                ),
                "crowding_breach_ts": (
                    crowding_breach_ts.isoformat(timespec="seconds")
                    if crowding_breach_ts
                    else None
                ),
                "time_to_valid_signal_hours": _safe_round(time_to_valid_signal_hours, 2),
                "time_to_execution_eligibility_hours": _safe_round(
                    time_to_execution_eligibility_hours,
                    2,
                ),
                "launch_state": launch_row.get("launch_state", "OBSERVE"),
            }
        )

    return {
        "measurement_mode": "HEURISTIC_SIGNAL_ID_CLOCK",
        "validated_signal_count": len(validated_durations),
        "review_ready_signal_count": len(launch_ready_durations),
        "median_time_to_valid_signal_hours": _safe_round(_median(validated_durations), 2),
        "fastest_time_to_valid_signal_hours": _safe_round(
            min(validated_durations) if validated_durations else None,
            2,
        ),
        "median_time_to_execution_eligibility_hours": _safe_round(
            _median(launch_ready_durations),
            2,
        ),
        "signals": signal_rows,
        "note": "Current repo lacks live event-emergence and ingestion clocks. This KPI is a heuristic until observation mode is wired.",
    }


def build_signal_refinery_report(
    runtime_state: dict[str, Any],
    trend_report: dict[str, Any] | None = None,
    open_positions_path: Path | None = None,
    moltbook_dir: Path | None = None,
    config_path: Path | None = None,
    output_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    config = load_signal_refinery_config(config_path)
    run_started_at = _parse_iso_datetime(get_run_started_at()) or datetime.now(timezone.utc)
    open_positions, open_positions_summary = load_open_positions(open_positions_path or OPEN_POSITIONS_PATH)
    trade_bundle = load_moltbook_bundle(moltbook_dir or MOLTBOOK_DIR)
    prior_context_by_signal = _prior_visibility_context_by_signal()
    operator_state = load_operator_state()
    signal_admission_gate = build_signal_admission_report(
        runtime_state=runtime_state,
        operator_state=operator_state,
        write_runtime=write_runtime,
    )
    admitted_signal_rows = filter_admitted_signal_rows(
        runtime_state.get("per_signal_attribution", []),
        signal_admission_gate,
    )
    gated_runtime_state = dict(runtime_state)
    gated_runtime_state["per_signal_attribution"] = admitted_signal_rows

    horsepower_monitor = _build_horsepower_monitor(runtime_state, config, run_started_at)
    validation_engine = _build_validation_engine(
        gated_runtime_state,
        config,
        trend_report,
        open_positions,
        run_started_at,
        prior_context_by_signal=prior_context_by_signal,
    )
    visibility_timing_context = summarize_visibility_timing_context(
        validation_engine.get("signals", [])
    )
    thermal_battery_manager = _build_thermal_battery_manager(
        gated_runtime_state,
        config,
        open_positions,
        trade_bundle.trade_closes,
        run_started_at,
    )
    launch_control = _build_launch_control(
        gated_runtime_state,
        config,
        validation_engine,
        thermal_battery_manager,
        open_positions,
    )
    repeatability_tracker = _build_repeatability_tracker(
        trade_bundle.trade_closes,
        config,
    )
    maintenance_wear_log = _build_maintenance_wear_log(
        trade_bundle.trade_closes,
        validation_engine,
        launch_control,
        config,
    )
    time_to_valid_signal_kpi = _build_time_to_valid_signal_kpi(
        validation_engine,
        launch_control,
        run_started_at,
    )

    signals_above_threshold = int(
        runtime_state.get("signal_summary", {}).get("signals_above_ce_threshold", 0) or 0
    )
    admitted_signal_count = int(signal_admission_gate["admitted_count"])
    decision_grade_signal_count = int(launch_control["decision_grade_signal_count"])
    deployable_signal_count = int(launch_control["deployable_signal_count"])
    average_validation_score = float(validation_engine["average_validation_score"])
    usable_signal_output = round(admitted_signal_count * average_validation_score, 3)
    if deployable_signal_count > 0:
        decision_engine_state = "REVIEW_READY"
    elif decision_grade_signal_count > 0:
        decision_engine_state = "VALIDATED_BUT_DEPLOYMENT_BLOCKED"
    elif int(validation_engine["validated_signal_count"]) > 0:
        decision_engine_state = "VALIDATED_BUT_NOT_ENTRY_ELIGIBLE"
    else:
        decision_engine_state = "CRUDE_SIGNAL_ONLY"

    report = {
        "generated_at": run_started_at.isoformat(timespec="seconds"),
        "source_mode": get_source_mode(),
        "config_path": repo_relative(config_path or SIGNAL_REFINERY_CONFIG_PATH),
        "open_positions_validation_summary": open_positions_summary,
        "manual_operator_state": operator_state,
        "signal_admission_gate": signal_admission_gate,
        "horsepower_monitor": horsepower_monitor,
        "validation_engine": validation_engine,
        "visibility_timing_context": visibility_timing_context,
        "launch_control": launch_control,
        "thermal_battery_manager": thermal_battery_manager,
        "repeatability_tracker": repeatability_tracker,
        "maintenance_wear_log": maintenance_wear_log,
        "time_to_valid_signal_kpi": time_to_valid_signal_kpi,
        "decision_engine_summary": {
            "usable_signal_output": usable_signal_output,
            "admitted_signal_count": admitted_signal_count,
            "rejected_signal_count": signal_admission_gate["rejected_count"],
            "decision_grade_signal_count": decision_grade_signal_count,
            "deployable_signal_count": deployable_signal_count,
            "current_operating_mode": decision_engine_state,
            "time_to_valid_signal_hours_median": time_to_valid_signal_kpi[
                "median_time_to_valid_signal_hours"
            ],
        },
        "note": (
            "The MVP now treats feed speed as crude horsepower, applies a hard signal "
            "admission gate, and routes admitted signals through validation, launch control, "
            "thermal discipline, repeatability, and maintenance layers."
        ),
    }

    if write_runtime:
        write_json_atomic(output_path or SIGNAL_REFINERY_REPORT_PATH, report)
    return report


def format_signal_refinery_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Signal Refinery",
            f"operating_mode={report['decision_engine_summary']['current_operating_mode']}",
            f"signals_above_threshold={report['horsepower_monitor']['signals_above_threshold']}",
            f"admitted_signal_count={report['signal_admission_gate']['admitted_count']}",
            f"rejected_signal_count={report['signal_admission_gate']['rejected_count']}",
            f"validated_signal_count={report['validation_engine']['validated_signal_count']}",
            f"review_ready_count={report['launch_control']['review_ready_count']}",
            f"deployable_signal_count={report['launch_control']['deployable_signal_count']}",
            f"thermal_state={report['thermal_battery_manager']['thermal_state']}",
            f"rolling_expectancy_pct={report['repeatability_tracker']['rolling_expectancy_pct']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert crude seeded signals into a decision-grade refinery report."
    )
    parser.add_argument(
        "--write-runtime",
        action="store_true",
        help="Persist runtime/signal_refinery_report.json.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    try:
        from scripts.signal_conversion_monitor import build_signal_conversion_report
    except ModuleNotFoundError:
        from signal_conversion_monitor import build_signal_conversion_report

    report = build_signal_refinery_report(
        runtime_state=build_runtime_state_from_scm_report_payload(
            build_signal_conversion_report()
        ),
        write_runtime=args.write_runtime,
    )
    if args.summary:
        print(format_signal_refinery_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
