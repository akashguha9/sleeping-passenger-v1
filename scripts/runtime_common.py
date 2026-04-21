from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MOLTBOOK_DIR = REPO_ROOT / "moltbook"
OPEN_POSITIONS_PATH = MOLTBOOK_DIR / "open_positions.json"
SIGNAL_LEDGER_PATH = MOLTBOOK_DIR / "signal_ledger.json"

LOG_DIR = REPO_ROOT / "logs"
SNAPSHOT_LOG_PATH = LOG_DIR / "system_snapshots.jsonl"

RUNTIME_DIR = REPO_ROOT / "runtime"
SCM_REPORT_PATH = RUNTIME_DIR / "scm_report.json"
DERIVED_GATE_STATES_PATH = RUNTIME_DIR / "derived_gate_states.json"
EXECUTION_POLICY_PATH = RUNTIME_DIR / "execution_policy.json"
PER_SIGNAL_ATTRIBUTION_PATH = RUNTIME_DIR / "per_signal_attribution.json"
ACTION_REPORT_PATH = RUNTIME_DIR / "action_report.json"
BLOCKER_COST_REPORT_PATH = RUNTIME_DIR / "blocker_cost_report.json"
TREND_REPORT_PATH = RUNTIME_DIR / "trend_report.json"
HEALTH_REPORT_PATH = RUNTIME_DIR / "pipeline_health_report.json"
SIGNAL_VOCODER_REPORT_PATH = RUNTIME_DIR / "signal_vocoder_report.json"
SIGNAL_VOCODER_ETIL_INPUT_PATH = RUNTIME_DIR / "signal_vocoder_etil_inputs.json"
QUOTE_CACHE_DIR = RUNTIME_DIR / "quote_cache"

CONFIG_DIR = REPO_ROOT / "config"
BLOCKER_WEIGHTS_PATH = CONFIG_DIR / "blocker_weights.json"

OPEN_POSITION_REQUIRED_KEYS = {
    "ticker",
    "entry_price",
    "current_price",
    "pnl_pct",
    "position_size",
    "state",
    "chaos_flag",
    "entry_type",
    "thesis_cluster",
    "stop_loss",
    "take_profit",
    "time_in_trade",
    "priority_score",
}
OPEN_POSITION_STATES = {"OPEN", "REDUCED", "EXIT_PENDING", "CLOSED"}
OPEN_POSITION_ENTRY_TYPES = {"CLEAN", "CHAOS"}

POLICY_STATE_RANK = {
    "BLOCKED": 0,
    "DO_NOT_DEPLOY": 0,
    "RESTRICTED": 1,
    "NOT_READY": 1,
    "LIMITED_DEPLOY": 2,
    "PARTIAL": 2,
    "REVIEW_READY": 2,
    "NORMAL": 3,
    "UNRESTRICTED": 3,
    "READY": 3,
}
PERMISSIVE_POLICY_STATES = {
    "READY",
    "UNRESTRICTED",
    "NORMAL",
    "LIMITED_DEPLOY",
    "REVIEW_READY",
}


def repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json_file(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return default
    return json.loads(raw)


def write_json_atomic(path: Path, payload: Any) -> None:
    ensure_directory(path.parent)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def _coerce_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def normalize_active_blockers(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return sorted({_text(item) for item in payload if _text(item)})
    if isinstance(payload, dict):
        if isinstance(payload.get("active_blockers"), list):
            return normalize_active_blockers(payload["active_blockers"])
        blockers = []
        for key, value in payload.items():
            if isinstance(value, bool) and value:
                blockers.append(str(key))
        return sorted(set(blockers))
    return []


def normalize_gate_state_map(payload: Any) -> dict[str, bool]:
    blockers = normalize_active_blockers(payload)
    if isinstance(payload, dict) and "active_blockers" not in payload:
        result = {}
        for key, value in payload.items():
            if isinstance(value, bool):
                result[str(key)] = value
        for blocker in blockers:
            result[blocker] = True
        return result
    return {blocker: True for blocker in blockers}


def normalize_execution_policy(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("execution_policy"), dict):
        payload = payload["execution_policy"]
    if isinstance(payload, dict):
        raw_state = (
            payload.get("policy_state")
            or payload.get("state")
            or payload.get("execution_policy")
            or "UNKNOWN"
        )
        policy_state = _text(raw_state, "UNKNOWN").upper()
        allow_new_risk = payload.get("allow_new_risk")
        if allow_new_risk is None:
            allow_new_risk = policy_state in PERMISSIVE_POLICY_STATES
        allow_clean_entries = payload.get("allow_clean_entries")
        if allow_clean_entries is None:
            allow_clean_entries = _coerce_bool(allow_new_risk, False)
        allow_chaos_entries = payload.get("allow_chaos_entries")
        if allow_chaos_entries is None:
            allow_chaos_entries = _coerce_bool(allow_new_risk, False)
        return {
            "policy_state": policy_state,
            "position_sizing_cap": _text(payload.get("position_sizing_cap"), "SYSTEM_DEFAULT"),
            "allow_clean_entries": _coerce_bool(allow_clean_entries, False),
            "allow_chaos_entries": _coerce_bool(allow_chaos_entries, False),
            "allow_new_risk": _coerce_bool(allow_new_risk, False),
            "allow_only_exits_and_reductions": _coerce_bool(
                payload.get("allow_only_exits_and_reductions"),
                policy_state in {"RESTRICTED", "BLOCKED", "DO_NOT_DEPLOY", "NOT_READY"},
            ),
            "retain_watchlist_names": _coerce_bool(payload.get("retain_watchlist_names"), False),
            "chaos_entries_forbidden": _coerce_bool(
                payload.get("chaos_entries_forbidden"),
                not _coerce_bool(allow_chaos_entries, False),
            ),
            "watchlist_action": _text(payload.get("watchlist_action"), "MONITOR"),
            "required_clearance_gates": [
                _text(item)
                for item in payload.get("required_clearance_gates", [])
                if _text(item)
            ],
            "blocked_entry_states": [
                _text(item)
                for item in payload.get("blocked_entry_states", [])
                if _text(item)
            ],
            "next_priority_action": _text(
                payload.get("next_priority_action"), "MONITOR_CONVERSION"
            ),
            "minimum_conditions_to_improve": [
                _text(item)
                for item in payload.get("minimum_conditions_to_improve", [])
                if _text(item)
            ],
            "rationale": [
                _text(item)
                for item in payload.get("rationale", [])
                if _text(item)
            ],
        }
    if isinstance(payload, str):
        return normalize_execution_policy({"policy_state": payload})
    return normalize_execution_policy({"policy_state": "UNKNOWN"})


def _infer_entry_type(row: dict[str, Any]) -> str:
    explicit = _text(row.get("entry_type")).upper()
    if explicit in OPEN_POSITION_ENTRY_TYPES:
        return explicit
    status = _text(row.get("status")).upper()
    state = _text(row.get("state")).upper()
    conversion_state = _text(row.get("conversion_state")).upper()
    if "CHAOS" in explicit or "CHAOS" in status or "CHAOS" in state or "CHAOS" in conversion_state:
        return "CHAOS"
    if "CLEAN" in explicit or "CLEAN" in status or "CLEAN" in state or "CLEAN" in conversion_state:
        return "CLEAN"
    return "UNKNOWN"


def _infer_signal_state(row: dict[str, Any]) -> str:
    for key in ("signal_state", "state", "status", "conversion_state"):
        value = _text(row.get(key)).upper()
        if not value:
            continue
        if value in {"WATCHLIST", "NOT_EXECUTED"}:
            return "WATCHLIST"
        if value in {"EXECUTED_CLEAN", "EXECUTED_CHAOS", "ACTIVE", "CLEAN_ENTRY", "CHAOS_ENTRY"}:
            return "ACTIVE"
        if value == "REJECTED":
            return "REJECTED"
        return value
    return "UNKNOWN"


def _extract_watchlist_diagnostics_map(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}

    diagnostics = payload.get("watchlist_diagnostics")
    if not isinstance(diagnostics, dict):
        return {}

    watchlist_rows = diagnostics.get("watchlist_signals")
    if not isinstance(watchlist_rows, list):
        return {}

    diagnostics_map: dict[str, dict[str, Any]] = {}
    for row in watchlist_rows:
        if not isinstance(row, dict):
            continue
        signal_id = _text(row.get("signal_id"))
        ticker = _text(row.get("ticker")).upper()
        if signal_id:
            diagnostics_map[signal_id] = row
        if ticker:
            diagnostics_map[ticker] = row
    return diagnostics_map


def normalize_per_signal_rows(payload: Any) -> list[dict[str, Any]]:
    rows_payload = payload
    watchlist_diagnostics_map = _extract_watchlist_diagnostics_map(payload)
    if isinstance(payload, dict):
        for key in ("per_signal_attribution", "signals", "rows"):
            if isinstance(payload.get(key), list):
                rows_payload = payload[key]
                break
    if not isinstance(rows_payload, list):
        return []

    rows: list[dict[str, Any]] = []
    for row in rows_payload:
        if not isinstance(row, dict):
            continue
        signal_id = _text(row.get("signal_id"))
        ticker = _text(row.get("ticker") or row.get("symbol")).upper()
        if not ticker:
            continue

        blocker = _text(row.get("blocker_attribution"), "NONE").upper()
        signal_state = _infer_signal_state(row)
        entry_type = _infer_entry_type(row)
        watchlist_diagnostics = (
            watchlist_diagnostics_map.get(signal_id)
            or watchlist_diagnostics_map.get(ticker)
            or {}
        )
        explicit_watchlist_tier = _text(
            row.get("watchlist_tier"),
            _text(watchlist_diagnostics.get("watchlist_tier")),
        ).upper()
        explicit_candidate_conversion_state = _text(
            row.get("candidate_conversion_state"),
            _text(watchlist_diagnostics.get("candidate_conversion_state")),
        ).upper()
        explicit_pre_entry_state = _text(
            row.get("pre_entry_state"),
            _text(watchlist_diagnostics.get("pre_entry_state")),
        ).upper()
        if (
            blocker == "NONE"
            and signal_state == "WATCHLIST"
            and not explicit_watchlist_tier
            and not explicit_candidate_conversion_state
            and not explicit_pre_entry_state
        ):
            blocker = "GSCE_PHASE_LOCK"

        promotable_clean_candidate = _coerce_bool(
            row.get("promotable_clean_candidate"),
            _coerce_bool(watchlist_diagnostics.get("promotable_clean_candidate"), False),
        )
        watchlist_tier = _text(
            row.get("watchlist_tier"),
            explicit_watchlist_tier,
        ).upper()
        candidate_conversion_state = _text(
            row.get("candidate_conversion_state"),
            explicit_candidate_conversion_state,
        ).upper()
        pre_entry_state = _text(
            row.get("pre_entry_state"),
            explicit_pre_entry_state or "NONE",
        ).upper()

        if signal_state == "WATCHLIST":
            if not watchlist_tier:
                watchlist_tier = "PROMOTABLE" if promotable_clean_candidate else "STANDARD"
            if not candidate_conversion_state:
                candidate_conversion_state = (
                    "PROMOTABLE_WATCHLIST" if promotable_clean_candidate else "NOT_EXECUTED"
                )
            if not pre_entry_state or pre_entry_state == "NONE":
                if promotable_clean_candidate and blocker == "GSCE_PHASE_LOCK":
                    pre_entry_state = "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
                else:
                    pre_entry_state = "NONE"
        else:
            if not watchlist_tier:
                watchlist_tier = "NONE"
            if not candidate_conversion_state:
                candidate_conversion_state = _text(row.get("conversion_state"), signal_state).upper()
            if not pre_entry_state:
                pre_entry_state = "NONE"

        rows.append(
            {
                "signal_id": signal_id,
                "ticker": ticker,
                "entry_type": entry_type,
                "signal_state": signal_state,
                "status": _text(
                    row.get("status") or row.get("state") or row.get("conversion_state"),
                    signal_state,
                ).upper(),
                "blocker_attribution": blocker,
                "priority_score": _coerce_number(
                    row.get("priority_score", row.get("ce_score", row.get("priority", 0.0)))
                ),
                "ce_score": _coerce_number(
                    row.get("ce_score", row.get("priority_score", 0.0))
                ),
                "promotable_clean_candidate": promotable_clean_candidate,
                "watchlist_tier": watchlist_tier,
                "candidate_conversion_state": candidate_conversion_state,
                "pre_entry_state": pre_entry_state,
            }
        )
    rows.sort(key=lambda item: (item["ticker"], -item["priority_score"], item["signal_id"]))
    return rows


def build_signal_summary_from_rows(
    rows: list[dict[str, Any]],
    seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    seed = seed or {}
    status_counts: dict[str, int] = {}
    qualifying_ids = []
    for row in rows:
        status = row["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if row["signal_id"]:
            qualifying_ids.append(row["signal_id"])
    summary = {
        "signal_count_total": int(seed.get("signal_count_total", len(rows))),
        "signals_above_ce_threshold": int(seed.get("signals_above_ce_threshold", len(rows))),
        "qualifying_signal_ids": seed.get("qualifying_signal_ids", qualifying_ids),
        "status_counts_above_threshold": seed.get("status_counts_above_threshold", status_counts),
        "qualifying_signals": seed.get("qualifying_signals", rows),
    }
    if summary["signal_count_total"] < summary["signals_above_ce_threshold"]:
        summary["signal_count_total"] = summary["signals_above_ce_threshold"]
    return summary


def normalize_scm_review(
    payload: Any, active_blockers: list[str] | None = None
) -> dict[str, Any]:
    active_blockers = active_blockers or []
    review_source = payload
    if isinstance(payload, dict) and isinstance(payload.get("scm_review"), dict):
        review_source = payload["scm_review"]
    if isinstance(review_source, dict):
        diagnosis = review_source.get("diagnosis")
        if diagnosis is None and active_blockers:
            diagnosis = active_blockers
        elif isinstance(diagnosis, str):
            diagnosis = [diagnosis]
        elif not isinstance(diagnosis, list):
            diagnosis = []
        return {
            "scm_rate": round(_coerce_number(review_source.get("scm_rate"), 0.0), 3),
            "scm_state": _text(review_source.get("scm_state"), "UNKNOWN").upper(),
            "diagnosis": [_text(item).upper() for item in diagnosis if _text(item)],
            "gap_type": _text(review_source.get("gap_type"), "UNKNOWN"),
        }
    return {
        "scm_rate": 0.0,
        "scm_state": "UNKNOWN",
        "diagnosis": active_blockers,
        "gap_type": "UNKNOWN",
    }


def load_open_positions_payload(path: Path | None = None) -> list[dict[str, Any]]:
    payload = load_json_file(path or OPEN_POSITIONS_PATH, default=[])
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("open_positions.json must contain a top-level JSON array")
    return payload


def validate_open_positions_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, list):
        return ["open_positions.json must contain a top-level JSON array"]
    price_fields = {
        "entry_price",
        "current_price",
        "pnl_pct",
        "stop_loss",
        "take_profit",
        "priority_score",
    }
    for index, item in enumerate(payload):
        context = f"open_positions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{context} must be an object")
            continue
        missing = sorted(OPEN_POSITION_REQUIRED_KEYS - set(item.keys()))
        if missing:
            errors.append(f"{context} missing keys: {missing}")
            continue
        ticker = _text(item.get("ticker")).upper()
        if not ticker:
            errors.append(f"{context}.ticker must be a non-empty string")
        if _text(item.get("state")).upper() not in OPEN_POSITION_STATES:
            errors.append(
                f"{context}.state must be one of {sorted(OPEN_POSITION_STATES)}"
            )
        if _text(item.get("entry_type")).upper() not in OPEN_POSITION_ENTRY_TYPES:
            errors.append(
                f"{context}.entry_type must be one of {sorted(OPEN_POSITION_ENTRY_TYPES)}"
            )
        if not isinstance(item.get("chaos_flag"), bool):
            errors.append(f"{context}.chaos_flag must be boolean")
        if not isinstance(item.get("time_in_trade"), str) or not item["time_in_trade"].strip():
            errors.append(f"{context}.time_in_trade must be a non-empty string")
        if not isinstance(item.get("position_size"), str) or not item["position_size"].strip():
            errors.append(f"{context}.position_size must be a non-empty string")
        if (
            not isinstance(item.get("thesis_cluster"), str)
            or not item["thesis_cluster"].strip()
        ):
            errors.append(f"{context}.thesis_cluster must be a non-empty string")
        for field in price_fields:
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{context}.{field} must be numeric")
    return errors


def load_open_positions(
    path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = path or OPEN_POSITIONS_PATH
    if not target.exists():
        summary = {
            "path": repo_relative(target),
            "file_exists": False,
            "valid": False,
            "position_count": 0,
            "states": {},
            "errors": [f"Missing open positions file: {repo_relative(target)}"],
        }
        return [], summary
    payload = load_json_file(target, default=[])
    errors = validate_open_positions_payload(payload)
    positions: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            position = dict(item)
            position["ticker"] = _text(position.get("ticker")).upper()
            position["state"] = _text(position.get("state")).upper()
            position["entry_type"] = _text(position.get("entry_type")).upper()
            positions.append(position)
    state_counts: dict[str, int] = {}
    for position in positions:
        state = position["state"]
        state_counts[state] = state_counts.get(state, 0) + 1
    summary = {
        "path": repo_relative(target),
        "file_exists": True,
        "valid": len(errors) == 0,
        "position_count": len(positions),
        "states": state_counts,
        "errors": errors,
    }
    return positions, summary


def _load_live_scm_report() -> dict[str, Any] | None:
    try:
        from scripts.signal_conversion_monitor import build_signal_conversion_report
    except ModuleNotFoundError:
        try:
            from signal_conversion_monitor import build_signal_conversion_report
        except ModuleNotFoundError:
            return None
    try:
        return build_signal_conversion_report()
    except Exception:
        return None


def _load_live_moltbook_summary() -> dict[str, Any]:
    # PATCHED: explicit ModuleNotFoundError guard makes this function self-contained.
    # Previously the double-import fallback could propagate ModuleNotFoundError
    # if both 'scripts.moltbook_loader' and 'moltbook_loader' were absent,
    # relying entirely on the call-site try/except Exception in
    # _load_state_from_runtime_files(). This patch mirrors the pattern used
    # by _load_live_scm_report() and eliminates the hidden dependency.
    try:
        from scripts.moltbook_loader import summarize_moltbook
    except ModuleNotFoundError:
        try:
            from moltbook_loader import summarize_moltbook
        except ModuleNotFoundError:
            return {}
    try:
        return summarize_moltbook()
    except Exception:
        return {}


def _build_state_from_live_report(report: dict[str, Any]) -> dict[str, Any]:
    per_signal_rows = normalize_per_signal_rows(report)
    gate_states = normalize_gate_state_map(report.get("derived_gate_states"))
    active_blockers = normalize_active_blockers(gate_states)
    signal_summary = build_signal_summary_from_rows(
        per_signal_rows, report.get("signal_summary")
    )
    return {
        "source": "live_builder",
        "moltbook_summary": report.get("moltbook_summary", {}),
        "signal_summary": signal_summary,
        "per_signal_attribution": per_signal_rows,
        "watchlist_diagnostics": report.get("watchlist_diagnostics", {}),
        "derived_gate_states": gate_states,
        "active_blockers": active_blockers,
        "execution_policy": normalize_execution_policy(report.get("execution_policy")),
        "scm_review": normalize_scm_review(report, active_blockers=active_blockers),
        "simulation_context": report.get("simulation_context", {}),
        "note": report.get("note", ""),
    }


def _load_state_from_runtime_files() -> dict[str, Any]:
    scm_payload = load_json_file(SCM_REPORT_PATH, default={}) or {}
    derived_payload = load_json_file(DERIVED_GATE_STATES_PATH, default={})
    execution_payload = load_json_file(EXECUTION_POLICY_PATH, default={})
    per_signal_payload = load_json_file(PER_SIGNAL_ATTRIBUTION_PATH, default=[])

    normalized_per_signal_payload: dict[str, Any] = {
        "watchlist_diagnostics": scm_payload.get("watchlist_diagnostics", {}),
    }
    if isinstance(per_signal_payload, dict):
        normalized_per_signal_payload.update(per_signal_payload)
    else:
        normalized_per_signal_payload["per_signal_attribution"] = per_signal_payload

    per_signal_rows = normalize_per_signal_rows(normalized_per_signal_payload)
    gate_states = normalize_gate_state_map(
        derived_payload or scm_payload.get("derived_gate_states")
    )
    active_blockers = normalize_active_blockers(gate_states)

    signal_summary_seed = {}
    if isinstance(scm_payload, dict):
        signal_summary_seed = scm_payload.get("signal_summary", {})
        if not isinstance(signal_summary_seed, dict):
            signal_summary_seed = {}
        if (
            "signals_above_threshold" in scm_payload
            and "signals_above_ce_threshold" not in signal_summary_seed
        ):
            signal_summary_seed["signals_above_ce_threshold"] = scm_payload[
                "signals_above_threshold"
            ]
    signal_summary = build_signal_summary_from_rows(per_signal_rows, signal_summary_seed)

    try:
        moltbook_summary = _load_live_moltbook_summary()
    except Exception:
        moltbook_summary = {}

    return {
        "source": "runtime_files",
        "moltbook_summary": moltbook_summary,
        "signal_summary": signal_summary,
        "per_signal_attribution": per_signal_rows,
        "watchlist_diagnostics": scm_payload.get("watchlist_diagnostics", {}),
        "derived_gate_states": gate_states,
        "active_blockers": active_blockers,
        "execution_policy": normalize_execution_policy(
            execution_payload or scm_payload
        ),
        "scm_review": normalize_scm_review(scm_payload, active_blockers=active_blockers),
        "simulation_context": scm_payload.get("simulation_context", {}),
        "note": _text(
            scm_payload.get("note"), "Loaded from normalized runtime files."
        ),
    }


def persist_current_runtime_state(state: dict[str, Any]) -> None:
    scm_payload = {
        "scm_rate": state["scm_review"]["scm_rate"],
        "scm_state": state["scm_review"]["scm_state"],
        "diagnosis": state["scm_review"].get("diagnosis", []),
        "gap_type": state["scm_review"].get("gap_type", "UNKNOWN"),
        "signals_above_threshold": state["signal_summary"].get(
            "signals_above_ce_threshold", 0
        ),
        "signal_summary": state["signal_summary"],
        "moltbook_summary": state["moltbook_summary"],
        "watchlist_diagnostics": state.get("watchlist_diagnostics", {}),
        "derived_gate_states": state["derived_gate_states"],
        "execution_policy": state["execution_policy"],
        "note": state.get("note", ""),
    }
    write_json_atomic(SCM_REPORT_PATH, scm_payload)
    write_json_atomic(DERIVED_GATE_STATES_PATH, state["derived_gate_states"])
    write_json_atomic(EXECUTION_POLICY_PATH, state["execution_policy"])
    write_json_atomic(
        PER_SIGNAL_ATTRIBUTION_PATH,
        {"per_signal_attribution": state["per_signal_attribution"]},
    )


def load_current_pipeline_state(prefer_runtime_files: bool = False) -> dict[str, Any]:
    if prefer_runtime_files:
        runtime_state = _load_state_from_runtime_files()
        if (
            runtime_state["per_signal_attribution"]
            or runtime_state["scm_review"]["scm_state"] != "UNKNOWN"
        ):
            return runtime_state
    live_report = _load_live_scm_report()
    if live_report is not None:
        return _build_state_from_live_report(live_report)
    return _load_state_from_runtime_files()


def build_runtime_state_from_scm_report_payload(scm_report: dict[str, Any]) -> dict[str, Any]:
    derived_gate_states = scm_report.get("derived_gate_states", {})
    return {
        "source": "scm_report",
        "moltbook_summary": scm_report.get("moltbook_summary", {}),
        "signal_summary": scm_report.get("signal_summary", {}),
        "per_signal_attribution": normalize_per_signal_rows(scm_report),
        "watchlist_diagnostics": scm_report.get("watchlist_diagnostics", {}),
        "derived_gate_states": derived_gate_states,
        "active_blockers": normalize_active_blockers(derived_gate_states),
        "execution_policy": scm_report.get("execution_policy", {}),
        "scm_review": scm_report.get("scm_review", {}),
        "simulation_context": scm_report.get("simulation_context", {}),
        "note": scm_report.get("note", ""),
    }


def policy_state_score(policy_state: str) -> int:
    return POLICY_STATE_RANK.get(_text(policy_state).upper(), 0)
