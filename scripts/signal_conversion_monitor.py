from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.moltbook_loader import load_moltbook_bundle
except ModuleNotFoundError:
    from moltbook_loader import load_moltbook_bundle

SCM_HIGH_CONVERSION = 0.60
SCM_PARTIAL_CONVERSION = 0.30
SCM_LOW_CONVERSION = 0.10
WATCHLIST_PROMOTION_CE_THRESHOLD = 0.65

SIGNAL_LEDGER_REQUIRED_KEYS = {
    "signal_id",
    "ticker",
    "ce_score",
    "above_ce_threshold",
    "status",
}

LEDGER_STATUS_ORDER = (
    "EXECUTED_CLEAN",
    "EXECUTED_CHAOS",
    "WATCHLIST",
    "REJECTED",
)

LEDGER_STATUS_VALUES = set(LEDGER_STATUS_ORDER)

QUALIFYING_STATUS_TO_ATTRIBUTION = {
    "EXECUTED_CLEAN": {"conversion_state": "CLEAN_ENTRY", "blocker_attribution": "NONE"},
    "EXECUTED_CHAOS": {"conversion_state": "CHAOS_ENTRY", "blocker_attribution": "REALM_BIS"},
    "WATCHLIST": {"conversion_state": "NOT_EXECUTED", "blocker_attribution": "GSCE_PHASE_LOCK"},
}

DIAGNOSTIC_ROUTING_ORDER = [
    "GSCE_PHASE_LOCK",
    "CEE_OVERLOAD",
    "MTL_TIMING",
    "NAR_ARCHETYPE",
    "TAT_PRESSURE_STATE",
    "REALM_BIS",
]

REPO_ROOT = Path(__file__).resolve().parents[1]
MOLTBOOK_DIR = REPO_ROOT / "moltbook"
SIGNAL_LEDGER_PATH = MOLTBOOK_DIR / "signal_ledger.json"


def _append_unique(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)


def _require_non_empty_text(value: object, context: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")


def _copy_rows(rows: list[dict]) -> list[dict]:
    return [dict(item) for item in rows if isinstance(item, dict)]


def resolve_simulation_context(
    gate_state_overrides: dict[str, bool] | None = None,
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict:
    scenario_flags = {
        "GSCE_CLEAR": bool(simulate_gsce_clear),
        "REALM_BIS_CLEAR": bool(simulate_realm_bis_clear),
        "ALL_CLEAR": bool(simulate_all_clear),
    }
    active_scenarios = [name for name, enabled in scenario_flags.items() if enabled]
    if len(active_scenarios) > 1:
        raise ValueError("Only one simulation scenario may be active at a time.")

    scenario = active_scenarios[0] if active_scenarios else "LIVE"
    effective_gate_state_overrides = dict(gate_state_overrides or {})
    if scenario == "GSCE_CLEAR":
        effective_gate_state_overrides["GSCE_PHASE_LOCK"] = False
    elif scenario == "REALM_BIS_CLEAR":
        effective_gate_state_overrides["REALM_BIS"] = False
    elif scenario == "ALL_CLEAR":
        effective_gate_state_overrides["GSCE_PHASE_LOCK"] = False
        effective_gate_state_overrides["REALM_BIS"] = False

    return {
        "scenario": scenario,
        "is_simulated": scenario != "LIVE",
        "gate_state_overrides": effective_gate_state_overrides,
        "simulate_gsce_clear": scenario in {"GSCE_CLEAR", "ALL_CLEAR"},
        "simulate_realm_bis_clear": scenario in {"REALM_BIS_CLEAR", "ALL_CLEAR"},
        "simulate_all_clear": scenario == "ALL_CLEAR",
    }


def compute_scm_rate(clean_system_entries: int, total_signals_above_threshold: int) -> float:
    if total_signals_above_threshold == 0:
        return 0.0
    return clean_system_entries / total_signals_above_threshold


def classify_scm_state(scm_rate: float) -> str:
    if scm_rate >= SCM_HIGH_CONVERSION:
        return "HIGH_CONVERSION"
    if scm_rate >= SCM_PARTIAL_CONVERSION:
        return "PARTIAL_CONVERSION"
    if scm_rate >= SCM_LOW_CONVERSION:
        return "LOW_CONVERSION"
    return "CONVERSION_FAILURE"


def scm_diagnostic_route(scm_state: str, gate_states: dict[str, bool]) -> list[str] | None:
    if scm_state in ("HIGH_CONVERSION", "PARTIAL_CONVERSION"):
        return None
    blocking_gates = []
    for gate in DIAGNOSTIC_ROUTING_ORDER:
        if gate_states.get(gate, False):
            blocking_gates.append(gate)
    return blocking_gates if blocking_gates else ["UNKNOWN_BLOCKER"]


def scm_review(clean_entries: int, total_signals: int, gate_states: dict[str, bool]) -> dict:
    rate = compute_scm_rate(clean_entries, total_signals)
    state = classify_scm_state(rate)
    diagnosis = scm_diagnostic_route(state, gate_states)
    return {
        "scm_rate": round(rate, 3),
        "scm_state": state,
        "diagnosis": diagnosis,
        "gap_type": "CONVERSION_FRICTION" if state != "HIGH_CONVERSION" else "NONE",
    }


def derive_clean_entries_from_moltbook(moltbook_dir: Path | None = None) -> dict:
    bundle = load_moltbook_bundle(moltbook_dir)

    clean_entries = sum(
        1
        for item in bundle.trade_closes
        if item.get("classification") in {"GOOD_WIN", "MARGINAL_WIN"}
    )
    chaos_entries = sum(
        1
        for item in bundle.trade_closes
        if item.get("classification") == "CHAOS_LOSS"
    )

    return {
        "trade_close_count": len(bundle.trade_closes),
        "mw_signal_count": len(bundle.mw_signals),
        "clean_entries": clean_entries,
        "chaos_entries": chaos_entries,
        "tickers": sorted({item["ticker"] for item in bundle.trade_closes}),
    }


def load_signal_ledger(signal_ledger_path: Path | None = None) -> list[dict]:
    path = signal_ledger_path or SIGNAL_LEDGER_PATH
    if not path.exists():
        raise FileNotFoundError(f"Missing signal ledger: {path}")

    raw = path.read_text(encoding="utf-8-sig")
    payload = json.loads(raw)

    if not isinstance(payload, list):
        raise ValueError("signal_ledger.json must contain a top-level JSON array")

    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"signal_ledger.json item {i} must be an object")
        missing = SIGNAL_LEDGER_REQUIRED_KEYS - set(item.keys())
        if missing:
            raise ValueError(f"signal_ledger.json item {i} missing keys: {sorted(missing)}")
        _require_non_empty_text(item["signal_id"], f"signal_ledger.json item {i} signal_id")
        _require_non_empty_text(item["ticker"], f"signal_ledger.json item {i} ticker")
        if not isinstance(item["above_ce_threshold"], bool):
            raise ValueError(f"signal_ledger.json item {i} above_ce_threshold must be boolean")
        if isinstance(item["ce_score"], bool) or not isinstance(item["ce_score"], (int, float)):
            raise ValueError(f"signal_ledger.json item {i} ce_score must be numeric")
        _require_non_empty_text(item["status"], f"signal_ledger.json item {i} status")
        if item["status"] not in LEDGER_STATUS_VALUES:
            raise ValueError(
                f"signal_ledger.json item {i} status must be one of {sorted(LEDGER_STATUS_VALUES)}"
            )

    return payload


def derive_total_signals_above_threshold(signal_ledger_path: Path | None = None) -> dict:
    ledger = load_signal_ledger(signal_ledger_path)
    qualifying = [item for item in ledger if item["above_ce_threshold"] is True]
    status_counts_above_threshold: dict[str, int] = {}
    qualifying_signals: list[dict] = []

    for item in qualifying:
        status = item["status"]
        status_counts_above_threshold[status] = status_counts_above_threshold.get(status, 0) + 1
        qualifying_signals.append(
            {
                "signal_id": item["signal_id"],
                "ticker": item["ticker"],
                "ce_score": item["ce_score"],
                "status": status,
            }
        )

    ordered_status_counts = {
        status: status_counts_above_threshold[status]
        for status in LEDGER_STATUS_ORDER
        if status in status_counts_above_threshold
    }

    return {
        "signal_count_total": len(ledger),
        "signals_above_ce_threshold": len(qualifying),
        "qualifying_signal_ids": [item["signal_id"] for item in qualifying],
        "status_counts_above_threshold": ordered_status_counts,
        "qualifying_signals": qualifying_signals,
    }


def derive_per_signal_attribution(signal_summary: dict) -> list[dict]:
    attributions: list[dict] = []

    for item in signal_summary.get("qualifying_signals", []):
        status = item["status"]
        if status not in QUALIFYING_STATUS_TO_ATTRIBUTION:
            raise ValueError(f"Unhandled qualifying signal status: {status}")

        mapped = QUALIFYING_STATUS_TO_ATTRIBUTION[status]
        attributions.append(
            {
                "signal_id": item["signal_id"],
                "ticker": item["ticker"],
                "ce_score": round(item["ce_score"], 3),
                "status": status,
                "conversion_state": mapped["conversion_state"],
                "blocker_attribution": mapped["blocker_attribution"],
            }
        )

    return attributions


def _watchlist_row_has_chaos_contamination(item: dict) -> bool:
    blocker_attribution = str(item.get("blocker_attribution") or "").upper()
    status = str(item.get("status") or "").upper()
    conversion_state = str(item.get("conversion_state") or "").upper()
    return (
        blocker_attribution == "REALM_BIS"
        or status == "EXECUTED_CHAOS"
        or conversion_state == "CHAOS_ENTRY"
    )


def derive_watchlist_diagnostics(
    per_signal_attribution: list[dict],
    gate_states: dict[str, bool] | None = None,
) -> dict:
    gate_states = gate_states or {}
    watchlist_signals: list[dict] = []
    promotable_count = 0

    for item in per_signal_attribution:
        if item.get("status") != "WATCHLIST":
            continue

        ce_score = round(item["ce_score"], 3)
        promotable_clean_candidate = ce_score >= WATCHLIST_PROMOTION_CE_THRESHOLD
        if promotable_clean_candidate:
            promotable_count += 1

        watchlist_tier = "PROMOTABLE" if promotable_clean_candidate else "STANDARD"
        if promotable_clean_candidate:
            gsce_phase_lock_active = bool(
                gate_states.get(
                    "GSCE_PHASE_LOCK",
                    str(item.get("blocker_attribution") or "").upper() == "GSCE_PHASE_LOCK",
                )
            )
            realm_bis_active = bool(gate_states.get("REALM_BIS", False))
            blocker_attribution = str(item.get("blocker_attribution") or "").upper()
            can_advance_to_clean_ready = (
                not gsce_phase_lock_active
                and blocker_attribution == "NONE"
                and not _watchlist_row_has_chaos_contamination(item)
            )
            if can_advance_to_clean_ready:
                if realm_bis_active:
                    candidate_conversion_state = "CLEAN_READY_PENDING"
                    pre_entry_state = "CLEAN_READY_PENDING_TRIGGER"
                else:
                    candidate_conversion_state = "CLEAN_ENTRY_ELIGIBLE"
                    pre_entry_state = "CLEAN_ENTRY_ELIGIBLE"
            else:
                candidate_conversion_state = "PROMOTABLE_WATCHLIST"
                pre_entry_state = "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
        else:
            candidate_conversion_state = "NOT_EXECUTED"
            pre_entry_state = "NONE"

        watchlist_signals.append(
            {
                "signal_id": item["signal_id"],
                "ticker": item["ticker"],
                "ce_score": ce_score,
                "blocker_attribution": item["blocker_attribution"],
                "promotable_clean_candidate": promotable_clean_candidate,
                "watchlist_tier": watchlist_tier,
                "candidate_conversion_state": candidate_conversion_state,
                "pre_entry_state": pre_entry_state,
            }
        )

    return {
        "promotion_threshold_ce_score": WATCHLIST_PROMOTION_CE_THRESHOLD,
        "promotable_count": promotable_count,
        "watchlist_signals": watchlist_signals,
    }


def derive_gate_states_from_live_data(
    per_signal_attribution: list[dict],
    gate_state_overrides: dict[str, bool] | None = None,
) -> dict:
    blockers = {item["blocker_attribution"] for item in per_signal_attribution}
    gate_states = {
        "GSCE_PHASE_LOCK": "GSCE_PHASE_LOCK" in blockers,
        "CEE_OVERLOAD": False,
        "MTL_TIMING": False,
        "NAR_ARCHETYPE": False,
        "TAT_PRESSURE_STATE": False,
        "REALM_BIS": "REALM_BIS" in blockers,
    }
    if isinstance(gate_state_overrides, dict):
        for gate, value in gate_state_overrides.items():
            if gate in gate_states and isinstance(value, bool):
                gate_states[gate] = value
    return gate_states


def apply_gate_simulation_to_per_signal_attribution(
    per_signal_attribution: list[dict],
    derived_gate_states: dict[str, bool],
    simulation_context: dict[str, Any] | None = None,
) -> list[dict]:
    rows = _copy_rows(per_signal_attribution)
    simulation_context = simulation_context or {}
    if not simulation_context.get("simulate_gsce_clear", False):
        return rows

    gsce_phase_lock_active = bool(derived_gate_states.get("GSCE_PHASE_LOCK", False))
    if gsce_phase_lock_active:
        return rows

    adjusted_rows: list[dict] = []
    for row in rows:
        adjusted = dict(row)
        if (
            str(adjusted.get("status") or "").upper() == "WATCHLIST"
            and str(adjusted.get("blocker_attribution") or "").upper() == "GSCE_PHASE_LOCK"
        ):
            adjusted["blocker_attribution"] = "NONE"
        adjusted_rows.append(adjusted)
    return adjusted_rows


def derive_execution_policy_from_live_data(
    moltbook_summary: dict,
    signal_summary: dict,
    derived_gate_states: dict,
    scm_review_payload: dict,
) -> dict:
    status_counts = signal_summary.get("status_counts_above_threshold", {})
    watchlist_count = status_counts.get("WATCHLIST", 0)
    chaos_count = status_counts.get("EXECUTED_CHAOS", 0)
    clean_entries = moltbook_summary.get("clean_entries", 0)
    total_signals = signal_summary.get("signals_above_ce_threshold", 0)

    policy = {
        "policy_state": "UNRESTRICTED",
        "position_sizing_cap": "SYSTEM_DEFAULT",
        "allow_clean_entries": True,
        "allow_chaos_entries": True,
        "allow_new_risk": True,
        "allow_only_exits_and_reductions": False,
        "retain_watchlist_names": False,
        "chaos_entries_forbidden": False,
        "watchlist_action": "STANDARD_REVIEW",
        "required_clearance_gates": [],
        "blocked_entry_states": [],
        "next_priority_action": "MONITOR_CONVERSION",
        "minimum_conditions_to_improve": [],
        "rationale": [],
    }

    restricted_by_scm = scm_review_payload.get("scm_state") in {
        "LOW_CONVERSION",
        "CONVERSION_FAILURE",
    }
    if restricted_by_scm:
        policy["policy_state"] = "REVIEW_READY"
        policy["position_sizing_cap"] = "QUARTER_UNIT"
        policy["retain_watchlist_names"] = True
        policy["watchlist_action"] = "REVIEW_FOR_ENTRY"
        policy["next_priority_action"] = "REVIEW_PROMOTABLE_CANDIDATES"
        policy["rationale"].append(
            f"{clean_entries} clean entries across {total_signals} above-threshold signals"
        )
        policy["rationale"].append("SCM rate remains below PARTIAL_CONVERSION threshold")
        _append_unique(
            policy["minimum_conditions_to_improve"],
            "SCM state improves to PARTIAL_CONVERSION or better",
        )

    if derived_gate_states.get("GSCE_PHASE_LOCK", False):
        policy["policy_state"] = "RESTRICTED"
        policy["position_sizing_cap"] = "QUARTER_UNIT"
        policy["allow_clean_entries"] = False
        policy["allow_new_risk"] = False
        policy["allow_only_exits_and_reductions"] = True
        policy["retain_watchlist_names"] = True
        policy["watchlist_action"] = "DO_NOT_FORCE_ENTRY"
        _append_unique(policy["required_clearance_gates"], "GSCE_PHASE_LOCK")
        _append_unique(
            policy["minimum_conditions_to_improve"],
            "GSCE_PHASE_LOCK clears for above-threshold WATCHLIST names",
        )
        policy["rationale"].append(f"{watchlist_count} above-threshold signals remained WATCHLIST")

    if derived_gate_states.get("REALM_BIS", False):
        policy["policy_state"] = "RESTRICTED"
        policy["position_sizing_cap"] = "QUARTER_UNIT"
        policy["allow_chaos_entries"] = False
        policy["allow_new_risk"] = False
        policy["allow_only_exits_and_reductions"] = True
        policy["chaos_entries_forbidden"] = True
        _append_unique(policy["blocked_entry_states"], "EXECUTED_CHAOS")
        _append_unique(policy["required_clearance_gates"], "REALM_BIS")
        _append_unique(
            policy["minimum_conditions_to_improve"],
            "REALM_BIS clears by eliminating chaos conversions",
        )
        policy["rationale"].append(
            f"{chaos_count} above-threshold signals converted into CHAOS entries"
        )

    if derived_gate_states.get("GSCE_PHASE_LOCK", False) and derived_gate_states.get("REALM_BIS", False):
        policy["next_priority_action"] = "CLEAR_BLOCKERS_BEFORE_NEW_RISK"
    elif derived_gate_states.get("GSCE_PHASE_LOCK", False):
        policy["next_priority_action"] = "CLEAR_GSCE_PHASE_LOCK"
    elif derived_gate_states.get("REALM_BIS", False):
        policy["next_priority_action"] = "ELIMINATE_REALM_BIS"
    elif restricted_by_scm:
        policy["next_priority_action"] = "REVIEW_PROMOTABLE_CANDIDATES"

    return policy


def build_signal_conversion_report(
    moltbook_dir: Path | None = None,
    signal_ledger_path: Path | None = None,
    gate_state_overrides: dict[str, bool] | None = None,
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict:
    moltbook_summary = derive_clean_entries_from_moltbook(moltbook_dir)
    signal_summary = derive_total_signals_above_threshold(signal_ledger_path)
    base_per_signal_attribution = derive_per_signal_attribution(signal_summary)
    simulation_context = resolve_simulation_context(
        gate_state_overrides=gate_state_overrides,
        simulate_gsce_clear=simulate_gsce_clear,
        simulate_realm_bis_clear=simulate_realm_bis_clear,
        simulate_all_clear=simulate_all_clear,
    )
    gate_states = derive_gate_states_from_live_data(
        base_per_signal_attribution,
        gate_state_overrides=simulation_context["gate_state_overrides"],
    )
    per_signal_attribution = apply_gate_simulation_to_per_signal_attribution(
        base_per_signal_attribution,
        gate_states,
        simulation_context=simulation_context,
    )
    watchlist_diagnostics = derive_watchlist_diagnostics(
        per_signal_attribution,
        gate_states=gate_states,
    )

    review = scm_review(
        clean_entries=moltbook_summary["clean_entries"],
        total_signals=signal_summary["signals_above_ce_threshold"],
        gate_states=gate_states,
    )
    execution_policy = derive_execution_policy_from_live_data(
        moltbook_summary=moltbook_summary,
        signal_summary=signal_summary,
        derived_gate_states=gate_states,
        scm_review_payload=review,
    )

    return {
        "moltbook_summary": moltbook_summary,
        "signal_summary": signal_summary,
        "per_signal_attribution": per_signal_attribution,
        "watchlist_diagnostics": watchlist_diagnostics,
        "derived_gate_states": gate_states,
        "scm_review": review,
        "execution_policy": execution_policy,
        "simulation_context": simulation_context,
        "note": "SCM now consumes live Moltbook close data for numerator and signal_ledger.json for denominator.",
    }


def format_signal_conversion_summary(report: dict) -> str:
    scm_payload = report["scm_review"]
    policy = report["execution_policy"]
    status_counts = report["signal_summary"]["status_counts_above_threshold"]
    gates = [gate for gate, is_active in report["derived_gate_states"].items() if is_active] or ["NONE"]
    return "\n".join(
        [
            "Signal Conversion Monitor",
            f"scm_state={scm_payload['scm_state']}",
            f"scm_rate={scm_payload['scm_rate']}",
            f"clean_entries={report['moltbook_summary']['clean_entries']}",
            f"chaos_entries={report['moltbook_summary']['chaos_entries']}",
            f"watchlist_non_conversions={status_counts.get('WATCHLIST', 0)}",
            f"active_gates={', '.join(gates)}",
            f"policy_state={policy['policy_state']}",
            f"allow_new_risk={str(policy['allow_new_risk']).lower()}",
            f"next_priority_action={policy['next_priority_action']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the live SCM runtime report.")
    parser.add_argument(
        "--moltbook-dir",
        type=Path,
        default=MOLTBOOK_DIR,
        help="Override the Moltbook directory path.",
    )
    parser.add_argument(
        "--signal-ledger",
        type=Path,
        default=SIGNAL_LEDGER_PATH,
        help="Override the signal ledger path.",
    )
    simulation = parser.add_mutually_exclusive_group()
    simulation.add_argument(
        "--simulate-gsce-clear",
        action="store_true",
        help="Preview watchlist transition state as if GSCE_PHASE_LOCK were cleared. Does not mutate source data.",
    )
    simulation.add_argument(
        "--simulate-realm-bis-clear",
        action="store_true",
        help="Preview diagnostics as if REALM_BIS were cleared. Does not mutate source data.",
    )
    simulation.add_argument(
        "--simulate-all-clear",
        action="store_true",
        help="Preview diagnostics as if GSCE_PHASE_LOCK and REALM_BIS were both cleared. Does not mutate source data.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    report = build_signal_conversion_report(
        moltbook_dir=args.moltbook_dir,
        signal_ledger_path=args.signal_ledger,
        simulate_gsce_clear=args.simulate_gsce_clear,
        simulate_realm_bis_clear=args.simulate_realm_bis_clear,
        simulate_all_clear=args.simulate_all_clear,
    )
    if args.summary:
        print(format_signal_conversion_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
