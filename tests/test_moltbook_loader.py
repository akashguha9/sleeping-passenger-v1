import json
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.run_diagnostics_pipeline as run_diagnostics_pipeline_module
from scripts.action_engine import build_action_report
from scripts.moltbook_loader import summarize_moltbook
from scripts.pipeline_health_report import (
    build_entry_review_packets,
    build_pipeline_health_report,
)
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.snapshot_logger import build_snapshot_row
from scripts.signal_conversion_monitor import build_signal_conversion_report, load_signal_ledger
from scripts.trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_moltbook_loader_summary_smoke() -> None:
    summary = summarize_moltbook(REPO_ROOT / "moltbook")

    assert summary["trade_close_count"] == 4
    assert summary["mw_signal_count"] == 1
    assert summary["tickers"] == ["FCG", "TIP", "TLT", "UNG"]
    assert summary["classifications"] == ["CHAOS_LOSS", "GOOD_WIN", "MARGINAL_WIN"]
    assert summary["mw_signal_ids"] == ["MW_DIRECTION_V1_2026_04_19"]


def test_signal_conversion_monitor_runtime_report_uses_live_files() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "signal_conversion_monitor.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)

    assert payload["moltbook_summary"] == {
        "trade_close_count": 4,
        "mw_signal_count": 1,
        "clean_entries": 2,
        "chaos_entries": 2,
        "tickers": ["FCG", "TIP", "TLT", "UNG"],
    }
    assert payload["signal_summary"] == {
        "signal_count_total": 8,
        "signals_above_ce_threshold": 7,
        "qualifying_signal_ids": [
            "SIG_2026_04_01_001",
            "SIG_2026_04_02_002",
            "SIG_2026_04_03_003",
            "SIG_2026_04_04_004",
            "SIG_2026_04_05_005",
            "SIG_2026_04_06_006",
            "SIG_2026_04_07_007",
        ],
        "status_counts_above_threshold": {
            "EXECUTED_CLEAN": 2,
            "EXECUTED_CHAOS": 2,
            "WATCHLIST": 3,
        },
        "qualifying_signals": [
            {"signal_id": "SIG_2026_04_01_001", "ticker": "TLT", "ce_score": 0.62, "status": "EXECUTED_CLEAN"},
            {"signal_id": "SIG_2026_04_02_002", "ticker": "TIP", "ce_score": 0.68, "status": "EXECUTED_CLEAN"},
            {"signal_id": "SIG_2026_04_03_003", "ticker": "UNG", "ce_score": 0.35, "status": "EXECUTED_CHAOS"},
            {"signal_id": "SIG_2026_04_04_004", "ticker": "FCG", "ce_score": 0.3, "status": "EXECUTED_CHAOS"},
            {"signal_id": "SIG_2026_04_05_005", "ticker": "GLD", "ce_score": 0.6, "status": "WATCHLIST"},
            {"signal_id": "SIG_2026_04_06_006", "ticker": "RTX", "ce_score": 0.71, "status": "WATCHLIST"},
            {"signal_id": "SIG_2026_04_07_007", "ticker": "ZIM", "ce_score": 0.66, "status": "WATCHLIST"},
        ],
    }
    assert payload["per_signal_attribution"] == [
        {
            "signal_id": "SIG_2026_04_01_001",
            "ticker": "TLT",
            "ce_score": 0.62,
            "status": "EXECUTED_CLEAN",
            "conversion_state": "CLEAN_ENTRY",
            "blocker_attribution": "NONE",
        },
        {
            "signal_id": "SIG_2026_04_02_002",
            "ticker": "TIP",
            "ce_score": 0.68,
            "status": "EXECUTED_CLEAN",
            "conversion_state": "CLEAN_ENTRY",
            "blocker_attribution": "NONE",
        },
        {
            "signal_id": "SIG_2026_04_03_003",
            "ticker": "UNG",
            "ce_score": 0.35,
            "status": "EXECUTED_CHAOS",
            "conversion_state": "CHAOS_ENTRY",
            "blocker_attribution": "REALM_BIS",
        },
        {
            "signal_id": "SIG_2026_04_04_004",
            "ticker": "FCG",
            "ce_score": 0.3,
            "status": "EXECUTED_CHAOS",
            "conversion_state": "CHAOS_ENTRY",
            "blocker_attribution": "REALM_BIS",
        },
        {
            "signal_id": "SIG_2026_04_05_005",
            "ticker": "GLD",
            "ce_score": 0.6,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "GSCE_PHASE_LOCK",
        },
        {
            "signal_id": "SIG_2026_04_06_006",
            "ticker": "RTX",
            "ce_score": 0.71,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "GSCE_PHASE_LOCK",
        },
        {
            "signal_id": "SIG_2026_04_07_007",
            "ticker": "ZIM",
            "ce_score": 0.66,
            "status": "WATCHLIST",
            "conversion_state": "NOT_EXECUTED",
            "blocker_attribution": "GSCE_PHASE_LOCK",
        },
    ]
    assert payload["derived_gate_states"] == {
        "GSCE_PHASE_LOCK": True,
        "CEE_OVERLOAD": False,
        "MTL_TIMING": False,
        "NAR_ARCHETYPE": False,
        "TAT_PRESSURE_STATE": False,
        "REALM_BIS": True,
    }
    assert payload["scm_review"] == {
        "scm_rate": 0.286,
        "scm_state": "LOW_CONVERSION",
        "diagnosis": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "gap_type": "CONVERSION_FRICTION",
    }
    assert payload["execution_policy"] == {
        "policy_state": "RESTRICTED",
        "position_sizing_cap": "QUARTER_UNIT",
        "allow_clean_entries": False,
        "allow_chaos_entries": False,
        "allow_new_risk": False,
        "allow_only_exits_and_reductions": True,
        "retain_watchlist_names": True,
        "chaos_entries_forbidden": True,
        "watchlist_action": "DO_NOT_FORCE_ENTRY",
        "required_clearance_gates": ["GSCE_PHASE_LOCK", "REALM_BIS"],
        "blocked_entry_states": ["EXECUTED_CHAOS"],
        "next_priority_action": "CLEAR_BLOCKERS_BEFORE_NEW_RISK",
        "minimum_conditions_to_improve": [
            "SCM state improves to PARTIAL_CONVERSION or better",
            "GSCE_PHASE_LOCK clears for above-threshold WATCHLIST names",
            "REALM_BIS clears by eliminating chaos conversions",
        ],
        "rationale": [
            "2 clean entries across 7 above-threshold signals",
            "SCM rate remains below PARTIAL_CONVERSION threshold",
            "3 above-threshold signals remained WATCHLIST",
            "2 above-threshold signals converted into CHAOS entries",
        ],
    }


def test_signal_ledger_rejects_unknown_status() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    ledger_path = scratch_dir / "signal_ledger_invalid_status.json"

    scratch_dir.mkdir(exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            [
                {
                    "signal_id": "SIG_BAD_001",
                    "ticker": "BAD",
                    "ce_score": 0.61,
                    "above_ce_threshold": True,
                    "status": "UNKNOWN_STATUS",
                }
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_signal_ledger(ledger_path)
    except ValueError as exc:
        assert "status must be one of" in str(exc)
    else:
        raise AssertionError("Expected load_signal_ledger to reject unknown status")
    finally:
        if ledger_path.exists():
            ledger_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_moltbook_loader_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "moltbook_loader.py"), "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines() == [
        "Moltbook Summary",
        "trade_close_count=4",
        "mw_signal_count=1",
        "tickers=FCG, TIP, TLT, UNG",
        "classifications=CHAOS_LOSS, GOOD_WIN, MARGINAL_WIN",
        "mw_signal_ids=MW_DIRECTION_V1_2026_04_19",
    ]


def test_signal_conversion_monitor_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "signal_conversion_monitor.py"), "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip().splitlines() == [
        "Signal Conversion Monitor",
        "scm_state=LOW_CONVERSION",
        "scm_rate=0.286",
        "clean_entries=2",
        "chaos_entries=2",
        "watchlist_non_conversions=3",
        "active_gates=GSCE_PHASE_LOCK, REALM_BIS",
        "policy_state=RESTRICTED",
        "allow_new_risk=false",
        "next_priority_action=CLEAR_BLOCKERS_BEFORE_NEW_RISK",
    ]


def test_signal_conversion_monitor_simulated_gsce_clear_transition() -> None:
    payload = build_signal_conversion_report(simulate_gsce_clear=True)
    watchlist_rows = {
        row["ticker"]: row for row in payload["watchlist_diagnostics"]["watchlist_signals"]
    }

    assert payload["derived_gate_states"]["GSCE_PHASE_LOCK"] is False
    assert payload["execution_policy"]["allow_new_risk"] is False
    assert watchlist_rows["RTX"]["candidate_conversion_state"] == "CLEAN_READY_PENDING"
    assert watchlist_rows["RTX"]["pre_entry_state"] == "CLEAN_READY_PENDING_TRIGGER"
    assert watchlist_rows["ZIM"]["candidate_conversion_state"] == "CLEAN_READY_PENDING"
    assert watchlist_rows["ZIM"]["pre_entry_state"] == "CLEAN_READY_PENDING_TRIGGER"
    assert watchlist_rows["GLD"]["watchlist_tier"] == "STANDARD"
    assert watchlist_rows["GLD"]["candidate_conversion_state"] == "NOT_EXECUTED"
    assert watchlist_rows["GLD"]["pre_entry_state"] == "NONE"


def test_signal_conversion_monitor_simulated_realm_bis_clear_transition() -> None:
    payload = build_signal_conversion_report(simulate_realm_bis_clear=True)
    watchlist_rows = {
        row["ticker"]: row for row in payload["watchlist_diagnostics"]["watchlist_signals"]
    }

    assert payload["derived_gate_states"]["GSCE_PHASE_LOCK"] is True
    assert payload["derived_gate_states"]["REALM_BIS"] is False
    assert payload["execution_policy"]["allow_new_risk"] is False
    assert payload["execution_policy"]["required_clearance_gates"] == ["GSCE_PHASE_LOCK"]
    assert watchlist_rows["RTX"]["candidate_conversion_state"] == "PROMOTABLE_WATCHLIST"
    assert watchlist_rows["RTX"]["pre_entry_state"] == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
    assert watchlist_rows["ZIM"]["pre_entry_state"] == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"


def test_signal_conversion_monitor_simulated_all_clear_transition() -> None:
    payload = build_signal_conversion_report(simulate_all_clear=True)
    watchlist_rows = {
        row["ticker"]: row for row in payload["watchlist_diagnostics"]["watchlist_signals"]
    }

    assert payload["derived_gate_states"]["GSCE_PHASE_LOCK"] is False
    assert payload["derived_gate_states"]["REALM_BIS"] is False
    assert payload["execution_policy"]["policy_state"] == "REVIEW_READY"
    assert payload["execution_policy"]["allow_new_risk"] is True
    assert payload["execution_policy"]["required_clearance_gates"] == []
    assert watchlist_rows["RTX"]["candidate_conversion_state"] == "CLEAN_ENTRY_ELIGIBLE"
    assert watchlist_rows["RTX"]["pre_entry_state"] == "CLEAN_ENTRY_ELIGIBLE"
    assert watchlist_rows["ZIM"]["candidate_conversion_state"] == "CLEAN_ENTRY_ELIGIBLE"
    assert watchlist_rows["ZIM"]["pre_entry_state"] == "CLEAN_ENTRY_ELIGIBLE"
    assert watchlist_rows["GLD"]["candidate_conversion_state"] == "NOT_EXECUTED"


def test_pipeline_health_report_builder_shape() -> None:
    payload = build_pipeline_health_report(include_tests=False, write_runtime=False)

    assert payload["operating_mode"] == "seeded"
    assert payload["truth_origin"] == "seeded"
    assert payload["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert payload["can_deploy_capital"] is False
    assert payload["what_should_i_do_next"] == "EXIT_NOW: UNG, FCG | CLEAR_GSCE_PHASE_LOCK_FOR: RTX, ZIM | DO NOT ADD NEW RISK"
    assert payload["entry_review_packets"] == []
    assert payload["transition_review_packets"] == []
    assert payload["packet_summary"] == {
        "entry_review_candidate_count": 0,
        "transition_review_candidate_count": 0,
        "entry_review_candidate_names": [],
        "transition_review_candidate_names": [],
        "packet_state": "NONE",
    }
    assert payload["transition_pressure_state"] == "STUCK_BLOCKED"
    assert payload["transition_readiness_state"] == "BLOCKED"
    assert payload["packet_transition_state"] == "NONE"
    assert payload["packet_entry_state"] == "NONE"
    assert payload["decision_review_state"] == "NONE"
    assert payload["scenario_transition_trends"]["LIVE"]["transition_readiness_state"] == "BLOCKED"
    assert payload["friction"]["friction_band"] == "HIGH_FRICTION"
    assert payload["friction"]["total_system_friction_score"] == 13.0
    assert payload["trends"]["snapshot_count"] >= 3
    assert "visibility_timing_context" in payload
    assert 0.0 <= payload["visibility_timing_context"]["average_light_score"] <= 1.0
    assert 0.0 <= payload["visibility_timing_context"]["average_shadow_score"] <= 1.0
    assert payload["open_positions_validation_summary"] == {
        "path": "moltbook/open_positions.json",
        "file_exists": True,
        "valid": True,
        "position_count": 4,
        "states": {"OPEN": 3, "EXIT_PENDING": 1},
        "errors": [],
    }
    assert payload["per_ticker_action_summary"] == {
        "summary_by_action": {
            "EXIT_NOW": 2,
            "REDUCE": 1,
            "HOLD": 0,
            "MONITOR": 1,
            "BLOCK_ENTRY": 3,
        },
        "highest_priority_actions": [
            {"ticker": "UNG", "action": "EXIT_NOW", "priority_score": 0.91},
            {"ticker": "FCG", "action": "EXIT_NOW", "priority_score": 0.88},
            {"ticker": "TLT", "action": "MONITOR", "priority_score": 0.82},
            {"ticker": "TIP", "action": "REDUCE", "priority_score": 0.79},
            {"ticker": "RTX", "action": "BLOCK_ENTRY", "priority_score": 0.71},
        ],
    }
    assert payload["scorecard"] == {
        "logging_quality": {"score": 10, "max_score": 10},
        "schema_reliability": {"score": 8, "max_score": 10},
        "end_to_end_wiring": {"score": 10, "max_score": 10},
        "self_correction_maturity": {"score": 10, "max_score": 10},
        "execution_readiness": {"score": 3, "max_score": 10},
    }


def test_pipeline_health_report_gsce_transition_preview() -> None:
    payload = build_pipeline_health_report(include_tests=False, write_runtime=False)

    queue_tickers = [row["ticker"] for row in payload["blocked_promotable_candidate_queue"]]
    preview_rows = {row["ticker"]: row for row in payload["gsce_clear_transition_preview"]}
    gate_preview = payload["gate_resolution_preview"]
    assert sorted(gate_preview) == ["all_clear", "gsce_clear", "live", "realm_bis_clear"]
    for scenario in gate_preview.values():
        assert "packet_summary" in scenario
        assert "entry_review_packets" in scenario
        assert "transition_review_packets" in scenario

    assert queue_tickers == ["RTX", "ZIM"]
    assert sorted(preview_rows) == ["RTX", "ZIM"]
    assert payload["policy"]["allow_new_risk"] is False
    assert gate_preview["live"]["policy_state"] == "RESTRICTED"
    assert gate_preview["gsce_clear"]["policy_state"] == "RESTRICTED"
    assert gate_preview["realm_bis_clear"]["policy_state"] == "RESTRICTED"
    assert gate_preview["all_clear"]["policy_state"] == "REVIEW_READY"
    assert preview_rows["RTX"]["current_pre_entry_state"] == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
    assert preview_rows["RTX"]["simulated_pre_entry_state"] == "CLEAN_READY_PENDING_TRIGGER"
    assert preview_rows["RTX"]["current_candidate_conversion_state"] == "PROMOTABLE_WATCHLIST"
    assert preview_rows["RTX"]["simulated_candidate_conversion_state"] == "CLEAN_READY_PENDING"
    assert preview_rows["RTX"]["gate_required_to_flip"] == "GSCE_PHASE_LOCK"
    assert preview_rows["RTX"]["would_still_allow_new_risk"] is False
    assert preview_rows["RTX"]["simulated_action"] == "MONITOR"
    assert preview_rows["ZIM"]["simulated_pre_entry_state"] == "CLEAN_READY_PENDING_TRIGGER"
    assert payload["entry_review_packets"] == []
    assert payload["transition_review_packets"] == []
    assert gate_preview["live"]["packet_summary"]["packet_state"] == "NONE"
    assert gate_preview["gsce_clear"]["packet_summary"] == {
        "entry_review_candidate_count": 0,
        "transition_review_candidate_count": 2,
        "entry_review_candidate_names": [],
        "transition_review_candidate_names": ["RTX", "ZIM"],
        "packet_state": "TRANSITION_REVIEW_READY",
    }
    gsce_packets = {row["ticker"]: row for row in gate_preview["gsce_clear"]["transition_review_packets"]}
    assert gsce_packets["RTX"]["target_pre_entry_state"] == "CLEAN_READY_PENDING_TRIGGER"
    assert gsce_packets["RTX"]["remaining_blockers"] == ["REALM_BIS"]
    assert gsce_packets["RTX"]["recommended_action"] == "MONITOR"
    assert gsce_packets["RTX"]["thesis_tag"] == "PROMOTABLE_CLEAN_CANDIDATE"
    assert gsce_packets["RTX"]["sizing_allowed_now"] is False
    assert gsce_packets["RTX"]["review_checklist_status"] == "INCOMPLETE"
    assert gsce_packets["RTX"]["operator_decision_state"] == "NEEDS_CHECKLIST"
    assert "policy_allows_sizing_now" in gsce_packets["RTX"]["review_checklist_missing_items"]
    assert gate_preview["gsce_clear"]["decision_review_state"] == "TRANSITION_REVIEW_READY"
    assert gate_preview["all_clear"]["packet_summary"]["packet_state"] == "ENTRY_REVIEW_READY"


def test_pipeline_health_report_simulated_all_clear_preview() -> None:
    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=True,
        simulate_all_clear=True,
    )

    assert payload["simulation_mode"] == "ALL_CLEAR"
    assert payload["simulation_writes_runtime"] is False
    assert payload["policy"]["policy_state"] == "REVIEW_READY"
    assert payload["policy"]["allow_new_risk"] is True
    assert payload["system_readiness_state"] == "LIMITED_DEPLOY"
    assert payload["can_deploy_capital"] is False
    assert payload["queue_sync_state"] == "UNKNOWN"
    assert payload["transition_pressure_state"] == "READY_BUT_UNTRIGGERED"
    assert payload["transition_readiness_state"] == "ENTRY_REVIEW_READY"
    assert payload["packet_transition_state"] == "NONE"
    assert payload["packet_entry_state"] == "ENTRY_REVIEW_READY"
    assert payload["decision_review_state"] == "ENTRY_REVIEW_READY"
    assert payload["scenario_transition_trends"]["ALL_CLEAR"]["packet_entry_state"] == "ENTRY_REVIEW_READY"
    assert (
        payload["scenario_transition_trends"]["ALL_CLEAR"]["transition_readiness_state"]
        == "ENTRY_REVIEW_READY"
    )
    assert payload["packet_summary"] == {
        "entry_review_candidate_count": 2,
        "transition_review_candidate_count": 0,
        "entry_review_candidate_names": ["RTX", "ZIM"],
        "transition_review_candidate_names": [],
        "packet_state": "ENTRY_REVIEW_READY",
    }
    assert payload["next_state_if_all_clear"] == {
        "tickers": ["RTX", "ZIM"],
        "pre_entry_state": "CLEAN_ENTRY_ELIGIBLE",
        "candidate_conversion_state": "CLEAN_ENTRY_ELIGIBLE",
        "action": "REVIEW_FOR_ENTRY",
        "policy_state": "REVIEW_READY",
        "allow_new_risk": True,
        "active_blockers": [],
    }
    all_clear_preview = {
        row["ticker"]: row
        for row in payload["gate_resolution_preview"]["all_clear"]["candidates"]
    }
    assert all_clear_preview["RTX"]["simulated_pre_entry_state"] == "CLEAN_ENTRY_ELIGIBLE"
    assert all_clear_preview["RTX"]["simulated_action"] == "REVIEW_FOR_ENTRY"
    assert all_clear_preview["ZIM"]["simulated_pre_entry_state"] == "CLEAN_ENTRY_ELIGIBLE"
    assert payload["transition_review_packets"] == []
    entry_packets = {packet["ticker"]: packet for packet in payload["entry_review_packets"]}
    assert sorted(entry_packets) == ["RTX", "ZIM"]
    for ticker, signal_id, priority_score, ce_score in [
        ("RTX", "SIG_2026_04_06_006", 0.71, 0.71),
        ("ZIM", "SIG_2026_04_07_007", 0.66, 0.66),
    ]:
        packet = entry_packets[ticker]
        assert packet["ticker"] == ticker
        assert packet["signal_id"] == signal_id
        assert packet["priority_score"] == priority_score
        assert packet["ce_score"] == ce_score
        assert packet["watchlist_tier"] == "PROMOTABLE"
        assert packet["current_pre_entry_state"] == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE"
        assert packet["target_pre_entry_state"] == "CLEAN_ENTRY_ELIGIBLE"
        assert packet["current_candidate_conversion_state"] == "PROMOTABLE_WATCHLIST"
        assert packet["target_candidate_conversion_state"] == "CLEAN_ENTRY_ELIGIBLE"
        assert packet["thesis_tag"] == "PROMOTABLE_CLEAN_CANDIDATE"
        assert packet["why_eligible_now"] == "GSCE_PHASE_LOCK and REALM_BIS cleared; promotable candidate advanced to review-ready state."
        assert packet["blockers_cleared"] == ["GSCE_PHASE_LOCK", "REALM_BIS"]
        assert packet["remaining_blockers"] == []
        assert packet["blocker_clearance_path"] == {
            "required_for_target_state": ["GSCE_PHASE_LOCK", "REALM_BIS"],
            "cleared_for_target_state": ["GSCE_PHASE_LOCK", "REALM_BIS"],
            "remaining_for_target_state": [],
            "live_active_blockers": ["GSCE_PHASE_LOCK", "REALM_BIS"],
            "remaining_blockers": [],
        }
        assert packet["scm_context"] == {
            "scm_state": "LOW_CONVERSION",
            "scm_rate": 0.286,
            "diagnosis": ["UNKNOWN_BLOCKER"],
            "signal_above_threshold": True,
        }
        assert packet["execution_policy_context"] == {
            "policy_state": "REVIEW_READY",
            "allow_new_risk": True,
            "position_sizing_cap": "QUARTER_UNIT",
            "required_clearance_gates": [],
            "next_priority_action": "REVIEW_PROMOTABLE_CANDIDATES",
        }
        assert packet["policy_state"] == "REVIEW_READY"
        assert packet["allow_new_risk"] is True
        assert packet["position_sizing_cap"] == "QUARTER_UNIT"
        assert packet["sizing_allowed_now"] is True
        assert packet["sizing_cap_now"] == "QUARTER_UNIT"
        assert packet["open_position_conflict"] is False
        assert packet["existing_exposure_conflict"] is False
        assert packet["recommended_action"] == "REVIEW_FOR_ENTRY"
        assert packet["action_reasons"] == [
            "Promotable clean candidate is fully gate-cleared and ready for entry review"
        ]
        assert packet["review_checklist_status"] == "COMPLETE"
        assert packet["review_checklist_missing_items"] == []
        assert packet["operator_decision_state"] == "READY_FOR_OPERATOR_DECISION"
        assert [item["name"] for item in packet["checklist_items"]] == [
            "signal_still_promotable",
            "signal_above_threshold",
            "no_open_position_conflict",
            "no_existing_exposure_conflict",
            "policy_allows_sizing_now",
            "required_blockers_cleared",
            "packet_fields_populated",
        ]
        assert all(item["passed"] is True for item in packet["checklist_items"])
        assert packet["operator_note"] == "Promotable clean candidate is fully gate-cleared and ready for operator entry review."


def test_snapshot_row_tracks_clean_entry_eligible_fields_from_simulated_state() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    row = build_snapshot_row(runtime_state=runtime_state)

    assert row["clean_ready_pending_trigger_count"] == 0
    assert row["clean_ready_pending_trigger_names"] == []
    assert row["clean_entry_eligible_count"] == 2
    assert row["clean_entry_eligible_names"] == ["RTX", "ZIM"]
    assert row["transition_review_candidate_count"] == 0
    assert row["transition_review_candidate_names"] == []
    assert row["entry_review_candidate_count"] == 2
    assert row["entry_review_candidate_names"] == ["RTX", "ZIM"]
    assert row["allow_new_risk"] is True
    assert row["transition_state_rows"] == [
        {
            "signal_id": "SIG_2026_04_06_006",
            "ticker": "RTX",
            "watchlist_tier": "PROMOTABLE",
            "candidate_conversion_state": "CLEAN_ENTRY_ELIGIBLE",
            "pre_entry_state": "CLEAN_ENTRY_ELIGIBLE",
        },
        {
            "signal_id": "SIG_2026_04_07_007",
            "ticker": "ZIM",
            "watchlist_tier": "PROMOTABLE",
            "candidate_conversion_state": "CLEAN_ENTRY_ELIGIBLE",
            "pre_entry_state": "CLEAN_ENTRY_ELIGIBLE",
        },
    ]


def test_snapshot_rows_are_scenario_tagged_for_live_and_simulation_states() -> None:
    live_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    gsce_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_gsce_clear=True)
    )
    realm_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_realm_bis_clear=True)
    )
    all_clear_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )

    live_row = build_snapshot_row(runtime_state=live_state)
    gsce_row = build_snapshot_row(runtime_state=gsce_state)
    realm_row = build_snapshot_row(runtime_state=realm_state)
    all_clear_row = build_snapshot_row(runtime_state=all_clear_state)

    assert live_row["scenario"] == "LIVE"
    assert gsce_row["scenario"] == "GSCE_CLEAR"
    assert realm_row["scenario"] == "REALM_BIS_CLEAR"
    assert all_clear_row["scenario"] == "ALL_CLEAR"
    assert [row["pre_entry_state"] for row in live_row["transition_state_rows"]] == [
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
    ]
    assert [row["pre_entry_state"] for row in gsce_row["transition_state_rows"]] == [
        "CLEAN_READY_PENDING_TRIGGER",
        "CLEAN_READY_PENDING_TRIGGER",
    ]
    assert [row["pre_entry_state"] for row in realm_row["transition_state_rows"]] == [
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
    ]
    assert [row["pre_entry_state"] for row in all_clear_row["transition_state_rows"]] == [
        "CLEAN_ENTRY_ELIGIBLE",
        "CLEAN_ENTRY_ELIGIBLE",
    ]
    assert gsce_row["transition_review_candidate_count"] == 2
    assert gsce_row["transition_review_candidate_names"] == ["RTX", "ZIM"]
    assert all_clear_row["entry_review_candidate_count"] == 2
    assert all_clear_row["entry_review_candidate_names"] == ["RTX", "ZIM"]


def test_run_diagnostics_pipeline_simulated_gsce_clear_preview() -> None:
    payload = run_diagnostics_pipeline(simulate_gsce_clear=True, write_runtime=True)

    assert payload["simulation_mode"] == "GSCE_CLEAR"
    assert payload["simulation_writes_runtime"] is False
    assert payload["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert payload["can_deploy_capital"] is False
    assert payload["policy"]["allow_new_risk"] is False
    assert payload["transition_readiness_state"] == "ADVANCING"
    assert payload["scenario_transition_trends"]["GSCE_CLEAR"]["packet_transition_state"] == "TRANSITION_REVIEW_READY"
    assert payload["decision_review_state"] == "TRANSITION_REVIEW_READY"
    assert payload["entry_review_packets"] == []
    assert [packet["ticker"] for packet in payload["transition_review_packets"]] == ["RTX", "ZIM"]
    assert payload["packet_summary"]["packet_state"] == "TRANSITION_REVIEW_READY"
    simulated_actions = {
        row["ticker"]: row
        for row in payload["gate_resolution_preview"]["gsce_clear"]["candidates"]
    }
    assert simulated_actions["RTX"]["simulated_action"] == "MONITOR"
    assert simulated_actions["ZIM"]["simulated_action"] == "MONITOR"


def test_run_diagnostics_pipeline_simulated_realm_bis_clear_preview() -> None:
    payload = run_diagnostics_pipeline(simulate_realm_bis_clear=True, write_runtime=True)

    assert payload["simulation_mode"] == "REALM_BIS_CLEAR"
    assert payload["simulation_writes_runtime"] is False
    assert payload["policy"]["policy_state"] == "RESTRICTED"
    assert payload["policy"]["allow_new_risk"] is False
    assert payload["transition_pressure_state"] == "STUCK_BLOCKED"
    assert payload["transition_readiness_state"] == "BLOCKED"
    assert payload["entry_review_packets"] == []
    assert payload["transition_review_packets"] == []
    assert payload["packet_summary"]["packet_state"] == "NONE"
    assert payload["what_should_i_do_next"] == "EXIT_NOW: UNG, FCG | CLEAR_GSCE_PHASE_LOCK_FOR: RTX, ZIM | DO NOT ADD NEW RISK"


def test_run_diagnostics_pipeline_simulated_all_clear_preview() -> None:
    payload = run_diagnostics_pipeline(simulate_all_clear=True, write_runtime=True)

    assert payload["simulation_mode"] == "ALL_CLEAR"
    assert payload["simulation_writes_runtime"] is False
    assert payload["policy"]["policy_state"] == "REVIEW_READY"
    assert payload["policy"]["allow_new_risk"] is True
    assert payload["transition_pressure_state"] == "READY_BUT_UNTRIGGERED"
    assert payload["transition_readiness_state"] == "ENTRY_REVIEW_READY"
    assert payload["scenario_transition_trends"]["ALL_CLEAR"]["packet_entry_state"] == "ENTRY_REVIEW_READY"
    assert payload["packet_summary"]["packet_state"] == "ENTRY_REVIEW_READY"
    assert payload["decision_review_state"] == "ENTRY_REVIEW_READY"
    assert payload["what_should_i_do_next"] == "EXIT_NOW: UNG, FCG | REVIEW_FOR_ENTRY: RTX, ZIM | REVIEW_PROMOTABLE_CANDIDATES"
    assert [packet["ticker"] for packet in payload["entry_review_packets"]] == ["RTX", "ZIM"]


def test_run_diagnostics_pipeline_persists_scenario_tagged_snapshot_rows() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "pipeline_scenario_snapshots.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    try:
        live_payload = run_diagnostics_pipeline(
            write_runtime=False,
            write_snapshot=True,
            snapshot_log_path=log_path,
        )
        gsce_payload = run_diagnostics_pipeline(
            write_runtime=False,
            write_snapshot=True,
            snapshot_log_path=log_path,
            simulate_gsce_clear=True,
        )
        realm_payload = run_diagnostics_pipeline(
            write_runtime=False,
            write_snapshot=True,
            snapshot_log_path=log_path,
            simulate_realm_bis_clear=True,
        )
        all_clear_payload = run_diagnostics_pipeline(
            write_runtime=False,
            write_snapshot=True,
            snapshot_log_path=log_path,
            simulate_all_clear=True,
        )

        rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [row["scenario"] for row in rows] == [
            "LIVE",
            "GSCE_CLEAR",
            "REALM_BIS_CLEAR",
            "ALL_CLEAR",
        ]

        live_row, gsce_row, realm_row, all_clear_row = rows
        assert live_row["transition_state_rows"] == [
            {
                "signal_id": "SIG_2026_04_06_006",
                "ticker": "RTX",
                "watchlist_tier": "PROMOTABLE",
                "candidate_conversion_state": "PROMOTABLE_WATCHLIST",
                "pre_entry_state": "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
            },
            {
                "signal_id": "SIG_2026_04_07_007",
                "ticker": "ZIM",
                "watchlist_tier": "PROMOTABLE",
                "candidate_conversion_state": "PROMOTABLE_WATCHLIST",
                "pre_entry_state": "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
            },
        ]
        assert gsce_row["transition_review_candidate_count"] == 2
        assert gsce_row["transition_review_candidate_names"] == ["RTX", "ZIM"]
        assert [row["pre_entry_state"] for row in gsce_row["transition_state_rows"]] == [
            "CLEAN_READY_PENDING_TRIGGER",
            "CLEAN_READY_PENDING_TRIGGER",
        ]
        assert realm_row["transition_review_candidate_count"] == 0
        assert realm_row["entry_review_candidate_count"] == 0
        assert all_clear_row["entry_review_candidate_count"] == 2
        assert all_clear_row["entry_review_candidate_names"] == ["RTX", "ZIM"]
        assert [row["pre_entry_state"] for row in all_clear_row["transition_state_rows"]] == [
            "CLEAN_ENTRY_ELIGIBLE",
            "CLEAN_ENTRY_ELIGIBLE",
        ]

        trend_report = build_trend_report(log_path=log_path, write_runtime=False)
        assert trend_report["scenario_transition_trends"]["LIVE"]["snapshot_count"] == 1
        assert trend_report["scenario_transition_trends"]["LIVE"]["transition_pressure_state"] == "STUCK_BLOCKED"
        assert trend_report["scenario_transition_trends"]["LIVE"]["packet_entry_state"] == "NONE"
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["snapshot_count"] == 1
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["clean_ready_pending_transition_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "persistent_names": [
                {"ticker": "RTX", "consecutive_snapshots": 1},
                {"ticker": "ZIM", "consecutive_snapshots": 1},
            ],
        }
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["transition_review_candidate_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "consecutive_snapshots": 1,
        }
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["packet_transition_state"] == "TRANSITION_REVIEW_READY"
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["transition_readiness_state"] == "ADVANCING"
        assert trend_report["scenario_transition_trends"]["ALL_CLEAR"]["snapshot_count"] == 1
        assert trend_report["scenario_transition_trends"]["ALL_CLEAR"]["clean_entry_eligible_transition_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "persistent_names": [
                {"ticker": "RTX", "consecutive_snapshots": 1},
                {"ticker": "ZIM", "consecutive_snapshots": 1},
            ],
        }
        assert trend_report["scenario_transition_trends"]["ALL_CLEAR"]["entry_review_candidate_streak"] == {
            "current_count": 2,
            "current_names": ["RTX", "ZIM"],
            "consecutive_snapshots": 1,
        }
        assert trend_report["scenario_transition_trends"]["ALL_CLEAR"]["packet_entry_state"] == "ENTRY_REVIEW_READY"
        assert trend_report["scenario_transition_trends"]["ALL_CLEAR"]["transition_readiness_state"] == "ENTRY_REVIEW_READY"

        assert live_payload["simulation_mode"] == "LIVE"
        assert gsce_payload["simulation_mode"] == "GSCE_CLEAR"
        assert realm_payload["simulation_mode"] == "REALM_BIS_CLEAR"
        assert all_clear_payload["simulation_mode"] == "ALL_CLEAR"
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_run_diagnostics_pipeline_write_snapshot_defaults_to_canonical_log_path(
    monkeypatch,
) -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    log_path = scratch_dir / "pipeline_default_snapshot_path.jsonl"
    scratch_dir.mkdir(exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    try:
        monkeypatch.setattr(run_diagnostics_pipeline_module, "SNAPSHOT_LOG_PATH", log_path)
        payload = run_diagnostics_pipeline_module.run_diagnostics_pipeline(
            write_runtime=False,
            write_snapshot=True,
            simulate_gsce_clear=True,
        )

        rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(rows) == 1
        assert rows[0]["scenario"] == "GSCE_CLEAR"
        assert rows[0]["transition_review_candidate_count"] == 2
        assert rows[0]["transition_review_candidate_names"] == ["RTX", "ZIM"]
        assert [row["pre_entry_state"] for row in rows[0]["transition_state_rows"]] == [
            "CLEAN_READY_PENDING_TRIGGER",
            "CLEAN_READY_PENDING_TRIGGER",
        ]

        trend_report = build_trend_report(log_path=log_path, write_runtime=False)
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["snapshot_count"] == 1
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["packet_transition_state"] == "TRANSITION_REVIEW_READY"
        assert trend_report["scenario_transition_trends"]["GSCE_CLEAR"]["transition_readiness_state"] == "ADVANCING"
        assert payload["simulation_mode"] == "GSCE_CLEAR"
    finally:
        if log_path.exists():
            log_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_all_clear_packet_conflict_blocks_operator_decision() -> None:
    scratch_dir = REPO_ROOT / "tests" / "_tmp_runtime"
    open_positions_path = scratch_dir / "conflicting_open_positions.json"
    scratch_dir.mkdir(exist_ok=True)
    open_positions_path.write_text(
        json.dumps(
            [
                {
                    "ticker": "RTX",
                    "entry_price": 100.0,
                    "current_price": 101.0,
                    "pnl_pct": 0.01,
                    "position_size": "QUARTER_UNIT",
                    "state": "OPEN",
                    "chaos_flag": False,
                    "entry_type": "CLEAN",
                    "thesis_cluster": "AEROSPACE_DEFENSE",
                    "stop_loss": 98.0,
                    "take_profit": 106.0,
                    "time_in_trade": "2d",
                    "priority_score": 0.75,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        payload = build_pipeline_health_report(
            include_tests=False,
            write_runtime=False,
            simulate_all_clear=True,
            open_positions_path=open_positions_path,
        )
        packets = {packet["ticker"]: packet for packet in payload["entry_review_packets"]}
        assert packets["RTX"]["open_position_conflict"] is True
        assert packets["RTX"]["existing_exposure_conflict"] is True
        assert packets["RTX"]["sizing_allowed_now"] is False
        assert packets["RTX"]["sizing_cap_now"] == "NONE"
        assert packets["RTX"]["review_checklist_status"] == "BLOCKED"
        assert packets["RTX"]["operator_decision_state"] == "BLOCKED_BY_CONFLICT"
        assert payload["decision_review_state"] == "BLOCKED_BY_CONFLICT"
    finally:
        if open_positions_path.exists():
            open_positions_path.unlink()
        if scratch_dir.exists() and not any(scratch_dir.iterdir()):
            scratch_dir.rmdir()


def test_entry_review_packet_with_missing_required_fields_needs_checklist() -> None:
    live_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    scenario_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    for row in live_state["watchlist_diagnostics"]["watchlist_signals"]:
        if row["ticker"] == "RTX":
            row["signal_id"] = ""
    for row in scenario_state["watchlist_diagnostics"]["watchlist_signals"]:
        if row["ticker"] == "RTX":
            row["signal_id"] = ""

    action_report = build_action_report(runtime_state=scenario_state, write_runtime=False)
    packets = build_entry_review_packets(
        live_state=live_state,
        scenario_state=scenario_state,
        scenario_action_report=action_report,
        open_positions=[],
    )
    packets_by_ticker = {packet["ticker"]: packet for packet in packets}
    assert packets_by_ticker["RTX"]["review_checklist_status"] == "INCOMPLETE"
    assert packets_by_ticker["RTX"]["operator_decision_state"] == "NEEDS_CHECKLIST"
    assert "packet_fields_populated" in packets_by_ticker["RTX"]["review_checklist_missing_items"]
    assert packets_by_ticker["ZIM"]["review_checklist_status"] == "COMPLETE"
    assert packets_by_ticker["ZIM"]["operator_decision_state"] == "READY_FOR_OPERATOR_DECISION"


def test_pipeline_health_report_cli_json_shape() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "pipeline_health_report.py"), "--no-write"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["system_readiness_state"] == "DO_NOT_DEPLOY"
    assert payload["can_deploy_capital"] is False
    assert payload["bridge_mode"] == "seeded"
    assert payload["bridge_mode_reason"] == "no external observation mode requested"
    assert payload["bridge_mode_safety_state"] == "paper_safe_only"
    assert payload["scm"]["scm_rate"] == 0.286
    assert payload["policy"]["policy_state"] == "RESTRICTED"
    assert payload["friction"]["friction_band"] == "HIGH_FRICTION"


def test_pipeline_health_report_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "pipeline_health_report.py"), "--summary", "--no-write"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Pipeline Health Report"
    assert lines[1] == "operating_mode=seeded"
    assert lines[2] == "truth_origin=seeded"
    assert lines[3] in {"git_clean=true", "git_clean=false"}
    assert "tests_invoked=false" in lines
    assert "tests_passed=None" in lines
    assert "system_readiness_state=DO_NOT_DEPLOY" in lines
    assert "can_deploy_capital=false" in lines
    assert "scm_state=LOW_CONVERSION" in lines
    assert "policy_state=RESTRICTED" in lines
    assert "friction_band=HIGH_FRICTION" in lines
    assert "perception_control_state=CONSTRAINED" in lines
    assert any(line.startswith("attention_proxy=state=") for line in lines)
    assert any(line.startswith("attention_proxy_inputs=") for line in lines)
    assert any(line.startswith("narrative_proxy_advisory=") for line in lines)
    assert "feedback_learning_state=INSUFFICIENT_FEEDBACK" in lines
    assert "feedback_cases_total=3" in lines
    assert "feedback_success_rate=0.6667" in lines
    assert "feedback_top_failure_mode=FAIL_SIGNAL" in lines
    assert "feedback_readiness_penalty=0.05" in lines
    assert "moltbook_feedback_available=true" in lines
    assert "bridge_mode=seeded" in lines
    assert "bridge_mode_reason=no external observation mode requested" in lines
    assert "bridge_mode_safety_state=paper_safe_only" in lines
    assert any(line.startswith("suggested_feedback_adjustments=") for line in lines)
    assert (
        "what_should_i_do_next=EXIT_NOW: UNG, FCG | CLEAR_GSCE_PHASE_LOCK_FOR: RTX, ZIM | DO NOT ADD NEW RISK"
        in lines
    )
    assert any(line.startswith("scorecard=") for line in lines)
    perception_metrics_line = next(
        line for line in lines if line.startswith("perception_metrics=")
    )
    assert "noise_suppression_ratio=0.429" in perception_metrics_line
    assert "signal_survival_rate=0.5" in perception_metrics_line
    average_signal_lux = float(
        perception_metrics_line.split("average_signal_lux=", maxsplit=1)[1]
    )
    assert average_signal_lux == pytest.approx(0.645, abs=0.001)
    assert (
        "perception_advisory=AMPLIFICATION WITHOUT SURVIVAL - injected signals failing gravity"
        in lines
    )


def test_pipeline_health_report_summary_cli_gsce_clear_includes_transition_candidates() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "pipeline_health_report.py"),
            "--summary",
            "--no-write",
            "--simulate-gsce-clear",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Pipeline Health Report"
    assert "simulation_mode=GSCE_CLEAR" in lines
    assert "operating_mode=seeded" in lines
    assert "truth_origin=synthetic" in lines
    assert "system_readiness_state=DO_NOT_DEPLOY" in lines
    assert "can_deploy_capital=false" in lines
    assert "policy_state=RESTRICTED" in lines
    assert "what_should_i_do_next=EXIT_NOW: UNG, FCG | ELIMINATE_REALM_BIS | DO NOT ADD NEW RISK" in lines
    assert any(line.startswith("scorecard=") for line in lines)
    assert "transition_review_candidates=RTX, ZIM" in lines
    assert "decision_review_state=TRANSITION_REVIEW_READY" in lines
    assert "transition_readiness_state=ADVANCING" in lines


def test_pipeline_health_report_summary_cli_all_clear_includes_entry_candidates() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "pipeline_health_report.py"),
            "--summary",
            "--no-write",
            "--simulate-all-clear",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Pipeline Health Report"
    assert "simulation_mode=ALL_CLEAR" in lines
    assert "operating_mode=seeded" in lines
    assert "truth_origin=synthetic" in lines
    assert "system_readiness_state=LIMITED_DEPLOY" in lines
    assert "can_deploy_capital=false" in lines
    assert "policy_state=REVIEW_READY" in lines
    assert "what_should_i_do_next=EXIT_NOW: UNG, FCG | REVIEW_FOR_ENTRY: RTX, ZIM | REVIEW_PROMOTABLE_CANDIDATES" in lines
    assert any(line.startswith("scorecard=") for line in lines)
    assert "entry_review_candidates=RTX, ZIM" in lines
    assert "decision_review_state=ENTRY_REVIEW_READY" in lines
    assert "transition_readiness_state=ENTRY_REVIEW_READY" in lines
