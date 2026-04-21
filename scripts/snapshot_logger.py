from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

try:
    from scripts.runtime_common import (
        LOG_DIR,
        SNAPSHOT_LOG_PATH,
        append_jsonl,
        get_run_id,
        load_current_pipeline_state,
    )
    from scripts.chronology_store import (
        get_connection as _chronology_get_connection,
        init_schema as _chronology_init_schema,
        log_observation as _chronology_log_observation,
        log_snapshot as _chronology_log_snapshot,
    )
except ModuleNotFoundError:
    from runtime_common import (
        LOG_DIR,
        SNAPSHOT_LOG_PATH,
        append_jsonl,
        get_run_id,
        load_current_pipeline_state,
    )
    from chronology_store import (
        get_connection as _chronology_get_connection,
        init_schema as _chronology_init_schema,
        log_observation as _chronology_log_observation,
        log_snapshot as _chronology_log_snapshot,
    )


DEFAULT_CHRONOLOGY_DB_PATH = LOG_DIR / "observation.db"


def _write_chronology_from_snapshot(row: dict, db_path=None) -> None:
    """Passively persist a snapshot row to the chronology DB.

    Writes two rows per snapshot:
      * one row in the snapshots table holding the full snapshot payload
      * one row in the observations table holding a compact metadata view
        keyed by source='snapshot_logger'

    Must never raise: chronology is a side observer of the runtime. If the
    DB can't be opened or any write fails, we print one line to stderr and
    return silently so the runtime continues.
    """
    target = db_path or DEFAULT_CHRONOLOGY_DB_PATH
    try:
        conn = _chronology_get_connection(target)
    except Exception as exc:
        print(
            f"[snapshot_logger] chronology open failed ({target}): {exc}",
            file=sys.stderr,
        )
        return
    try:
        _chronology_init_schema(conn)
        run_id = get_run_id()
        _chronology_log_snapshot(conn, run_id=run_id, snapshot=row)
        observation_payload = {
            "snapshot_ts": row.get("timestamp"),
            "scenario": row.get("scenario"),
            "scm_state": row.get("scm_state"),
            "policy_state": row.get("policy_state"),
            "active_blockers": row.get("blockers_active"),
            "blocked_promotable_count": row.get(
                "blocked_promotable_candidate_count"
            ),
        }
        _chronology_log_observation(
            conn,
            {
                "ts": str(row.get("timestamp", "")),
                "source": "snapshot_logger",
                "payload_json": json.dumps(observation_payload, sort_keys=True),
                "run_id": run_id,
            },
        )
    except Exception as exc:
        print(
            f"[snapshot_logger] chronology write skipped: {exc}",
            file=sys.stderr,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _watchlist_names_by_pre_entry_state(state: dict, pre_entry_state: str) -> list[str]:
    diagnostics = state.get("watchlist_diagnostics", {})
    watchlist_rows = diagnostics.get("watchlist_signals", []) if isinstance(diagnostics, dict) else []
    if not isinstance(watchlist_rows, list):
        return []

    target_state = pre_entry_state.upper()
    names: list[str] = []
    for row in watchlist_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("pre_entry_state") or "NONE").upper() != target_state:
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker and ticker not in names:
            names.append(ticker)
    return names


def _transition_state_rows_from_state(state: dict) -> list[dict]:
    diagnostics = state.get("watchlist_diagnostics", {})
    watchlist_rows = diagnostics.get("watchlist_signals", []) if isinstance(diagnostics, dict) else []
    if not isinstance(watchlist_rows, list):
        return []

    tracked_states = {
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
        "CLEAN_READY_PENDING_TRIGGER",
        "CLEAN_ENTRY_ELIGIBLE",
    }
    rows: list[dict] = []
    for row in watchlist_rows:
        if not isinstance(row, dict):
            continue
        pre_entry_state = str(row.get("pre_entry_state") or "NONE").upper()
        if pre_entry_state not in tracked_states:
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        rows.append(
            {
                "signal_id": str(row.get("signal_id") or ""),
                "ticker": ticker,
                "watchlist_tier": str(row.get("watchlist_tier") or "").upper(),
                "candidate_conversion_state": str(
                    row.get("candidate_conversion_state") or ""
                ).upper(),
                "pre_entry_state": pre_entry_state,
            }
        )
    rows.sort(key=lambda item: (item["pre_entry_state"], item["ticker"]))
    return rows


def _summarize_watchlist_intelligence_from_state(state: dict) -> dict:
    diagnostics = state.get("watchlist_diagnostics", {})
    watchlist_rows = diagnostics.get("watchlist_signals", []) if isinstance(diagnostics, dict) else []
    if not isinstance(watchlist_rows, list):
        watchlist_rows = []

    promotable_names: list[str] = []
    standard_names: list[str] = []
    for row in watchlist_rows:
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


def build_snapshot_row(
    runtime_state: dict | None = None,
    health_report: dict | None = None,
    snapshot_path=SNAPSHOT_LOG_PATH,
) -> dict:
    state = runtime_state or load_current_pipeline_state()
    snapshot_target = snapshot_path or SNAPSHOT_LOG_PATH
    scenario = (
        str(health_report.get("simulation_mode") or "").upper()
        if isinstance(health_report, dict)
        else str(state.get("simulation_context", {}).get("scenario") or "LIVE").upper()
    )
    if not scenario:
        scenario = "LIVE"
    status_counts = state["signal_summary"].get("status_counts_above_threshold", {})
    watchlist_intelligence = (
        health_report.get("watchlist_intelligence", {})
        if isinstance(health_report, dict)
        else _summarize_watchlist_intelligence_from_state(state)
    )
    blocked_names = (
        [item["ticker"] for item in health_report.get("blocked_promotable_candidate_queue", [])]
        if isinstance(health_report, dict)
        else _watchlist_names_by_pre_entry_state(state, "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE")
    )
    clean_ready_names = _watchlist_names_by_pre_entry_state(
        state,
        "CLEAN_READY_PENDING_TRIGGER",
    )
    clean_entry_eligible_names = _watchlist_names_by_pre_entry_state(
        state,
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
    transition_state_rows = _transition_state_rows_from_state(state)

    return {
        "timestamp": _unique_snapshot_timestamp(snapshot_target),
        "scenario": scenario,
        "scm_rate": state["scm_review"]["scm_rate"],
        "scm_state": state["scm_review"]["scm_state"],
        "blockers_active": state["active_blockers"],
        "policy_state": state["execution_policy"]["policy_state"],
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
        "transition_state_rows": transition_state_rows,
    }


def log_snapshot(
    path=SNAPSHOT_LOG_PATH,
    runtime_state: dict | None = None,
    health_report: dict | None = None,
    chronology_db_path=None,
) -> dict:
    target_path = path or SNAPSHOT_LOG_PATH
    row = build_snapshot_row(
        runtime_state=runtime_state,
        health_report=health_report,
        snapshot_path=target_path,
    )
    append_jsonl(target_path, row)
    # Passive chronology hook. Never raises; see _write_chronology_from_snapshot.
    _write_chronology_from_snapshot(row, db_path=chronology_db_path)
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
