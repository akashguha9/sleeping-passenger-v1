from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

try:
    from scripts.runtime_common import (
        SNAPSHOT_LOG_PATH,
        append_jsonl,
        load_current_pipeline_state,
    )
except ModuleNotFoundError:
    from runtime_common import (
        SNAPSHOT_LOG_PATH,
        append_jsonl,
        load_current_pipeline_state,
    )


SYSTEM_ENTITY_ID = "PIPELINE"
TRANSITION_STATE_RANK = {
    "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE": 1,
    "CLEAN_READY_PENDING_TRIGGER": 2,
    "CLEAN_ENTRY_ELIGIBLE": 3,
}
TAG_METADATA = {
    "BLOCKED_BY_GSCE": {
        "family": "BLOCKER",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": True,
    },
    "BLOCKED_BY_REALM_BIS": {
        "family": "BLOCKER",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": True,
    },
    "GATE_GSCE_PHASE_LOCK_ACTIVE": {
        "family": "GATE",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": True,
    },
    "GATE_REALM_BIS_ACTIVE": {
        "family": "GATE",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": True,
    },
    "PROMOTABLE_BY_CE": {
        "family": "WATCHLIST",
        "severity": "LOW",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
    "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE": {
        "family": "TRANSITION",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": True,
    },
    "CLEAN_READY_PENDING_TRIGGER": {
        "family": "TRANSITION",
        "severity": "MEDIUM",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
    "CLEAN_ENTRY_ELIGIBLE": {
        "family": "TRANSITION",
        "severity": "LOW",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
    "STANDARD_WATCHLIST": {
        "family": "WATCHLIST",
        "severity": "LOW",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
    "QUEUE_PRESSURE_HIGH": {
        "family": "QUEUE",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
    "QUEUE_PRESSURE_MEDIUM": {
        "family": "QUEUE",
        "severity": "MEDIUM",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
    "QUEUE_PRESSURE_LOW": {
        "family": "QUEUE",
        "severity": "LOW",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
    "BLOCKAGE_CRITICAL": {
        "family": "BLOCKAGE",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": True,
    },
    "OPERATOR_HOLD": {
        "family": "OPERATOR",
        "severity": "HIGH",
        "persistence": "STATEFUL",
        "veto_capable": True,
    },
    "TRANSITION_PERSISTENCE_ADVANCING": {
        "family": "TRANSITION",
        "severity": "LOW",
        "persistence": "EVENT",
        "veto_capable": False,
    },
    "TRANSITION_PACKET_READY": {
        "family": "PACKET",
        "severity": "MEDIUM",
        "persistence": "STATEFUL",
        "veto_capable": False,
    },
}


def _scenario_from_snapshot_row(row: dict | None) -> str:
    if not isinstance(row, dict):
        return "LIVE"
    scenario = str(row.get("scenario") or "LIVE").upper().strip()
    return scenario or "LIVE"


def _normalized_text_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for value in values:
        text = str(value or "").upper().strip()
        if text and text not in items:
            items.append(text)
    return items


def _watchlist_rows_from_state(state: dict) -> list[dict]:
    diagnostics = state.get("watchlist_diagnostics", {})
    watchlist_rows = diagnostics.get("watchlist_signals", []) if isinstance(diagnostics, dict) else []
    return watchlist_rows if isinstance(watchlist_rows, list) else []


def _load_snapshot_rows(path, scenario: str | None = None) -> list[dict]:
    path = path or SNAPSHOT_LOG_PATH
    if not path.exists():
        return []

    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if scenario and _scenario_from_snapshot_row(payload) != str(scenario).upper():
            continue
        rows.append(payload)
    return rows


def _previous_transition_state_map(previous_row: dict | None) -> dict[str, str]:
    if not isinstance(previous_row, dict):
        return {}

    mapping: dict[str, str] = {}
    for row in previous_row.get("transition_state_rows", []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()
        if ticker and pre_entry_state in TRANSITION_STATE_RANK:
            mapping[ticker] = pre_entry_state
    return mapping


def _transition_persistence_direction(
    previous_pre_entry_state: str | None,
    current_pre_entry_state: str,
) -> str:
    previous_rank = TRANSITION_STATE_RANK.get(str(previous_pre_entry_state or "").upper(), 0)
    current_rank = TRANSITION_STATE_RANK.get(str(current_pre_entry_state or "").upper(), 0)

    if previous_rank and current_rank > previous_rank:
        return "ADVANCING"
    if previous_rank and current_rank < previous_rank:
        return "REGRESSING"
    if previous_rank and current_rank == previous_rank:
        return "PERSISTING"
    return "NEW"


def _ticker_tag_codes(tags: list[dict]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        if str(tag.get("entity_scope") or "").upper() != "TICKER":
            continue
        ticker = str(tag.get("entity_id") or "").upper()
        tag_code = str(tag.get("tag_code") or "").upper()
        if not ticker or not tag_code:
            continue
        mapping.setdefault(ticker, set()).add(tag_code)
    return mapping


def _compat_pre_entry_state_from_tag_codes(tag_codes: set[str]) -> str:
    if "CLEAN_ENTRY_ELIGIBLE" in tag_codes:
        return "CLEAN_ENTRY_ELIGIBLE"
    if "CLEAN_READY_PENDING_TRIGGER" in tag_codes:
        return "CLEAN_READY_PENDING_TRIGGER"
    if "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE" in tag_codes:
        return "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
    return "NONE"


def _compat_candidate_conversion_state(pre_entry_state: str) -> str:
    mapping = {
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE": "PROMOTABLE_WATCHLIST",
        "CLEAN_READY_PENDING_TRIGGER": "CLEAN_READY_PENDING",
        "CLEAN_ENTRY_ELIGIBLE": "CLEAN_ENTRY_ELIGIBLE",
    }
    return mapping.get(str(pre_entry_state or "").upper(), "")


def _watchlist_names_by_pre_entry_state(state: dict, pre_entry_state: str) -> list[str]:
    target_state = pre_entry_state.upper()
    names: list[str] = []
    for row in _watchlist_rows_from_state(state):
        if not isinstance(row, dict):
            continue
        if str(row.get("pre_entry_state") or "NONE").upper() != target_state:
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker and ticker not in names:
            names.append(ticker)
    return names


def _transition_state_rows_from_tags(
    state: dict,
    tags: list[dict],
    previous_row: dict | None = None,
) -> list[dict]:
    previous_state_by_ticker = _previous_transition_state_map(previous_row)
    tag_codes_by_ticker = _ticker_tag_codes(tags)
    rows: list[dict] = []
    for row in _watchlist_rows_from_state(state):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        pre_entry_state = _compat_pre_entry_state_from_tag_codes(
            tag_codes_by_ticker.get(ticker, set())
        )
        if pre_entry_state not in TRANSITION_STATE_RANK:
            continue
        rows.append(
            {
                "signal_id": str(row.get("signal_id") or ""),
                "ticker": ticker,
                "watchlist_tier": str(row.get("watchlist_tier") or "").upper(),
                "candidate_conversion_state": _compat_candidate_conversion_state(
                    pre_entry_state
                ),
                "pre_entry_state": pre_entry_state,
                "transition_persistence_direction": _transition_persistence_direction(
                    previous_state_by_ticker.get(ticker),
                    pre_entry_state,
                ),
            }
        )
    rows.sort(key=lambda item: (item["pre_entry_state"], item["ticker"]))
    return rows


def _transition_state_names_by_pre_entry_state(
    transition_state_rows: list[dict],
    pre_entry_state: str,
) -> list[str]:
    target_state = str(pre_entry_state or "").upper()
    names: list[str] = []
    for row in transition_state_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("pre_entry_state") or "NONE").upper() != target_state:
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker and ticker not in names:
            names.append(ticker)
    return names


def _summarize_watchlist_intelligence_from_state(state: dict) -> dict:
    promotable_names: list[str] = []
    standard_names: list[str] = []
    for row in _watchlist_rows_from_state(state):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        watchlist_tier = str(row.get("watchlist_tier") or "").upper()
        if watchlist_tier == "PROMOTABLE" and ticker not in promotable_names:
            promotable_names.append(ticker)
        if watchlist_tier == "STANDARD" and ticker not in standard_names:
            standard_names.append(ticker)

    blocked_names = _watchlist_names_by_pre_entry_state(
        state,
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
    )
    return {
        "promotable_watchlist_count": len(promotable_names),
        "promotable_watchlist_names": promotable_names,
        "standard_watchlist_count": len(standard_names),
        "standard_watchlist_names": standard_names,
        "blocked_promotable_clean_candidate_count": len(blocked_names),
        "blocked_promotable_clean_candidate_names": blocked_names,
    }


def _load_last_snapshot_timestamp(path) -> datetime | None:
    path = path or SNAPSHOT_LOG_PATH
    if not path.exists():
        return None

    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not lines:
        return None

    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    raw_timestamp = payload.get("timestamp")
    if not isinstance(raw_timestamp, str) or not raw_timestamp.strip():
        return None

    try:
        return datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return None


def _unique_snapshot_timestamp(path=SNAPSHOT_LOG_PATH) -> str:
    candidate = datetime.now(timezone.utc)
    last_timestamp = _load_last_snapshot_timestamp(path)
    if last_timestamp is not None and candidate <= last_timestamp:
        candidate = last_timestamp + timedelta(microseconds=1)
    return candidate.isoformat(timespec="microseconds")


def _consecutive_name_presence(rows: list[dict], key: str, names: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for name in names:
        streak = 0
        for row in reversed(rows):
            if name in _normalized_text_list(row.get(key, [])):
                streak += 1
            else:
                break
        mapping[name] = streak
    return mapping


def _derive_queue_pressure_state(
    blocked_names: list[str],
    scenario_rows: list[dict],
    health_report: dict | None = None,
) -> str:
    if isinstance(health_report, dict):
        queue_pressure_state = str(health_report.get("queue_pressure_state") or "").upper()
        if queue_pressure_state in {"HIGH", "MEDIUM", "LOW"}:
            return queue_pressure_state

    if not blocked_names:
        return "LOW"

    prior_streaks = _consecutive_name_presence(
        scenario_rows,
        "blocked_promotable_candidate_names",
        blocked_names,
    )
    max_persistent_block_count = max(
        (streak + 1 for streak in prior_streaks.values()),
        default=1,
    )
    if len(blocked_names) >= 2 and max_persistent_block_count >= 3:
        return "HIGH"
    return "MEDIUM"


def _is_blockage_critical(
    *,
    blocked_names: list[str],
    scenario_rows: list[dict],
    health_report: dict | None,
    active_blockers: list[str],
    chaos_count: int,
) -> bool:
    if isinstance(health_report, dict):
        return str(health_report.get("blockage_severity") or "").upper() == "HIGH"

    queue_pressure_state = _derive_queue_pressure_state(
        blocked_names,
        scenario_rows,
        health_report=None,
    )
    critical_blockers = {
        blocker for blocker in active_blockers if blocker in {"GSCE_PHASE_LOCK", "REALM_BIS"}
    }
    if queue_pressure_state == "HIGH":
        return True
    if chaos_count >= 2:
        return True
    return len(critical_blockers) >= 2


def _packet_ready_tickers(
    health_report: dict | None,
    decision_review_state: str,
) -> list[str]:
    if not isinstance(health_report, dict):
        return []
    if decision_review_state not in {"ENTRY_REVIEW_READY", "TRANSITION_REVIEW_READY"}:
        return []

    packet_summary = health_report.get("packet_summary", {})
    if not isinstance(packet_summary, dict):
        return []
    return _normalized_text_list(
        list(packet_summary.get("entry_review_candidate_names", []))
        + list(packet_summary.get("transition_review_candidate_names", []))
    )


def _operator_hold_tickers(
    health_report: dict | None,
    decision_review_state: str,
) -> list[str]:
    if not isinstance(health_report, dict):
        return []
    if decision_review_state != "BLOCKED_BY_CONFLICT":
        return []

    tickers: list[str] = []
    for key in ("entry_review_packets", "transition_review_packets"):
        packets = health_report.get(key, [])
        if not isinstance(packets, list):
            continue
        for packet in packets:
            if not isinstance(packet, dict):
                continue
            if str(packet.get("operator_decision_state") or "").upper() != "BLOCKED_BY_CONFLICT":
                continue
            ticker = str(packet.get("ticker") or "").upper()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
    return tickers


def _previous_tag_index(previous_row: dict | None) -> dict[tuple[str, str, str, str], dict]:
    if not isinstance(previous_row, dict):
        return {}

    index: dict[tuple[str, str, str, str], dict] = {}
    for tag in previous_row.get("tags", []):
        if not isinstance(tag, dict):
            continue
        key = (
            str(tag.get("tag_code") or "").upper(),
            str(tag.get("entity_scope") or "").upper(),
            str(tag.get("entity_id") or "").upper(),
            str(tag.get("scenario_scope") or "").upper(),
        )
        if all(key):
            index[key] = tag
    return index


def _build_tag(
    *,
    tag_code: str,
    entity_scope: str,
    entity_id: str,
    scenario_scope: str,
    current_timestamp: str,
    previous_tag_index: dict[tuple[str, str, str, str], dict],
) -> dict:
    metadata = TAG_METADATA[tag_code]
    normalized_scope = str(entity_scope or "").upper()
    normalized_entity_id = str(entity_id or "").upper()
    normalized_scenario_scope = str(scenario_scope or "LIVE").upper()
    key = (
        tag_code,
        normalized_scope,
        normalized_entity_id,
        normalized_scenario_scope,
    )
    previous_tag = previous_tag_index.get(key, {})
    first_seen_at = str(previous_tag.get("first_seen_at") or current_timestamp)

    return {
        "tag_code": tag_code,
        "family": metadata["family"],
        "entity_scope": normalized_scope,
        "entity_id": normalized_entity_id,
        "scenario_scope": normalized_scenario_scope,
        "severity": metadata["severity"],
        "persistence": metadata["persistence"],
        "veto_capable": metadata["veto_capable"],
        "status": "ACTIVE",
        "first_seen_at": first_seen_at,
        "last_seen_at": current_timestamp,
    }


def _build_tags(
    *,
    state: dict,
    health_report: dict | None,
    scenario: str,
    current_timestamp: str,
    scenario_rows: list[dict],
    previous_row: dict | None,
    transition_state_rows: list[dict],
    blocked_names: list[str],
    status_counts: dict,
) -> list[dict]:
    previous_tag_index = _previous_tag_index(previous_row)
    active_blockers = _normalized_text_list(list(state.get("active_blockers", [])))
    decision_review_state = (
        str(health_report.get("decision_review_state") or "NONE").upper()
        if isinstance(health_report, dict)
        else "NONE"
    )
    queue_pressure_state = _derive_queue_pressure_state(
        blocked_names,
        scenario_rows,
        health_report=health_report,
    )
    chaos_count = int(status_counts.get("EXECUTED_CHAOS", 0) or 0)
    watchlist_rows = _watchlist_rows_from_state(state)

    tags: list[dict] = []

    def add_tag(tag_code: str, entity_scope: str, entity_id: str) -> None:
        tags.append(
            _build_tag(
                tag_code=tag_code,
                entity_scope=entity_scope,
                entity_id=entity_id,
                scenario_scope=scenario,
                current_timestamp=current_timestamp,
                previous_tag_index=previous_tag_index,
            )
        )

    for blocker, tag_code in (
        ("GSCE_PHASE_LOCK", "GATE_GSCE_PHASE_LOCK_ACTIVE"),
        ("REALM_BIS", "GATE_REALM_BIS_ACTIVE"),
    ):
        if blocker in active_blockers:
            add_tag(tag_code, "SYSTEM", SYSTEM_ENTITY_ID)

    add_tag(f"QUEUE_PRESSURE_{queue_pressure_state}", "SYSTEM", SYSTEM_ENTITY_ID)

    if _is_blockage_critical(
        blocked_names=blocked_names,
        scenario_rows=scenario_rows,
        health_report=health_report,
        active_blockers=active_blockers,
        chaos_count=chaos_count,
    ):
        add_tag("BLOCKAGE_CRITICAL", "SYSTEM", SYSTEM_ENTITY_ID)

    for ticker in _operator_hold_tickers(health_report, decision_review_state):
        add_tag("OPERATOR_HOLD", "TICKER", ticker)

    for ticker in _packet_ready_tickers(health_report, decision_review_state):
        add_tag("TRANSITION_PACKET_READY", "TICKER", ticker)

    for row in watchlist_rows:
        if not isinstance(row, dict):
            continue

        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue

        watchlist_tier = str(row.get("watchlist_tier") or "").upper()
        pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()
        blocker_attribution = str(row.get("blocker_attribution") or "").upper()

        if watchlist_tier == "PROMOTABLE":
            add_tag("PROMOTABLE_BY_CE", "TICKER", ticker)
        if watchlist_tier == "STANDARD":
            add_tag("STANDARD_WATCHLIST", "TICKER", ticker)
        if pre_entry_state in TRANSITION_STATE_RANK:
            add_tag(pre_entry_state, "TICKER", ticker)
        if pre_entry_state == "CLEAN_READY_PENDING_TRIGGER" or blocker_attribution == "REALM_BIS":
            add_tag("BLOCKED_BY_REALM_BIS", "TICKER", ticker)
        if (
            pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
            and (
                blocker_attribution == "GSCE_PHASE_LOCK"
                or ("GSCE_PHASE_LOCK" in active_blockers and blocker_attribution in {"", "NONE"})
            )
        ):
            add_tag("BLOCKED_BY_GSCE", "TICKER", ticker)

    for row in transition_state_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("transition_persistence_direction") or "").upper() != "ADVANCING":
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            add_tag("TRANSITION_PERSISTENCE_ADVANCING", "TICKER", ticker)

    unique_tags: dict[tuple[str, str, str, str], dict] = {}
    for tag in tags:
        key = (
            tag["tag_code"],
            tag["entity_scope"],
            tag["entity_id"],
            tag["scenario_scope"],
        )
        unique_tags[key] = tag
    return sorted(
        unique_tags.values(),
        key=lambda item: (
            item["entity_scope"],
            item["entity_id"],
            item["tag_code"],
        ),
    )


def build_snapshot_row(
    runtime_state: dict | None = None,
    health_report: dict | None = None,
    snapshot_path=SNAPSHOT_LOG_PATH,
) -> dict:
    state = runtime_state or load_current_pipeline_state()
    snapshot_target = snapshot_path or SNAPSHOT_LOG_PATH
    current_timestamp = _unique_snapshot_timestamp(snapshot_target)
    scenario = (
        str(health_report.get("simulation_mode") or "").upper()
        if isinstance(health_report, dict)
        else str(state.get("simulation_context", {}).get("scenario") or "LIVE").upper()
    )
    if not scenario:
        scenario = "LIVE"
    scenario_rows = _load_snapshot_rows(snapshot_target, scenario=scenario)
    previous_row = scenario_rows[-1] if scenario_rows else None
    status_counts = state["signal_summary"].get("status_counts_above_threshold", {})
    watchlist_intelligence = (
        health_report.get("watchlist_intelligence", {})
        if isinstance(health_report, dict)
        else _summarize_watchlist_intelligence_from_state(state)
    )
    blocked_queue_names = (
        _normalized_text_list(
            [
                item.get("ticker")
                for item in health_report.get("blocked_promotable_candidate_queue", [])
                if isinstance(item, dict)
            ]
        )
        if isinstance(health_report, dict)
        else _watchlist_names_by_pre_entry_state(state, "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE")
    )
    decision_review_state = (
        str(health_report.get("decision_review_state") or "NONE").upper()
        if isinstance(health_report, dict)
        else "NONE"
    )
    base_tags = _build_tags(
        state=state,
        health_report=health_report if isinstance(health_report, dict) else None,
        scenario=scenario,
        current_timestamp=current_timestamp,
        scenario_rows=scenario_rows,
        previous_row=previous_row,
        transition_state_rows=[],
        blocked_names=blocked_queue_names,
        status_counts=status_counts,
    )
    transition_state_rows = _transition_state_rows_from_tags(
        state,
        base_tags,
        previous_row=previous_row,
    )
    tags = _build_tags(
        state=state,
        health_report=health_report if isinstance(health_report, dict) else None,
        scenario=scenario,
        current_timestamp=current_timestamp,
        scenario_rows=scenario_rows,
        previous_row=previous_row,
        transition_state_rows=transition_state_rows,
        blocked_names=blocked_queue_names,
        status_counts=status_counts,
    )
    blocked_names = _transition_state_names_by_pre_entry_state(
        transition_state_rows,
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
    )
    clean_ready_names = _transition_state_names_by_pre_entry_state(
        transition_state_rows,
        "CLEAN_READY_PENDING_TRIGGER",
    )
    clean_entry_eligible_names = _transition_state_names_by_pre_entry_state(
        transition_state_rows,
        "CLEAN_ENTRY_ELIGIBLE",
    )
    if isinstance(health_report, dict):
        packet_summary = health_report.get("packet_summary", {})
        transition_review_candidate_names = list(
            packet_summary.get("transition_review_candidate_names", [])
        )
        entry_review_candidate_names = list(
            packet_summary.get("entry_review_candidate_names", [])
        )
    else:
        transition_review_candidate_names = list(clean_ready_names)
        entry_review_candidate_names = (
            list(clean_entry_eligible_names)
            if state["execution_policy"].get("allow_new_risk", False)
            else []
        )

    return {
        "timestamp": current_timestamp,
        "scenario": scenario,
        "scm_rate": state["scm_review"]["scm_rate"],
        "scm_state": state["scm_review"]["scm_state"],
        "blockers_active": state["active_blockers"],
        "policy_state": state["execution_policy"]["policy_state"],
        "decision_review_state": decision_review_state,
        "allow_new_risk": state["execution_policy"].get("allow_new_risk", False),
        "clean_entries": state["moltbook_summary"].get("clean_entries", 0),
        "chaos_entries": state["moltbook_summary"].get("chaos_entries", 0),
        "signals_above_threshold": state["signal_summary"].get("signals_above_ce_threshold", 0),
        "watchlist_count": status_counts.get("WATCHLIST", 0),
        "chaos_count": status_counts.get("EXECUTED_CHAOS", 0),
        "blocked_promotable_candidate_count": len(blocked_names),
        "blocked_promotable_candidate_names": blocked_names,
        "promotable_watchlist_count": watchlist_intelligence.get("promotable_watchlist_count", 0),
        "promotable_watchlist_names": watchlist_intelligence.get("promotable_watchlist_names", []),
        "standard_watchlist_count": watchlist_intelligence.get("standard_watchlist_count", 0),
        "standard_watchlist_names": watchlist_intelligence.get("standard_watchlist_names", []),
        "clean_ready_pending_trigger_count": len(clean_ready_names),
        "clean_ready_pending_trigger_names": clean_ready_names,
        "clean_entry_eligible_count": len(clean_entry_eligible_names),
        "clean_entry_eligible_names": clean_entry_eligible_names,
        "transition_review_candidate_count": len(transition_review_candidate_names),
        "transition_review_candidate_names": transition_review_candidate_names,
        "entry_review_candidate_count": len(entry_review_candidate_names),
        "entry_review_candidate_names": entry_review_candidate_names,
        "tags": tags,
        "transition_state_rows": transition_state_rows,
    }


def log_snapshot(path=SNAPSHOT_LOG_PATH, runtime_state: dict | None = None, health_report: dict | None = None) -> dict:
    target_path = path or SNAPSHOT_LOG_PATH
    row = build_snapshot_row(
        runtime_state=runtime_state,
        health_report=health_report,
        snapshot_path=target_path,
    )
    append_jsonl(target_path, row)
    return row


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append a deterministic system snapshot row to JSONL.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    parser.parse_args(argv)
    print(json.dumps(log_snapshot(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
